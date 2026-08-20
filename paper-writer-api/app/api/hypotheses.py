from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.services.hypothesis_service import HypothesisService

router = APIRouter(tags=["research-hypotheses"])


def _service() -> HypothesisService:
    return HypothesisService(settings)


def _problem(exc: ValueError, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


class HypothesisInput(BaseModel):
    task_id: str
    title: str = ""
    statement: str
    direction: str = "unknown"
    variable_bindings: dict[str, Any] = Field(default_factory=dict)
    analysis_ids: list[str] = Field(default_factory=list)


class HypothesisPatch(BaseModel):
    title: str | None = None
    statement: str | None = None
    direction: str | None = None
    variable_bindings: dict[str, Any] | None = None
    analysis_ids: list[str] | None = None


class EvaluationInput(BaseModel):
    analysis_id: str
    analysis_result_id: str


class FrameworkInput(BaseModel):
    task_id: str
    hypothesis_ids: list[str]
    finding_ids: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)
    # This optional field is untrusted prose and strictly checked by the service.
    ai_suggestion: dict[str, Any] | None = None


@router.post("/api/research/hypotheses")
def create_hypothesis(payload: HypothesisInput):
    try:
        return _service().create(**payload.model_dump())
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("/api/research/hypotheses")
def list_hypotheses(task_id: str = Query(..., min_length=1)):
    try:
        return {"hypotheses": _service().list(task_id)}
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("/api/research/hypotheses/{hypothesis_id}")
def get_hypothesis(hypothesis_id: str):
    try:
        return _service().get(hypothesis_id)
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.patch("/api/research/hypotheses/{hypothesis_id}")
def patch_hypothesis(hypothesis_id: str, payload: HypothesisPatch):
    try:
        changes = {key: value for key, value in payload.model_dump().items() if value is not None}
        return _service().update(hypothesis_id, changes)
    except ValueError as exc:
        raise _problem(exc) from exc


@router.post("/api/research/hypotheses/{hypothesis_id}/evaluate")
def evaluate_hypothesis(hypothesis_id: str, payload: EvaluationInput):
    try:
        return _service().evaluate(hypothesis_id=hypothesis_id, **payload.model_dump())
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("/api/research/hypotheses/{hypothesis_id}/evaluations")
def hypothesis_evaluations(hypothesis_id: str):
    try:
        return {"evaluations": _service().evaluations(hypothesis_id)}
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.post("/api/research/discussion/framework")
def create_discussion_framework(payload: FrameworkInput):
    try:
        return _service().create_framework(**payload.model_dump())
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("/api/research/discussion/framework/{framework_id}")
def get_discussion_framework(framework_id: str):
    try:
        return _service().get_framework(framework_id)
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.get("/api/research/hypothesis-evaluations/{evaluation_id}/evidence")
def evaluation_evidence(evaluation_id: str):
    try:
        return _service().evidence(evaluation_id)
    except ValueError as exc:
        raise _problem(exc, 404) from exc
