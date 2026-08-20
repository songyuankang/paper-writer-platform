from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.research_workspace_insert_service import ResearchWorkspaceInsertService

router = APIRouter(prefix="/api/research/workspace", tags=["research-workspace"])


class InsertPreviewRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., pattern="^(analysis_result|table|figure|finding|discussion_draft|hypothesis_evaluation)$")
    source_id: str = Field(..., min_length=1, max_length=160)
    section_id: str = Field(..., min_length=1, max_length=160)
    analysis_id: str = Field(default="", max_length=160)
    artifact: str = Field(default="table", pattern="^(table|chart|actual_predicted|residual|coefficient)$")


class ConfirmInsertRequest(InsertPreviewRequest):
    confirmed: bool = False


def _service() -> ResearchWorkspaceInsertService:
    return ResearchWorkspaceInsertService(settings)


@router.post("/insert-preview")
def insert_preview(body: InsertPreviewRequest) -> dict:
    try:
        return _service().preview(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/insert")
def insert_into_paper(body: ConfirmInsertRequest) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=422, detail="请确认后再加入论文")
    try:
        payload = body.model_dump(exclude={"confirmed"})
        return _service().insert(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
