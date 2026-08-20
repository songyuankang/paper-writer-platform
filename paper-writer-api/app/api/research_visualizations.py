from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.research_visualization_service import ResearchVisualizationService

router = APIRouter(prefix="/api/research/visualizations", tags=["research-visualizations"])


class PlanRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    topic: str = Field(..., min_length=1, max_length=500)
    chapter: str = Field(default="", max_length=240)
    research_question: str = Field(default="", max_length=1000)
    model_id: str | None = Field(default=None, max_length=160)


class SearchRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    limit: int = Field(default=8, ge=1, le=12)


class SaveSourcesRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=30)


class ExtractRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    literature_ids: list[str] = Field(default_factory=list, max_length=30)


class ManualEvidenceRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    subject: str = Field(..., min_length=1, max_length=180)
    metric: str = Field(..., min_length=1, max_length=120)
    value: float
    unit: str = Field(..., min_length=1, max_length=20)
    source_title: str = Field(..., min_length=1, max_length=1000)
    source_location: str = Field(..., min_length=1, max_length=500)
    source_quote: str = Field(..., min_length=1, max_length=1200)
    source_type: str = Field(default="user_provided", max_length=80)
    source_id: str = Field(default="", max_length=160)
    year: int | None = Field(default=None, ge=1000, le=3000)
    device_model: str = Field(default="", max_length=240)
    test_condition: str = Field(default="", max_length=500)


class VerifyRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class RecommendRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=128)
    section: str = Field(default="", max_length=240)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    dataset_id: str = Field(default="", max_length=160)
    dataset_version: int | None = Field(default=None, ge=1)


class InsertRequest(BaseModel):
    section_id: str = Field(..., min_length=1, max_length=160)
    confirmed: bool = False


def _service() -> ResearchVisualizationService:
    return ResearchVisualizationService(settings)


def _call(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plan")
def create_plan(body: PlanRequest) -> dict:
    return _call(lambda: {"plan": _service().create_plan(**body.model_dump())})


@router.get("/{task_id}/plan")
def get_plan(task_id: str) -> dict:
    return _call(lambda: {"plan": _service().plan(task_id)})


@router.post("/search")
def search_sources(body: SearchRequest) -> dict:
    return _call(lambda: _service().search(**body.model_dump()))


@router.post("/sources")
def save_sources(body: SaveSourcesRequest) -> dict:
    return _call(lambda: {"literature": _service().save_sources(**body.model_dump())})


@router.get("/{task_id}/evidence")
def list_evidence(task_id: str) -> dict:
    return _call(lambda: {"evidence": _service().evidence(task_id)})


@router.post("/extract")
def extract_evidence(body: ExtractRequest) -> dict:
    return _call(lambda: {"evidence": _service().extract(**body.model_dump())})


@router.post("/evidence/manual")
def manual_evidence(body: ManualEvidenceRequest) -> dict:
    return _call(lambda: {"evidence": _service().add_manual_evidence(**body.model_dump())})


@router.post("/verify")
def verify_evidence(body: VerifyRequest) -> dict:
    return _call(lambda: {"evidence": _service().verify(**body.model_dump())})


@router.post("/recommend")
def recommend_visualizations(body: RecommendRequest) -> dict:
    return _call(lambda: {"candidates": _service().recommend(**body.model_dump())})


@router.get("/{task_id}/candidates")
def list_candidates(task_id: str) -> dict:
    return _call(lambda: {"candidates": _service().candidates(task_id)})


@router.get("/candidate/{candidate_id}/preview")
def preview_candidate(candidate_id: str) -> dict:
    return _call(lambda: _service().preview(candidate_id))


@router.post("/candidate/{candidate_id}/insert")
def insert_candidate(candidate_id: str, body: InsertRequest) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=422, detail="请确认后再加入论文")
    return _call(lambda: _service().insert(candidate_id=candidate_id, section_id=body.section_id))
