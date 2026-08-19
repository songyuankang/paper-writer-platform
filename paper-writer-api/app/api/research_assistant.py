"""Research-method assistant API; recommendation never runs analysis automatically."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.research_assistant_service import ALLOWED_METHODS, ResearchAssistantService

router = APIRouter(prefix="/api/research-assistant", tags=["research-assistant"])


class RecommendationRequest(BaseModel):
    research_question: str = Field(..., min_length=2, max_length=3000)
    hypothesis: str = Field(default="", max_length=2000)
    dataset_id: str = Field(..., min_length=4, max_length=160)
    dataset_version: int = Field(..., ge=1)
    model_id: str | None = Field(default=None, max_length=160)


class RunConfirmedRequest(BaseModel):
    task_id: str = Field(..., min_length=32, max_length=32)
    dataset_id: str = Field(..., min_length=4, max_length=160)
    dataset_version: int = Field(..., ge=1)
    method: str = Field(..., pattern="^(descriptive|pearson|spearman|independent_t|anova|regression)$")
    variables: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)


def _service() -> ResearchAssistantService:
    return ResearchAssistantService(settings)


@router.post("/recommend")
def recommend(body: RecommendationRequest) -> dict:
    try:
        return _service().recommend(question=body.research_question, hypothesis=body.hypothesis, dataset_id=body.dataset_id, dataset_version=body.dataset_version, model_id=body.model_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/run")
def run_confirmed(body: RunConfirmedRequest) -> dict:
    if body.method not in ALLOWED_METHODS:
        raise HTTPException(status_code=422, detail="推荐的方法不受当前 Analysis 引擎支持")
    try:
        return _service().run_confirmed(task_id=body.task_id, dataset_id=body.dataset_id, dataset_version=body.dataset_version, method=body.method, variables=body.variables, parameters=body.parameters)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
