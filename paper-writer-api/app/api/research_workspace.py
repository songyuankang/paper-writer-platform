from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services.research_workspace_service import ResearchWorkspaceService

router = APIRouter(prefix="/api/research/workspace", tags=["research-workspace"])


def _service() -> ResearchWorkspaceService:
    return ResearchWorkspaceService(settings)


@router.get("/templates")
def workspace_templates() -> dict:
    return {"templates": _service().templates()}


@router.get("/{task_id}")
def research_workspace(task_id: str) -> dict:
    try:
        return _service().get(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
