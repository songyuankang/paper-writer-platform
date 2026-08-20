from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.cross_reference_service import CrossReferenceService

router = APIRouter(tags=["cross-references"])


def _service() -> CrossReferenceService:
    return CrossReferenceService(settings)


class CreateReferenceRequest(BaseModel):
    target_object_id: str = Field(..., min_length=8)
    # source_block_id supports attaching a record to an already structured block;
    # section_id is the normal editor path and creates a text/reference/text block.
    source_block_id: str | None = None
    section_id: str | None = None
    prefix: str = Field(default="如", max_length=300)
    suffix: str = Field(default="所示", max_length=300)


class UpdateReferenceRequest(BaseModel):
    target_object_id: str = Field(..., min_length=8)


@router.get("/api/tasks/{task_id}/research-objects/references")
def reference_candidates(task_id: str):
    try:
        return {"objects": _service().reference_candidates(task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/tasks/{task_id}/references")
def list_references(task_id: str):
    try:
        return {"references": _service().list(task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/references")
def create_reference(task_id: str, body: CreateReferenceRequest):
    try:
        service = _service()
        if body.section_id:
            return service.insert(
                task_id=task_id, section_id=body.section_id,
                target_object_id=body.target_object_id,
                prefix=body.prefix, suffix=body.suffix,
            )
        if not body.source_block_id:
            raise ValueError("必须提供 section_id 或 source_block_id")
        return {"reference": service.create(
            task_id=task_id, source_block_id=body.source_block_id,
            target_object_id=body.target_object_id,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/api/tasks/{task_id}/references/{reference_id}")
def update_reference(task_id: str, reference_id: str, body: UpdateReferenceRequest):
    try:
        return {"reference": _service().update(
            task_id=task_id, reference_id=reference_id,
            target_object_id=body.target_object_id,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/tasks/{task_id}/references/{reference_id}")
def delete_reference(task_id: str, reference_id: str):
    try:
        _service().delete(task_id=task_id, reference_id=reference_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
