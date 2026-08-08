"""API endpoints: submit generation, query status, download results."""

import asyncio
import io
import json
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings
from app.models.generate import (
    GenerateRequest,
    ChartConfig,
    GenerationMode,
    GenerationStrategy,
    MaterialFile,
    OutlineRequest,
    OutlineResponse,
    AbstractRequest,
    ReferenceSearchRequest,
    PaperType,
    ReferenceStyle,
)
from app.models.task import GenerateResponse, TaskInfo, TaskStatus
from app.services import outline_service
from app.services import preview_service
from app.services import history_service
from app.services import deepseek, deepseek_service
from app.services import model_service
from app.services import material_service
from app.services import reference_search
from app.generation.service import ContentGenerator
from app.services.chart_service import CHART_TYPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


def _task_dir(task_id: str) -> Path:
    return settings.output_dir / task_id


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    http_request: Request,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    major: Annotated[str, Form(min_length=1, max_length=100)],
    paper_type: Annotated[PaperType, Form()] = "课程论文",
    word_count: Annotated[int, Form(ge=500, le=100_000)] = 3000,
    chart_enabled: Annotated[bool, Form()] = False,
    reference_style: Annotated[ReferenceStyle, Form()] = "gb7714",
    generation_mode: Annotated[GenerationMode, Form()] = "auto",
    outline: Annotated[str | None, Form()] = None,
    chart_config: Annotated[str | None, Form()] = None,
    special_requirements: Annotated[str | None, Form()] = None,
    generation_strategy: Annotated[GenerationStrategy, Form()] = "section",
    model_id: Annotated[str | None, Form()] = None,
    template_id: Annotated[str, Form()] = "",
    material_kinds: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    abstract: Annotated[str | None, Form()] = None,
    keywords: Annotated[str | None, Form()] = None,
    references: Annotated[str | None, Form()] = None,
    draft_mode: Annotated[bool, Form()] = False,
) -> GenerateResponse:
    """提交论文生成任务，返回 task_id（任务异步执行）。"""
    if generation_mode == "outline" and not (outline or "").strip():
        raise HTTPException(
            status_code=400,
            detail="大纲模式（generation_mode=outline）必须提供 outline 参数",
        )
    parsed_chart_config: ChartConfig | None = None
    if chart_config and chart_config.strip():
        try:
            parsed_chart_config = ChartConfig.model_validate_json(chart_config)
        except Exception:  # noqa: BLE001 - 转为 400
            raise HTTPException(
                status_code=400,
                detail="chart_config 格式不正确，应为 JSON："
                       '{"enabled":true,"count":5,"types":["bar","line"]}',
            )
        unknown = [t for t in parsed_chart_config.types if t not in CHART_TYPES]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的图表类型：{', '.join(unknown)}。"
                       f"支持：{', '.join(CHART_TYPES)}",
            )

    # 解析资料类型（JSON 数组，与 files 一一对应）
    kinds: list[str] | None = None
    if material_kinds and material_kinds.strip():
        try:
            parsed_kinds = json.loads(material_kinds)
            if not isinstance(parsed_kinds, list):
                raise ValueError
            kinds = [str(k) for k in parsed_kinds]
        except Exception:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="material_kinds 格式不正确，应为 JSON 数组，如 "
                       '["开题报告","其他资料"]',
            )

    # 解析自定义关键词（JSON 数组，与 abstract 一起覆盖自动生成）
    parsed_keywords: list[str] = []
    if keywords and keywords.strip():
        try:
            parsed_kw = json.loads(keywords)
            if isinstance(parsed_kw, list):
                parsed_keywords = [str(k).strip() for k in parsed_kw if str(k).strip()]
        except Exception:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="keywords 格式不正确，应为 JSON 数组，如 [\"摘要\",\"关键词\"]",
            )

    # 解析用户选择的参考文献引文（JSON 数组，覆盖自动生成）
    parsed_references: list[str] = []
    if references and references.strip():
        try:
            parsed_refs = json.loads(references)
            if isinstance(parsed_refs, list):
                parsed_references = [str(r).strip() for r in parsed_refs if str(r).strip()]
        except Exception:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="references 格式不正确，应为 JSON 数组",
            )

    request = GenerateRequest(
        title=title, major=major, paper_type=paper_type,
        word_count=word_count, chart_enabled=chart_enabled,
        reference_style=reference_style,
        generation_mode=generation_mode, outline=outline,
        chart_config=parsed_chart_config,
        special_requirements=special_requirements,
        generation_strategy=generation_strategy,
        model_id=model_id,
        template_id=template_id,
        abstract=(abstract or "").strip() or None,
        keywords=parsed_keywords,
        references=parsed_references,
        draft_mode=draft_mode,
    )
    task_id = uuid.uuid4().hex
    task_dir = _task_dir(task_id)
    task_dir.mkdir(parents=True, exist_ok=False)

    # 参考资料：保存 + 提取文本，合并进特殊要求供 AI 参考
    materials: list[MaterialFile] = []
    if files:
        try:
            material_list = material_service.save_and_extract(files, kinds, task_dir)
            materials = [MaterialFile(**m) for m in material_list]
            ctx = material_service.build_materials_context(material_list)
            if ctx:
                req_text = request.special_requirements or ""
                combined = (req_text.rstrip() + "\n\n" if req_text.strip() else "") + \
                    f"【参考资料】\n{ctx}"
                request = request.model_copy(update={
                    "special_requirements": combined,
                    "materials": materials,
                })
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if materials:
        request = request.model_copy(update={"materials": materials})

    (task_dir / "request.json").write_text(
        request.model_dump_json(), encoding="utf-8")

    manager = http_request.app.state.task_manager
    manager.create(task_id)
    history_service.create_record(task_id, request.model_dump())
    manager.submit(task_id)
    logger.info("Task %s submitted: title=%s major=%s type=%s charts=%s files=%d",
                task_id, request.title, request.major, request.paper_type,
                request.chart_enabled, len(materials))
    return GenerateResponse(task_id=task_id)


@router.post("/outline/generate", response_model=OutlineResponse)
async def outline_generate(request: OutlineRequest) -> OutlineResponse:
    """根据标题/专业/论文类型/字数生成论文大纲（章节结构 + 预计字数分配）。"""
    from contextlib import nullcontext
    model_cfg = model_service.resolve_model(request.model_id)
    ctx = deepseek.connection(model_cfg) if model_cfg else nullcontext()
    if model_cfg is not None:
        with ctx:
            try:
                result = deepseek_service.generate_outline(
                    title=request.title, major=request.major,
                    paper_type=request.paper_type, word_count=request.word_count)
                return OutlineResponse(**result)
            except deepseek.DeepSeekError as exc:
                raise HTTPException(
                    status_code=502, detail=f"AI 模型生成大纲失败：{exc}")
    result = outline_service.generate_outline(
        title=request.title, major=request.major,
        paper_type=request.paper_type, word_count=request.word_count,
    )
    return OutlineResponse(**result)


@router.post("/abstract/generate")
async def abstract_generate(request: AbstractRequest) -> dict:
    """独立生成论文摘要与关键词（创作向导第②步，"新建一条"按钮）。

    与大纲生成一致：优先使用模型配置，未配置模型时返回 400 提示。
    """
    from contextlib import nullcontext
    model_cfg = model_service.resolve_model(request.model_id)
    ctx = deepseek.connection(model_cfg) if model_cfg else nullcontext()
    if model_cfg is not None:
        with ctx:
            try:
                abstract, keywords = deepseek_service.generate_abstract(
                    title=request.title, major=request.major,
                    paper_type=request.paper_type,
                    special_requirements=(request.special_requirements or "").strip())
                return {"abstract": abstract, "keywords": keywords}
            except deepseek.DeepSeekError as exc:
                raise HTTPException(
                    status_code=502, detail=f"AI 模型生成摘要失败：{exc}")
    raise HTTPException(
        status_code=400,
        detail="未配置 AI 模型，请先在「模型设置」中配置并启用模型")


@router.post("/references/search")
async def references_search(request: ReferenceSearchRequest) -> dict:
    """搜索真实参考文献（CrossRef 学术库），供创作向导第③步选择。

    返回文献列表：标题/作者/期刊/年份/类型/DOI/摘要 + GB/T 7714 引文。
    """
    keywords = " ".join(request.keywords or [])
    base_query = (request.query or "").strip() or \
        " ".join(x for x in [request.title, keywords] if x)
    if not base_query.strip():
        raise HTTPException(
            status_code=400, detail="请先填写论文选题或关键词")
    try:
        refs = reference_search.search_references(base_query, request.limit)
    except Exception as exc:  # noqa: BLE001 - 转为 502
        logger.warning("参考文献搜索失败: %s", exc)
        raise HTTPException(status_code=502, detail=f"文献搜索失败：{exc}")
    return {"references": refs, "query": base_query}


@router.get("/status/{task_id}", response_model=TaskInfo)
async def status(task_id: str, request: Request) -> TaskInfo:
    """查询任务状态、进度与错误信息。"""
    info = request.app.state.task_manager.get(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return info


@router.get("/generate/stream/{task_id}")
async def stream_status(task_id: str, request: Request):
    """SSE：实时推送分段生成进度（planning/摘要/逐章/结论/检查…）。"""
    manager = request.app.state.task_manager

    async def event_gen():
        last = None
        for _ in range(2400):  # 最长约 20 分钟
            info = manager.get(task_id)
            if info is None:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                return
            sig = (info.progress, info.status, info.message,
                   info.current_stage, info.current_chapter,
                   info.chapter_count)
            if sig != last:
                payload = {
                    "task_id": task_id,
                    "status": info.status,
                    "progress": info.progress,
                    "message": info.message,
                    "current_stage": info.current_stage,
                    "current_chapter": info.current_chapter,
                    "chapter_count": info.chapter_count,
                }
                yield ("event: progress\n"
                       f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                last = sig
            if info.status in ("completed", "failed"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _require_completed(task_id: str, request: Request) -> Path:
    task_dir = _task_dir(task_id)
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    info = request.app.state.task_manager.get(task_id)
    if info is None or info.status != TaskStatus.completed:
        raise HTTPException(
            status_code=409,
            detail=f"任务尚未完成（当前状态: {info.status if info else 'unknown'}），无法预览",
        )
    return task_dir


@router.get("/content/{task_id}")
async def paper_content(task_id: str, request: Request) -> dict:
    """第一阶段产物：论文内容清单（paper_content/，不含 docx）。"""
    task_dir = _require_completed(task_id, request)
    content_dir = task_dir / "paper_content"
    if content_dir.is_dir():
        generator = ContentGenerator(task_id, {}, content_dir,
                                     request.app.state.task_manager)
        manifest = generator.manifest()
        if manifest.get("abstract") or manifest.get("chapters"):
            return manifest
    # 回退：从已生成 spec 提供内容
    preview = preview_service.parse_preview(
        task_dir, preview_service.load_request(task_dir))
    return {
        "outline": {"chapters": [
            {"title": ch["title"]} for ch in preview["chapters"]
            if ch["level"] == 1]},
        "abstract": next(
            (ch["content"] for ch in preview["chapters"]
             if ch["title"] == "摘要"), ""),
        "keywords": [],
        "chapters": [
            {"title": ch["title"], "text": ch["content"]}
            for ch in preview["chapters"] if ch["level"] == 1],
        "conclusion": "",
        "references": preview["references"],
    }


@router.get("/preview/{task_id}")
async def preview(task_id: str, request: Request) -> dict:
    """论文生成结果预览：解析 论文.docx 为网页可渲染 JSON（不返回 docx）。"""
    task_dir = _require_completed(task_id, request)
    return preview_service.parse_preview(
        task_dir, preview_service.load_request(task_dir))


@router.get("/chapters/{task_id}")
async def chapters(task_id: str, request: Request) -> dict:
    """返回论文目录（章节层级，用于左侧目录导航）。"""
    task_dir = _require_completed(task_id, request)
    preview_data = preview_service.parse_preview(
        task_dir, preview_service.load_request(task_dir))
    return {"chapters": [
        {"id": ch["id"], "level": ch["level"], "title": ch["title"]}
        for ch in preview_data["chapters"]
    ]}


@router.get("/images/{task_id}")
async def images(task_id: str, request: Request) -> dict:
    """返回论文图表元数据（图号/标题/路径），供缩略图展示。"""
    task_dir = _require_completed(task_id, request)
    preview_data = preview_service.parse_preview(
        task_dir, preview_service.load_request(task_dir))
    all_images = [
        img for ch in preview_data["chapters"] for img in ch.get("images", [])
    ]
    return {"images": all_images, "count": len(all_images)}


@router.get("/download/{task_id}")
async def download(task_id: str, request: Request,
                   file: str | None = None):
    """下载任务产物。默认打包 ZIP；指定 ?file=论文.docx 可下载单个文件。"""
    task_dir = _task_dir(task_id)
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    info = request.app.state.task_manager.get(task_id)
    if info is None or info.status != TaskStatus.completed:
        raise HTTPException(
            status_code=409,
            detail=f"任务尚未完成（当前状态: {info.status if info else 'unknown'}）",
        )

    if file is not None:
        target = (task_dir / file).resolve()
        if not str(target).startswith(str(task_dir.resolve())):
            raise HTTPException(status_code=400, detail="非法的文件名")
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"文件不存在: {file}")
        return FileResponse(target, filename=target.name)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(task_dir.rglob("*")):
            if p.is_file() and p.name not in ("task.json", "request.json"):
                zf.write(p, arcname=str(p.relative_to(task_dir)).replace("\\", "/"))
    buffer.seek(0)
    headers = {
        "Content-Disposition":
            f"attachment; filename=\"paper_{task_id}.zip\"; "
            f"filename*=UTF-8''{_urlquote(f'论文生成_{task_id}.zip')}",
    }
    return StreamingResponse(
        buffer, media_type="application/zip", headers=headers)


@router.get("/health")
async def health(request: Request) -> dict:
    engine_ready = False
    try:
        request.app.state.paper_service.engine()
        engine_ready = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Engine not ready: %s", exc)
    return {"status": "ok", "engine_ready": engine_ready}


def _urlquote(name: str) -> str:
    from urllib.parse import quote
    return quote(name)
