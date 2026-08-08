"""论文大纲：生成与解析。"""

from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services import deepseek_service
from app.services.outline_service import parse_outline


def generate_outline(paper_info: dict) -> dict:
    """调用模型生成大纲（含章节层级与预计字数）。"""
    req = GenerateRequest.model_validate(paper_info)
    return deepseek_service.generate_outline(
        title=req.title, major=req.major,
        paper_type=req.paper_type, word_count=req.word_count)


def parse_outline_text(text: str) -> list[dict]:
    """把大纲文本解析为章节列表 [{title, level}]。"""
    return parse_outline(text)
