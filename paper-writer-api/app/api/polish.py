"""段落优化接口：对粘贴文本进行润色/扩写/缩写/修改/翻译等处理。

对应 aiunipaper 的"段落优化"功能，独立于论文任务，直接调用 AI 模型。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import deepseek, deepseek_service, model_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/polish", tags=["polish"])

PolishOperation = Literal["polish", "expand", "condense", "rewrite", "translate"]


class PolishRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000, description="待处理文本")
    operation: PolishOperation = Field("polish", description="操作类型")
    instruction: str = Field("", max_length=1000,
                             description="补充要求（翻译时为目标语言）")
    model_id: str | None = Field(None, description="指定使用的模型")


@router.post("")
def polish_text(req: PolishRequest) -> dict:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="请输入需要处理的文本")

    # 与生成管线一致：优先使用「模型设置」中启用的模型，其次环境变量配置。
    model_cfg = model_service.resolve_model(req.model_id)
    if model_cfg is None:
        raise HTTPException(
            status_code=400,
            detail="未配置 AI 模型，请先在「模型设置」中配置并启用模型")

    try:
        with deepseek.connection(model_cfg):
            result = deepseek_service.polish_text(
                text, req.operation, req.instruction)
    except deepseek.DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=f"AI 处理失败：{exc}")
    except Exception as exc:  # noqa: BLE001 - 兜底，避免 500 崩溃
        logger.exception("段落优化调用失败")
        raise HTTPException(status_code=500, detail=f"AI 处理失败：{exc}")
    return {"text": result, "operation": req.operation}
