"""Structured research Dataset API; separate from material upload parsing."""
from __future__ import annotations

import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.services.dataset_service import DatasetService

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
_TASK_ID = re.compile(r"^[0-9a-f]{32}$")


def _service() -> DatasetService:
    return DatasetService(settings)


def _verify_task(task_id: str | None) -> str | None:
    if not task_id:
        return None
    if not _TASK_ID.fullmatch(task_id) or not (settings.output_dir / task_id).is_dir():
        raise HTTPException(status_code=404, detail="要关联的论文任务不存在")
    return task_id


def _problem(exc: Exception, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@router.post("/import")
def import_dataset(
    file: UploadFile | None = File(default=None),
    import_token: str | None = Form(default=None),
    source_filename: str | None = Form(default=None),
    name: str = Form(default=""),
    description: str = Form(default=""),
    dataset_id: str | None = Form(default=None),
    sheet: str | None = Form(default=None),
    task_id: str | None = Form(default=None),
) -> dict:
    """Stage a multi-sheet workbook or create an immutable DatasetVersion.

    For XLSX with more than one sheet, omit ``sheet`` on the first call. The
    response contains an ``import_token`` and available sheet names; submit the
    token plus the chosen sheet on the second call without re-uploading bytes.
    """
    service = _service()
    task_id = _verify_task(task_id)
    try:
        if import_token:
            result = service.import_staged(import_token, filename=source_filename, name=name, description=description, dataset_id=dataset_id, sheet=sheet, task_id=task_id)
            return {"status": "imported", "dataset": result}
        if file is None:
            raise ValueError("请上传 CSV 或 XLSX 文件")
        raw = file.file.read()
        if not raw:
            raise ValueError("上传文件为空")
        if len(raw) > settings.max_upload_bytes:
            raise ValueError(f"文件超过 {settings.max_upload_mb}MB 限制")
        filename = file.filename or "dataset"
        info = service.inspect_upload(filename, raw)
        if info["requires_sheet_selection"] and not sheet:
            staged = service.stage_upload(filename, raw)
            return {"status": "sheet_selection_required", **staged}
        result = service.import_data(filename=filename, raw=raw, name=name, description=description, dataset_id=dataset_id, sheet=sheet, task_id=task_id)
        return {"status": "imported", "dataset": result}
    except ValueError as exc:
        raise _problem(exc) from exc


@router.get("")
def list_datasets(task_id: str | None = None) -> dict:
    task_id = _verify_task(task_id)
    return {"datasets": _service().list_datasets(task_id)}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str) -> dict:
    try:
        return _service().get_dataset(dataset_id)
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.get("/{dataset_id}/versions")
def get_versions(dataset_id: str) -> dict:
    try:
        return {"dataset_id": dataset_id, "versions": _service().versions(dataset_id)}
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.get("/{dataset_id}/versions/{version}")
def get_version(dataset_id: str, version: int) -> dict:
    try:
        return _service().get_version(dataset_id, version, include_rows=False)
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.get("/{dataset_id}/versions/{version}/preview")
def get_preview(dataset_id: str, version: int, limit: int = 50, offset: int = 0) -> dict:
    try:
        return _service().preview(dataset_id, version, limit=limit, offset=offset)
    except ValueError as exc:
        raise _problem(exc, 404) from exc


@router.post("/{dataset_id}/attach")
def attach_dataset(dataset_id: str, task_id: str = Form(...)) -> dict:
    task_id = _verify_task(task_id)
    try:
        return {"dataset": _service().attach(dataset_id, str(task_id))}
    except ValueError as exc:
        raise _problem(exc, 404) from exc
