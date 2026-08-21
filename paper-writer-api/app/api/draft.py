"""论文草稿（逐段生成编辑器）API。"""

from __future__ import annotations

import re
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from pydantic import BaseModel, Field

from app.config import settings
from app.draft.service import DraftService
from app.draft import block_service
from app.draft.chart_runtime import (
    adapt_insight_chart,
    create_lab_chart,
    create_lab_chart_from_dataset,
    dataset_by_id,
    external_dataset_version,
    dataset_profile,
    insert_chart_into_section,
    locate_block,
    locate_chart,
    recompute_chart_block,
    update_chart_configuration,
    upsert_table_dataset,
    walk_sections,
)
from app.draft.insight_blocks import (
    InsightCreateRequest,
    InsightPatchRequest,
    InsightRegenerateRequest,
    create_insight_block,
    patch_insight_block,
    regenerate_insight_block,
)
from app.draft.chart_blocks import (
    AIChartRegenerateRequest,
    ChartCreateRequest,
    ChartPatchRequest,
    ChartRegenerateRequest,
    ChartSpecUpdateRequest,
    create_chart_block,
    patch_chart_block,
    regenerate_chart_block,
        update_chart_spec_block,
    ai_chart_candidate,
)
from app.draft.chart_versions import bootstrap_chart_version, export_version_summary, restore_chart_version
from app.services.chart_version_service import ChartVersionService

from app.services import history_service
from app.services.dataset_service import DatasetService
from app.services.full_paper_generation_service import FullPaperGenerationService

router = APIRouter(prefix="/api/draft", tags=["draft"])
_TASK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class SectionUpdateRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    gist: str | None = Field(None, max_length=500)


class ParagraphAddRequest(BaseModel):
    section_id: str
    text: str = Field("", max_length=20_000)


class ParagraphUpdateRequest(BaseModel):
    text: str = Field(..., max_length=20_000)


class MoveRequest(BaseModel):
    direction: str = Field(..., pattern="^(up|down)$")


class GenerateRequest(BaseModel):
    model_id: str | None = Field(None)


def _service(task_id: str, request: Request) -> DraftService:
    if not _TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=400, detail="任务 ID 格式无效")
    task_dir = settings.output_dir / task_id
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return DraftService(task_id, task_dir, request.app.state.task_manager)



class TableBlockAddRequest(BaseModel):
    section_id: str
    title: str = Field("数据表", max_length=200)
    headers: list[str] = Field(default_factory=lambda: ["指标", "数值"])
    rows: list[list[str]] = Field(default_factory=lambda: [["", ""]])

class BlockUpdateRequest(BaseModel):
    text: str | None = Field(None, max_length=20_000)
    title: str | None = Field(None, max_length=200)
    headers: list[str] | None = None
    rows: list[list[str]] | None = None

class OutlineRegenerateRequest(BaseModel):
    model_id: str | None = Field(None)


class OutlineAddRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    gist: str = Field("", max_length=500)
    parent_id: str | None = Field(None)


class LabChartCreateRequest(BaseModel):
    table_id: str | None = Field(default=None, max_length=160)
    dataset_id: str | None = Field(default=None, max_length=160)
    dataset_version: int | None = Field(default=None, ge=1)
    source_type: str = Field(default="table_block", pattern="^(table_block|research_dataset)$")
    title_hint: str = Field("", max_length=100)
    chart_kind: str = Field("bar", max_length=32)


class LabChartPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    caption: str | None = Field(default=None, max_length=220)
    kind: str | None = Field(default=None, max_length=32)
    binding: dict | None = None
    appearance: dict | None = None


class LabChartRecomputeRequest(BaseModel):
    chart_kind: str | None = Field(default=None, max_length=32)


class LabChartInsertRequest(BaseModel):
    section_id: str = Field(..., min_length=1, max_length=160)





@router.get("/{task_id}")
def get_draft(task_id: str, request: Request) -> dict:
    draft = _service(task_id, request).load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在，请重新生成")
    return draft


@router.get("/{task_id}/outline")
def get_outline_review(task_id: str, request: Request) -> dict:
    draft = _service(task_id, request).load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在，请重新生成")
    return {"title": draft.get("title", ""), "sections": draft.get("sections", []), "outline_meta": draft.get("outline_meta", {})}


@router.post("/{task_id}/outline/confirm")
def confirm_outline(task_id: str, request: Request) -> dict:
    try:
        return {"outline_meta": _service(task_id, request).confirm_outline()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/outline/regenerate")
def regenerate_outline(task_id: str, body: OutlineRegenerateRequest, request: Request) -> dict:
    try:
        draft = _service(task_id, request).regenerate_outline(body.model_id)
        return {"sections": draft.get("sections", []), "outline_meta": draft.get("outline_meta", {})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/outline/section")
def add_outline_section(task_id: str, body: OutlineAddRequest, request: Request) -> dict:
    try:
        return _service(task_id, request).add_outline_section(body.title, body.gist, body.parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{task_id}/outline/section/{section_id}")
def delete_outline_section(task_id: str, section_id: str, request: Request) -> dict:
    try:
        _service(task_id, request).delete_outline_section(section_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}/status")
def draft_status(task_id: str, request: Request) -> dict:
    service = _service(task_id, request)
    draft = service.load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return FullPaperGenerationService(service).status()


@router.post("/{task_id}/section/{section_id}/generate")
def generate_section(task_id: str, section_id: str,
                     body: GenerateRequest, request: Request) -> dict:
    try:
        para = _service(task_id, request).generate_section(
            section_id, body.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return para


@router.post("/{task_id}/section/{section_id}")
def update_section(task_id: str, section_id: str,
                   body: SectionUpdateRequest, request: Request) -> dict:
    try:
        _service(task_id, request).update_section(
            section_id, title=body.title, gist=body.gist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/{task_id}/paragraph")
def add_paragraph(task_id: str, body: ParagraphAddRequest,
                  request: Request) -> dict:
    try:
        return _service(task_id, request).add_paragraph(body.section_id, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{task_id}/paragraph/{pid}")
def update_paragraph(task_id: str, pid: str,
                     body: ParagraphUpdateRequest, request: Request) -> dict:
    try:
        _service(task_id, request).update_paragraph(pid, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.delete("/{task_id}/paragraph/{pid}")
def delete_paragraph(task_id: str, pid: str, request: Request) -> dict:
    try:
        _service(task_id, request).delete_paragraph(pid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/{task_id}/paragraph/{pid}/move")
def move_paragraph(task_id: str, pid: str, body: MoveRequest,
                   request: Request) -> dict:
    try:
        _service(task_id, request).move_paragraph(pid, body.direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/{task_id}/table")
def add_table_block(task_id: str, body: TableBlockAddRequest, request: Request) -> dict:
    try:
        return block_service.add_table(_service(task_id, request), body.section_id, body.title, body.headers, body.rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.put("/{task_id}/block/{block_id}")
def update_content_block(task_id: str, block_id: str, body: BlockUpdateRequest, request: Request) -> dict:
    try:
        return block_service.update_block(_service(task_id, request), block_id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def _start_full_paper_thread(task_id: str, service: DraftService, model_id: str | None, *, resume: bool = False, section_id: str | None = None) -> None:
    pipeline = FullPaperGenerationService(service)

    def run() -> None:
        try:
            if section_id:
                pipeline.regenerate_section(section_id, model_id)
            else:
                pipeline.run(model_id)
            state = pipeline.status().get("pipeline") or {}
            if state.get("status") == "paused":
                history_service.update_record_progress(task_id, current_stage="paused", progress=int(pipeline.status().get("progress") or 0))
                return
            history_service.update_record(task_id, status="completed", error=None, completed=False)
            history_service.update_record_progress(task_id, current_stage="completed", progress=100)
        except Exception as exc:  # noqa: BLE001
            pipeline._save_state(status="failed", stage="failed", message="全文生成失败", error=str(exc))
            history_service.update_record(task_id, status="failed", error="一键全文生成失败")

    threading.Thread(target=run, daemon=True).start()


@router.post("/{task_id}/oneclick")
def oneclick(task_id: str, body: GenerateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    pipeline = FullPaperGenerationService(service)
    try:
        state = pipeline.start(body.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_full_paper_thread(task_id, service, body.model_id)
    return {"ok": True, "message": "已启动全文生成流水线", "pipeline": state}


@router.post("/{task_id}/oneclick/pause")
def pause_oneclick(task_id: str, request: Request) -> dict:
    try:
        state = FullPaperGenerationService(_service(task_id, request)).pause()
        return {"ok": True, "pipeline": state}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/oneclick/resume")
def resume_oneclick(task_id: str, body: GenerateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    pipeline = FullPaperGenerationService(service)
    try:
        state = pipeline.start(body.model_id, resume=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_full_paper_thread(task_id, service, body.model_id, resume=True)
    return {"ok": True, "message": "已继续全文生成流水线", "pipeline": state}


@router.post("/{task_id}/section/{section_id}/full-regenerate")
def regenerate_full_section(task_id: str, section_id: str, body: GenerateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    pipeline = FullPaperGenerationService(service)
    try:
        state = pipeline.start(body.model_id) if not service.load().get("generating") else pipeline.status().get("pipeline") or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _start_full_paper_thread(task_id, service, body.model_id, section_id=section_id)
    return {"ok": True, "message": "已启动当前章节重新生成", "pipeline": state}


@router.post("/{task_id}/acknowledgement")
def generate_ack(task_id: str, body: GenerateRequest, request: Request) -> dict:
    return {"text": _service(task_id, request).generate_acknowledgement(body.model_id)}


@router.post("/{task_id}/abstract/en")
def generate_en(task_id: str, body: GenerateRequest, request: Request) -> dict:
    return {"text": _service(task_id, request).generate_en_abstract(body.model_id)}


@router.post("/{task_id}/export")
def export(task_id: str, request: Request,
           template_id: str = "") -> dict:
    try:
        files = _service(task_id, request).export(template_id=template_id or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出失败：{exc}")
    return {"ok": True, "files": files}


def _research_dataset_loader(dataset_id: str, version: int | None) -> dict:
    return DatasetService(settings).get_version(dataset_id, version, include_rows=True)


def _lab_chart_summary(block: dict) -> dict:
    spec = block.get("chart_spec") or {}
    binding = spec.get("binding") or {}
    return {
        "id": block.get("id"), "title": block.get("title"), "caption": block.get("caption"),
        "status": block.get("status"), "version": block.get("version"),
        "in_paper": bool(block.get("in_paper", True)), "figure_number": block.get("figure_number"),
        "kind": spec.get("kind") or (block.get("chart") or {}).get("kind"),
        "dataset_id": binding.get("dataset_id"), "source_table_id": binding.get("source_table_id"),
        "asset": block.get("asset"), "stale_reason": block.get("stale_reason"),
    }


@router.get("/{task_id}/lab/state")
def get_lab_state(task_id: str, request: Request) -> dict:
    service = _service(task_id, request)
    with service.lock:
        draft = service.load()
        # Existing first-stage drafts may predate `datasets`; hydrate only from
        # their authoritative table blocks rather than inventing a second source.
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                if block.get("type") == "table":
                    upsert_table_dataset(draft, block)
        service.save(draft)
    charts = []
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("type") == "chart":
                charts.append(_lab_chart_summary(block))
    for block in draft.get("chart_library") or []:
        if block.get("type") == "chart":
            charts.append(_lab_chart_summary(block))
    sections = [{"id": item.get("id"), "number": item.get("number", ""), "title": item.get("title", "")} for item in walk_sections(draft.get("sections") or [])]
    research_datasets = DatasetService(settings).list_datasets(task_id)
    return {"datasets": draft.get("datasets") or [], "research_datasets": research_datasets, "charts": charts, "sections": sections, "templates": [{"id": key, **value} for key, value in {"academic": {"label": "学术论文"}, "cn_thesis": {"label": "中文毕业论文"}, "clean_report": {"label": "简洁报告"}}.items()]}


@router.get("/{task_id}/lab/datasets/{dataset_id}")
def get_lab_dataset(task_id: str, dataset_id: str, request: Request, limit: int = 50, offset: int = 0, version: int | None = None) -> dict:
    draft = _service(task_id, request).load()
    try:
        if dataset_id.startswith("ds_"):
            external = external_dataset_version(_research_dataset_loader(dataset_id, version))
            result = dataset_profile(external, limit=limit, offset=offset)
            result["source_type"] = "research_dataset"
            return result
        return dataset_profile(dataset_by_id(draft, dataset_id), limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/lab/charts/{chart_id}")
def get_lab_chart(task_id: str, chart_id: str, request: Request) -> dict:
    draft = _service(task_id, request).load()
    try:
        _, block, _ = locate_chart(draft, chart_id)
        return block
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/lab/charts")
def create_lab_chart_endpoint(task_id: str, body: LabChartCreateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            chart_id = "chart_" + __import__("uuid").uuid4().hex[:12]
            if body.source_type == "research_dataset":
                if not body.dataset_id:
                    raise ValueError("请选择研究数据集")
                dataset = external_dataset_version(_research_dataset_loader(body.dataset_id, body.dataset_version))
                block = create_lab_chart_from_dataset(draft, service.task_dir, chart_id, dataset, body.title_hint, body.chart_kind)
            else:
                if not body.table_id:
                    raise ValueError("请选择论文表格")
                block = create_lab_chart(draft, service.task_dir, chart_id, body.table_id, body.title_hint, body.chart_kind)
            service.save(draft)
            return block
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{task_id}/lab/charts/{chart_id}")
def patch_lab_chart(task_id: str, chart_id: str, body: LabChartPatchRequest, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            block = update_chart_configuration(draft, service.task_dir, chart_id, body.model_dump(exclude_none=True), _research_dataset_loader)
            service.save(draft)
            return block
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/lab/charts/{chart_id}/recompute")
def recompute_lab_chart(task_id: str, chart_id: str, body: LabChartRecomputeRequest, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            _, block, _ = locate_chart(draft, chart_id)
            recompute_chart_block(draft, service.task_dir, block, body.chart_kind, _research_dataset_loader)
            service.save(draft)
            return block
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/lab/charts/{chart_id}/insert")
def insert_lab_chart(task_id: str, chart_id: str, body: LabChartInsertRequest, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            block = insert_chart_into_section(draft, chart_id, body.section_id)
            service.save(draft)
            return block
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/insight/{insight_id}/adapt-chart")
def adapt_insight_chart_endpoint(task_id: str, insight_id: str, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            block = adapt_insight_chart(draft, service.task_dir, insight_id)
            service.save(draft)
            return block
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/section/{section_id}/chart")
def add_chart(task_id: str, section_id: str, body: ChartCreateRequest, request: Request):
    try:
        return create_chart_block(_service(task_id, request), section_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{task_id}/chart/{block_id}/regenerate")
def regenerate_chart(task_id: str, block_id: str, body: ChartRegenerateRequest, request: Request):
    try:
        return regenerate_chart_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{task_id}/chart/{block_id}/ai-regenerate")
def ai_regenerate_chart(task_id: str, block_id: str, body: AIChartRegenerateRequest, request: Request):
    try:
        return ai_chart_candidate(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{task_id}/chart/{block_id}/versions")
def list_chart_versions(task_id: str, block_id: str, request: Request) -> dict:
    service = _service(task_id, request)
    try:
        with service.lock:
            draft = service.load()
            before = __import__("copy").deepcopy(draft)
            _, block = locate_chart(draft, block_id)
            bootstrap_chart_version(service, draft, block, before)
            versions = ChartVersionService(service._storage_settings()).list(task_id, block_id)
            current = str(block.get("current_chart_version_id") or "")
            items = [dict(export_version_summary(item), is_current=item.get("id") == current) for item in reversed(versions)]
            return {"figure_id": block_id, "current_chart_version_id": current, "versions": items}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{task_id}/chart/{block_id}/restore/{version_id}")
def restore_chart_version_endpoint(task_id: str, block_id: str, version_id: str, request: Request) -> dict:
    try:
        return restore_chart_version(_service(task_id, request), block_id, version_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{task_id}/chart/{block_id}")
def patch_chart(task_id: str, block_id: str, body: ChartPatchRequest, request: Request):
    try:
        return patch_chart_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{task_id}/chart/{block_id}/spec")
def update_chart_spec(task_id: str, block_id: str, body: ChartSpecUpdateRequest, request: Request):
    """保存正文内编辑器的 ChartSpec，并从同一 spec 重建现有 PNG/SVG 资产。"""
    try:
        return update_chart_spec_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{task_id}/chart/{block_id}/asset")
def get_chart_asset(task_id: str, block_id: str, request: Request, format: str = "svg"):
    """Return a chart's persisted renderer asset for editor preview or download."""
    if format not in {"svg", "png"}:
        raise HTTPException(status_code=422, detail="图表资产格式仅支持 svg 或 png")
    service = _service(task_id, request)
    draft = service.load()
    try:
        _, block, _ = locate_chart(draft, block_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if block.get("type") != "chart":
        raise HTTPException(status_code=422, detail="目标内容块不是图表")
    asset = block.get("asset") or {}
    relative = asset.get("svg_path" if format == "svg" else "png_path")
    if not relative:
        raise HTTPException(status_code=404, detail="图表资产尚未生成")
    target = (service.task_dir / str(relative)).resolve()
    charts_dir = (service.task_dir / "charts").resolve()
    try:
        target.relative_to(charts_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="图表资产路径无效") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="图表资产文件不存在")
    media_type = "image/svg+xml" if format == "svg" else "image/png"
    return FileResponse(target, media_type=media_type, filename=target.name)


@router.post("/{task_id}/section/{section_id}/insight")
def add_insight(task_id: str, section_id: str, body: InsightCreateRequest, request: Request):
    try:
        return create_insight_block(_service(task_id, request), section_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{task_id}/insight/{block_id}/regenerate")
def regenerate_insight(task_id: str, block_id: str, body: InsightRegenerateRequest, request: Request):
    try:
        return regenerate_insight_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/{task_id}/insight/{block_id}")
def patch_insight(task_id: str, block_id: str, body: InsightPatchRequest, request: Request):
    try:
        return patch_insight_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
