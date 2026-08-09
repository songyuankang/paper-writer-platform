"""AI 模型配置接口。"""

from fastapi import APIRouter, HTTPException

from app.models.model_config import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelTestRequest,
)
from app.services import model_service

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def list_models() -> dict:
    return {"models": model_service.list_models()}


@router.post("")
def create_model(data: ModelConfigCreate) -> dict:
    return model_service.create_model(data)


@router.put("/{model_id}")
def update_model(model_id: str, data: ModelConfigUpdate) -> dict:
    record = model_service.update_model(model_id, data)
    if record is None:
        raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")
    return record


@router.delete("/{model_id}")
def delete_model(model_id: str) -> dict:
    if not model_service.delete_model(model_id):
        raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")
    return {"deleted": model_id}


@router.post("/test")
def test_model(payload: ModelTestRequest) -> dict:
    try:
        return model_service.test_connection(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - 透出 DeepSeek 错误信息
        raise HTTPException(status_code=400, detail=f"连接失败：{exc}")


@router.post("/default/{model_id}")
def set_default(model_id: str) -> dict:
    if not model_service.set_default(model_id):
        raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")
    return {"default": model_id}
