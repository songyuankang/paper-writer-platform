"""API endpoints: submit generation, query status, download results."""

import asyncio
import json
import re
import io
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.models.generate import (
    GenerateRequest,
    GenerationMode,
    GenerationStrategy,
    MaterialFile,
    OutlineRequest,
    OutlineResponse,
    AbstractRequest,
    ManualReferenceRequest,
    ReferenceSearchRequest,
    PaperType,
    ReferenceStyle,
)

class TopicSuggestionsRequest(BaseModel):
    discipline: str = Field("", max_length=100)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: str = Field("毕业论文", min_length=1, max_length=50)
    model_id: str | None = None
    prompt: str | None = Field(None, max_length=1000)
from app.models.task import GenerateResponse, TaskInfo, TaskStatus
from app.services import outline_service
from app.services import preview_service
from app.services import history_service
from app.services import deepseek, deepseek_service
from app.services import model_service
from app.services import material_service
from app.services import reference_search
from app.generation.service import ContentGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])

_TASK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _validate_task_id(task_id: str) -> str:
    """仅接受本服务生成的 UUID4 hex 任务标识，禁止将路径片段带入输出目录。"""
    if not _TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=400, detail="任务 ID 格式无效")
    return task_id


def _task_dir(task_id: str) -> Path:
    return settings.output_dir / _validate_task_id(task_id)


_MANUAL_REFERENCE_TYPE_LABELS = {
    "journal": ("期刊论文", "J"),
    "thesis": ("学位论文", "D"),
    "conference": ("会议论文", "C"),
    "book": ("图书", "M"),
    "report": ("报告", "R"),
    "web": ("网络资源", "EB/OL"),
    "standard": ("标准", "S"),
}


def _format_manual_reference(reference: ManualReferenceRequest) -> str:
    """将手动录入字段格式化为与现有向导兼容的 GB/T 7714 引文字符串。"""
    _, marker = _MANUAL_REFERENCE_TYPE_LABELS[reference.reference_type]
    publication = f"{reference.source}, {reference.year}"
    if reference.reference_type == "journal":
        volume_issue = reference.volume
        if reference.issue:
            volume_issue = f"{volume_issue}({reference.issue})" if volume_issue else f"({reference.issue})"
        if volume_issue:
            publication += f", {volume_issue}"
        if reference.pages:
            publication += f": {reference.pages}"
    elif reference.pages:
        publication += f": {reference.pages}"

    citation = f"{reference.authors}. {reference.title}[{marker}]. {publication}."
    if reference.doi:
        citation += f" DOI:{reference.doi}."
    if reference.url:
        citation += f" {reference.url}"
    return citation


def _manual_reference_item(reference: ManualReferenceRequest) -> dict:
    """映射为与外部检索结果一致的候选文献形状，供前端统一勾选和提交。"""
    type_label, _ = _MANUAL_REFERENCE_TYPE_LABELS[reference.reference_type]
    return {
        "title": reference.title,
        "authors": reference.authors,
        "source": reference.source,
        "year": reference.year,
        "type": type_label,
        "doi": reference.doi,
        "abstract": "",
        "citation": _format_manual_reference(reference),
        "source_name": "manual",
        "url": reference.url,
        "manual": reference.model_dump(),
    }


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    http_request: Request,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    major: Annotated[str, Form(min_length=1, max_length=100)],
    paper_type: Annotated[PaperType, Form()] = "课程论文",
    word_count: Annotated[int, Form(ge=500, le=100_000)] = 3000,
    reference_style: Annotated[ReferenceStyle, Form()] = "gb7714",
    generation_mode: Annotated[GenerationMode, Form()] = "auto",
    outline: Annotated[str | None, Form()] = None,
    special_requirements: Annotated[str | None, Form()] = None,
    generation_strategy: Annotated[GenerationStrategy, Form()] = "section",
    model_id: Annotated[str | None, Form()] = None,
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
        word_count=word_count,
        reference_style=reference_style,
        generation_mode=generation_mode, outline=outline,
        special_requirements=special_requirements,
        generation_strategy=generation_strategy,
        model_id=model_id,
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
    logger.info("Task %s submitted: title=%s major=%s type=%s files=%d",
                task_id, request.title, request.major, request.paper_type,
                len(materials))
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


@router.post("/topics/suggest")
async def topic_suggestions(request: TopicSuggestionsRequest) -> dict:
    """让 AI 一次生成 8 个可选论文选题。"""
    model_cfg = model_service.resolve_model(request.model_id)
    if model_cfg is None:
        raise HTTPException(status_code=400, detail="未配置 AI 模型")
    user_hint = (request.prompt or "").strip()
    prompt = (
        f"请严格基于以下学科门类和专业类，为该专业的{request.paper_type}生成8个互不重复、具体可研究的论文选题。"
        f"学科门类：{request.discipline or '未指定'}；专业类：{request.major}。"
        f"用户补充的选题方向是：{user_hint or '无，请结合以上学科和专业自主拟定'}。"
        "要求结合专业场景，避免空泛和重复，不要解释，只返回 JSON 数组，格式为"
        '["选题1","选题2",...,"选题8"]。'
    )
    from contextlib import nullcontext
    with (deepseek.connection(model_cfg) if model_cfg else nullcontext()):
        try:
            text = deepseek.chat([{"role": "user", "content": prompt}])
            match = re.search(r"\[.*\]", text, re.S)
            topics = json.loads(match.group(0)) if match else []
            topics = [str(x).strip() for x in topics if str(x).strip()][:8]
            if len(topics) < 8:
                raise ValueError("AI 返回的选题数量不足 8 个")
            return {"topics": topics}
        except (deepseek.DeepSeekError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"AI 选题生成失败：{exc}")


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


@router.post("/references/manual")
async def manual_reference(request: ManualReferenceRequest) -> dict:
    """格式化用户手动录入的文献，作为向导第③步可勾选的本地候选条目。"""
    return {"reference": _manual_reference_item(request)}


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
    _validate_task_id(task_id)
    info = request.app.state.task_manager.get(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return info


@router.get("/generate/stream/{task_id}")
async def stream_status(task_id: str, request: Request):
    """SSE：实时推送分段生成进度（planning/摘要/逐章/结论/检查…）。"""
    _validate_task_id(task_id)
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
    if (task_dir / "draft.json").exists() and not (task_dir / "论文.docx").exists():
        return preview_service.parse_draft_preview(
            task_dir, preview_service.load_request(task_dir))
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


@router.get("/download/{task_id}")
async def download(task_id: str, request: Request,
                   file: str | None = None):
    """下载任务产物。默认打包 ZIP；指定 ?file=论文.docx 可下载单个文件。"""
    task_dir = _task_dir(task_id)
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    info = request.app.state.task_manager.get(task_id)
    completed = info is not None and info.status == TaskStatus.completed
    if not completed:
        # 内存任务管理器（重启后清空）没有该任务时，回退数据库记录判断
        record = history_service.get_record(task_id)
        completed = bool(record and record["status"] == "completed")
    if not completed:
        raise HTTPException(
            status_code=409,
            detail=f"任务尚未完成（当前状态: {info.status if info else 'unknown'}）",
        )

    if file is not None:
        task_root = task_dir.resolve()
        target = (task_root / file).resolve()
        try:
            target.relative_to(task_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="非法的文件名") from exc
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


@router.post("/export/{task_id}")
async def export_paper(task_id: str, template_id: str = "") -> dict:
    """按选定排版模板导出论文 docx（未选模板时使用默认基础模板）。

    生成阶段不再自动产出最终 DOCX（format_paper(build_docx=False)），
    由本接口在用户点击「导出论文」并按所选模板渲染。
    """
    task_dir = _task_dir(task_id)
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    spec_path = task_dir / "paper_spec.json"
    if not spec_path.exists():
        raise HTTPException(status_code=400, detail="论文内容不存在，请先生成论文")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        try:
            paper_info = preview_service.load_request(task_dir)
        except Exception:  # noqa: BLE001 - 无 request.json 时用空信息兜底
            paper_info = {}
        from app.formatter.template import render_service
        # template_id 为空/未知 → TemplateService.resolve 自动回退默认（基础）模板
        render_service.render_with_template(
            template_id or None, task_dir, spec, paper_info=paper_info,
            out_name="论文.docx")
    except Exception as exc:  # noqa: BLE001 - 统一映射为 HTTP 错误
        logger.exception("Task %s export failed", task_id)
        raise HTTPException(status_code=500, detail=f"导出失败：{exc}")
    return {"ok": True, "files": ["论文.docx"]}


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
