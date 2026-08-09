"""分章节生成：摘要、单章（generate_section）、结论、参考文献。"""

from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services import deepseek_service


def generate_abstract(paper_info: dict) -> tuple[str, list[str]]:
    req = GenerateRequest.model_validate(paper_info)
    return deepseek_service.generate_abstract(
        req.title, req.major, req.paper_type,
        (req.special_requirements or "").strip())


def generate_section(paper_info: dict, chapter_info: dict,
                     previous_summary: str, requirements: dict) -> str:
    """单个章节独立调用模型。

    paper_info：标题/专业/类型/字数等
    chapter_info：{title, words, focus, index}
    previous_summary：前文章节摘要（避免重复）
    requirements：{outline, special_requirements, ...}
    返回：section_content（markdown 文本）
    """
    req = GenerateRequest.model_validate(paper_info)
    special = requirements.get("special_requirements")
    if special is not None:
        req = req.model_copy(update={"special_requirements": special})
    return deepseek_service.generate_chapter(
        req, chapter_info["title"], int(chapter_info.get("words") or 0),
        chapter_info.get("focus", ""), requirements.get("outline", ""),
        previous_summary)


def generate_conclusion(paper_info: dict, chapter_summaries: str) -> str:
    req = GenerateRequest.model_validate(paper_info)
    words = max(300, int(req.word_count * 0.1))
    return deepseek_service.generate_conclusion(req, chapter_summaries, words)


def generate_references(paper_info: dict, style: str) -> list[str]:
    req = GenerateRequest.model_validate(paper_info)
    return deepseek_service.generate_references(req, style)


def parse_section_markdown(text: str) -> list[dict]:
    """把章节 markdown 解析为 blocks（h2/h3/p）。"""
    return deepseek_service._parse_chapter(text)
