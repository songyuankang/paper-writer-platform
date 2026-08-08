"""论文修改接口：章节/段落修改、全文分析、版本管理与恢复。"""

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.revise import (
    AnalyzeRequest,
    RestoreRequest,
    ReviseChapterRequest,
    ReviseParagraphRequest,
)
from app.services import revise_service

router = APIRouter(prefix="/api/revise", tags=["revise"])


def _task_dir(task_id: str):
    task_dir = settings.output_dir / task_id
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return task_dir


@router.post("/chapter")
def revise_chapter(req: ReviseChapterRequest) -> dict:
    task_dir = _task_dir(req.task_id)
    revise_service._ensure_initial_version(req.task_id, task_dir)
    try:
        return revise_service.apply_chapter_revision(
            req.task_id, task_dir, req.chapter_id,
            req.change_type, req.instruction, model_id=req.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/paragraph")
def revise_paragraph(req: ReviseParagraphRequest) -> dict:
    task_dir = _task_dir(req.task_id)
    revise_service._ensure_initial_version(req.task_id, task_dir)
    try:
        return revise_service.apply_paragraph_revision(
            req.task_id, task_dir, req.paragraph_id,
            req.change_type, req.instruction, model_id=req.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    task_dir = _task_dir(req.task_id)
    revise_service._ensure_initial_version(req.task_id, task_dir)
    return revise_service.analyze_paper(req.task_id, task_dir)


@router.get("/versions/{task_id}")
def versions(task_id: str) -> dict:
    task_dir = _task_dir(task_id)
    revise_service._ensure_initial_version(task_id, task_dir)
    return {"versions": revise_service.list_versions(task_id)}


@router.post("/restore")
def restore(req: RestoreRequest) -> dict:
    task_dir = _task_dir(req.task_id)
    revise_service._ensure_initial_version(req.task_id, task_dir)
    try:
        return revise_service.restore_version(
            req.task_id, task_dir, req.version_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
