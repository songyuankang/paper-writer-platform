from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.draft.analysis_blocks import insert_analysis_result
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api/analyses", tags=["analyses"])
_TASK_ID = re.compile(r"^[0-9a-f]{32}$")


def _service() -> AnalysisService:
    return AnalysisService(settings)


def _problem(exc: Exception, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _validate_task(task_id: str) -> str:
    if not _TASK_ID.fullmatch(task_id) or not (settings.output_dir / task_id).is_dir():
        raise HTTPException(status_code=404, detail="论文任务不存在")
    return task_id


class AnalysisCreateRequest(BaseModel):
    task_id: str = Field(..., min_length=32, max_length=32)
    dataset_id: str = Field(..., min_length=4, max_length=160)
    dataset_version: int | None = Field(default=None, ge=1)
    type: str = Field(..., pattern="^(descriptive|pearson|spearman|independent_t|anova|regression)$")
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    variables: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)


class AnalysisInsertRequest(BaseModel):
    section_id: str = Field(..., min_length=1, max_length=160)
    result_id: str | None = Field(default=None, max_length=160)
    artifact: str = Field(default="table", pattern="^(table|chart|actual_predicted|residual|coefficient)$")


@router.post("")
def create_analysis(body: AnalysisCreateRequest) -> dict:
    _validate_task(body.task_id)
    try:
        analysis = _service().create(
            task_id=body.task_id, dataset_id=body.dataset_id, dataset_version=body.dataset_version,
            analysis_type=body.type, variables=body.variables, name=body.name,
            description=body.description, parameters=body.parameters,
        )
        return {"analysis": analysis}
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("")
def list_analyses(task_id: str | None = None, dataset_id: str | None = None) -> dict:
    if task_id:
        _validate_task(task_id)
    return {"analyses": _service().list(task_id=task_id, dataset_id=dataset_id)}


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    try:
        analysis = _service().get(analysis_id)
        _validate_task(str(analysis["task_id"]))
        return {"analysis": analysis}
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.post("/{analysis_id}/run")
def run_analysis(analysis_id: str) -> dict:
    try:
        analysis = _service().get(analysis_id)
        _validate_task(str(analysis["task_id"]))
        return {"analysis": _service().get(analysis_id), "result": _service().run(analysis_id)}
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.get("/{analysis_id}/result")
def get_analysis_result(analysis_id: str, result_id: str | None = None) -> dict:
    try:
        analysis = _service().get(analysis_id)
        _validate_task(str(analysis["task_id"]))
        return {"result": _service().get_result(analysis_id, result_id)}
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.post("/{analysis_id}/insert")
def insert_result(analysis_id: str, body: AnalysisInsertRequest) -> dict:
    try:
        analysis = _service().get(analysis_id)
        task_id = _validate_task(str(analysis["task_id"]))
        result = _service().get_result(analysis_id, body.result_id)
        block = insert_analysis_result(
            task_id=task_id, analysis=analysis, result=result,
            section_id=body.section_id, artifact=body.artifact,
        )
        return {"block": block, "analysis": _service().get(analysis_id), "result": result}
    except ValueError as exc:
        raise _problem(exc) from exc
