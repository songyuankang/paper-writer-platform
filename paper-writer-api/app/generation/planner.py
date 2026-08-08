"""论文生成规划：章节列表、目标字数、写作重点。"""

from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services import deepseek_service
from app.services.outline_service import OUTLINES, allocate_words


def generate_plan(paper_info: dict) -> dict:
    """调用模型生成规划；解析失败时回退到内置结构。"""
    req = GenerateRequest.model_validate(paper_info)
    try:
        return deepseek_service.generate_plan(req)
    except Exception:
        return fallback_plan(paper_info)


def fallback_plan(paper_info: dict) -> dict:
    """未配置模型或解析失败时的确定性规划。"""
    paper_type = paper_info.get("paper_type", "课程论文")
    titles = OUTLINES.get(paper_type, OUTLINES["课程论文"])
    titles = [t.split(" ", 1)[-1] for t in titles]
    alloc = allocate_words(len(titles), paper_info.get("word_count", 3000))
    chapters = [{"title": f"第{i + 1}章 {t}", "words": alloc[i], "focus": t}
                for i, t in enumerate(titles)]
    outline_text = "\n".join(f"{c['title']}" for c in chapters)
    return {"chapters": chapters, "outline_text": outline_text}
