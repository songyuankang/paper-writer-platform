from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.services.discussion_writer_service import DiscussionWriterService

router = APIRouter(tags=["research-discussion-writer"])

def service() -> DiscussionWriterService: return DiscussionWriterService(settings)
def fail(exc: ValueError, status: int = 422) -> HTTPException: return HTTPException(status_code=status, detail=str(exc))

class FactPackageInput(BaseModel):
    task_id: str; framework_id: str; hypothesis_ids: list[str] = Field(default_factory=list); finding_ids: list[str] = Field(default_factory=list); literature_evidence_ids: list[str] = Field(default_factory=list); research_context: str = ""; practical_context: str = ""
class GenerateInput(FactPackageInput):
    section_type: str; style: dict[str, Any] = Field(default_factory=dict); model_id: str | None = None
class InsertInput(BaseModel): section_id: str

@router.post("/api/research/discussion/fact-package")
def discussion_fact_package(payload: FactPackageInput):
    try: return service().build_fact_package(**payload.model_dump())
    except ValueError as exc: raise fail(exc) from exc
@router.post("/api/research/discussion/drafts")
def generate_discussion_draft(payload: GenerateInput):
    try: return service().generate(**payload.model_dump())
    except ValueError as exc: raise fail(exc) from exc
@router.get("/api/research/discussion/drafts")
def list_discussion_drafts(task_id: str = Query(...), framework_id: str | None = None):
    try: return {"drafts":service().list(task_id,framework_id)}
    except ValueError as exc: raise fail(exc) from exc
@router.get("/api/research/discussion/drafts/{draft_id}")
def get_discussion_draft(draft_id: str):
    try: return service().get(draft_id)
    except ValueError as exc: raise fail(exc,404) from exc
@router.get("/api/research/discussion/drafts/{draft_id}/evidence")
def discussion_draft_evidence(draft_id: str):
    try:
        draft=service().get(draft_id)
        return {"draft_id":draft_id,"source_snapshot":draft.get("source_snapshot"),"fact_package":draft.get("fact_package"),"sections":draft.get("sections")}
    except ValueError as exc: raise fail(exc,404) from exc
@router.post("/api/research/discussion/drafts/{draft_id}/insert")
def insert_discussion_draft(draft_id: str,payload: InsertInput):
    try: return {"blocks":service().insert(draft_id=draft_id,section_id=payload.section_id)}
    except ValueError as exc: raise fail(exc) from exc
