"""Build the paper_spec.json consumed by the paper-writer engine."""
from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services.outline_service import OUTLINES, allocate_words, parse_outline

EXAMPLE_REFS = [
    {"key": "ref1", "type": "journal", "title": "与《{title}》相关的示例研究", "authors": ["示例作者A"], "year": "2024", "source": "示例期刊", "volume": "50", "issue": "1", "pages": "1-10", "publisher": "", "city": "", "doi": "", "url": "", "citation": "[1]", "verified": False, "raw": "", "note": "示例文献，请替换为真实文献"},
    {"key": "ref2", "type": "book", "title": "{major}基础理论教程", "authors": ["示例作者B"], "year": "2023", "source": "示例出版社", "volume": "", "issue": "", "pages": "", "publisher": "示例出版社", "city": "北京", "doi": "", "url": "", "citation": "[2]", "verified": False, "raw": "", "note": "示例文献，请替换为真实文献"},
    {"key": "ref3", "type": "thesis", "title": "{major}相关方向研究", "authors": ["示例作者C"], "year": "2022", "source": "示例大学", "volume": "", "issue": "", "pages": "", "publisher": "", "city": "北京", "doi": "", "url": "", "citation": "[3]", "verified": False, "raw": "", "note": "示例文献，请替换为真实文献"},
]


def make_example_refs(title: str, major: str) -> list[dict]:
    refs = [dict(item) for item in EXAMPLE_REFS]
    for item in refs:
        item["title"] = item["title"].format(title=title, major=major)
    return refs


def _placeholder_paragraph(title: str, major: str, index: int, requirement: str = "") -> str:
    text = (
        f"本节围绕“{title}”展开论述。结合{major}专业背景，本节对相关概念与"
        f"研究进展进行归纳[2]，并在此基础上提出本文的分析思路。"
        f"（【示例内容】占位段落 {index}，请由 LLM/人工替换为真实内容。）"
    )
    if requirement:
        text += f" 本节已结合特殊要求“{requirement}”进行针对性处理。"
    return text


def _sections_default(request: GenerateRequest, title: str, major: str) -> list[dict]:
    sections: list[dict] = []
    requirement = (request.special_requirements or "").strip()
    for index, heading in enumerate(OUTLINES.get(request.paper_type, OUTLINES["课程论文"])):
        if index > 0:
            sections.append({"type": "p", "text": _placeholder_paragraph(title, major, index, requirement)})
        sections.append({"type": "h1", "text": heading})
    return sections


def _sections_from_outline(outline: str, title: str, major: str, word_count: int,
                           requirement: str = "") -> list[dict]:
    chapters = parse_outline(outline)
    tops = [chapter for chapter in chapters if chapter["level"] == 1] or chapters
    allocation = allocate_words(len(tops), word_count)
    top_index = -1
    sections: list[dict] = []
    for chapter in chapters:
        level = min(3, chapter["level"])
        sections.append({"type": f"h{level}", "text": chapter["title"]})
        if chapter["level"] == 1:
            top_index += 1
            words = allocation[min(top_index, len(allocation) - 1)] if allocation else word_count
            for index in range(1, max(1, min(6, round(words / 180))) + 1):
                sections.append({"type": "p", "text": _placeholder_paragraph(title, major, index, requirement)})
    return sections


def build_spec(request: GenerateRequest) -> dict:
    """Return a paper_spec.json dict consumable by the document formatter."""
    title = request.title
    major = request.major
    requirement = (request.special_requirements or "").strip()
    abstract = (
        f"本文围绕“{title}”这一主题，结合{major}领域的相关理论与研究进展，"
        f"对该问题进行了系统梳理与分析[1]。研究发现，该主题具有重要的理论意义"
        f"与实践价值，但现有研究仍存在一定的拓展空间。"
        "（【示例内容】此摘要由 API 自动生成，正式使用请替换为真实摘要。）"
    )
    if requirement:
        abstract += f" 本文特别考虑了以下特殊要求：{requirement}。"
    if request.generation_mode == "outline" and (request.outline or "").strip():
        sections = _sections_from_outline(request.outline or "", title, major, request.word_count, requirement)
    else:
        sections = _sections_default(request, title, major)
    sections.append({"type": "references", "items": []})
    return {
        "meta": {"title": title, "abstract": abstract, "keywords": [major, title[:8] if len(title) > 8 else title, "研究"], "reference_style": request.reference_style, "citation_style": "numeric"},
        "sections": sections,
        "references": make_example_refs(title, major),
    }
