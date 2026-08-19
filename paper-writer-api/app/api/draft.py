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
from app.draft.chart_runtime import locate_block
from app.draft.insight_blocks import (
    InsightCreateRequest,
    InsightPatchRequest,
    InsightRegenerateRequest,
    create_insight_block,
    patch_insight_block,
    regenerate_insight_block,
)
from app.draft.chart_blocks import (
    ChartCreateRequest,
    ChartPatchRequest,
    ChartRegenerateRequest,
    create_chart_block,
    patch_chart_block,
    regenerate_chart_block,
)
from app.services import history_service

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
    draft = _service(task_id, request).load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return {
        "generating": draft.get("generating", False),
        "progress": draft.get("progress", 0),
        "done": draft.get("done", 0),
        "total": draft.get("total", 0),
    }


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

@router.post("/{task_id}/oneclick")
def oneclick(task_id: str, body: GenerateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    draft = service.load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.get("generating"):
        raise HTTPException(status_code=400, detail="正在生成中，请稍候")
    try:
        service.ensure_outline_confirmed()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def run() -> None:
        try:
            service.oneclick(body.model_id)
            # 草稿模式的一键全文不经过 paper_service 的常规完成分支，
            # 必须在这里同步历史记录状态。
            history_service.update_record(
                task_id, status="completed", error=None, completed=False)
            history_service.update_record_progress(
                task_id, current_stage="completed", progress=100)
        except Exception:  # noqa: BLE001
            with service.lock:
                d = service.load()
                d["generating"] = False
                service.save(d)
            history_service.update_record(
                task_id, status="failed", error="一键全文生成失败")

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "message": "开始一键全文生成"}


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


@router.patch("/{task_id}/chart/{block_id}")
def patch_chart(task_id: str, block_id: str, body: ChartPatchRequest, request: Request):
    try:
        return patch_chart_block(_service(task_id, request), block_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{task_id}/chart/{block_id}/asset")
def get_chart_asset(task_id: str, block_id: str, request: Request, format: str = "svg"):
    """Return a chart's persisted renderer asset for editor preview or download."""
    if format not in {"svg", "png"}:
        raise HTTPException(status_code=422, detail="图表资产格式仅支持 svg 或 png")
    service = _service(task_id, request)
    draft = service.load()
    try:
        _, block = locate_block(draft, block_id)
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
