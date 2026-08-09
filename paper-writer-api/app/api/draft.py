"""论文草稿（逐段生成编辑器）API。"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.draft.service import DraftService
from app.services import history_service

router = APIRouter(prefix="/api/draft", tags=["draft"])


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
    task_dir = settings.output_dir / task_id
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return DraftService(task_id, task_dir, request.app.state.task_manager)


@router.get("/{task_id}")
def get_draft(task_id: str, request: Request) -> dict:
    draft = _service(task_id, request).load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在，请重新生成")
    return draft


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


@router.post("/{task_id}/oneclick")
def oneclick(task_id: str, body: GenerateRequest, request: Request) -> dict:
    service = _service(task_id, request)
    draft = service.load()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if draft.get("generating"):
        raise HTTPException(status_code=400, detail="正在生成中，请稍候")

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
