from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services.research_object_service import ResearchObjectService

router = APIRouter(tags=["research-objects"])


def _service() -> ResearchObjectService:
    return ResearchObjectService(settings)


@router.get("/api/research/objects")
def list_research_objects(task_id: str | None = None):
    """List lightweight semantic objects, optionally within one paper task."""
    try:
        return {"objects": _service().list(task_id=task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/research/objects/{object_id}")
def get_research_object(object_id: str):
    try:
        return _service().get(object_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/tasks/{task_id}/research-objects")
def task_research_objects(task_id: str):
    try:
        return {"objects": _service().list(task_id=task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/renumber")
def renumber_task_references(task_id: str):
    try:
        return _service().renumber_document_references(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
