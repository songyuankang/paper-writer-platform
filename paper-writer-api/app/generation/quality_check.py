"""全文检查：逻辑连贯、重复内容、字数、格式。"""

from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services import deepseek_service


def collect_full_text(chapters: list[dict]) -> str:
    parts = []
    for ch in chapters:
        parts.append(ch.get("title", ""))
        for b in ch.get("blocks", []):
            if b.get("type") in ("p", "h2", "h3"):
                parts.append(b.get("text", ""))
    return "\n".join(parts)


def check_paper(paper_info: dict, full_text: str) -> dict:
    req = GenerateRequest.model_validate(paper_info)
    return deepseek_service.check_paper(req, full_text)
