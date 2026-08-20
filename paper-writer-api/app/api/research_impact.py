from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.services.dependency_graph_service import DependencyGraphService

router = APIRouter(tags=["research-impact"])


def _service() -> DependencyGraphService:
    return DependencyGraphService(settings)


@router.get("/api/research/impact/dataset/{dataset_id}/version/{version}")
def dataset_impact(dataset_id: str, version: int, task_id: str = Query(..., min_length=1)):
    try:
        return _service().get_impact(task_id=task_id, dataset_id=dataset_id, version=version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/research/results")
def results_center(task_id: str = Query(..., min_length=1), kind: str | None = None):
    try:
        return _service().results_center(task_id, kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/research/findings/{finding_id}/evidence")
def finding_evidence(finding_id: str):
    try:
        return _service().evidence(finding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/tasks/{task_id}/dependencies")
def dependency_links(task_id: str):
    try:
        return {"links": _service().rebuild_task(task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
