"""Build the paper_spec.json consumed by the paper-writer engine.

Phase-1 implementation: deterministic placeholder content so the full API
pipeline (queue -> template parse -> charts -> docx -> checks) is testable.
All generated text is clearly marked 示例内容. Swap ``build_spec`` with an LLM
backend later without touching the rest of the pipeline.
"""

from __future__ import annotations

from app.models.generate import GenerateRequest
from app.services.outline_service import OUTLINES, allocate_words, parse_outline

EXAMPLE_REFS = [
    {
        "key": "ref1", "type": "journal", "title": "与《{title}》相关的示例研究",
        "authors": ["示例作者A"], "year": "2024", "source": "示例期刊",
        "volume": "50", "issue": "1", "pages": "1-10", "publisher": "",
        "city": "", "doi": "", "url": "", "citation": "[1]",
        "verified": False, "raw": "", "note": "示例文献，请替换为真实文献",
    },
    {
        "key": "ref2", "type": "book", "title": "{major}基础理论教程",
        "authors": ["示例作者B"], "year": "2023", "source": "示例出版社",
        "volume": "", "issue": "", "pages": "", "publisher": "示例出版社",
        "city": "北京", "doi": "", "url": "", "citation": "[2]",
        "verified": False, "raw": "", "note": "示例文献，请替换为真实文献",
    },
    {
        "key": "ref3", "type": "thesis", "title": "{major}相关方向研究",
        "authors": ["示例作者C"], "year": "2022", "source": "示例大学",
        "volume": "", "issue": "", "pages": "", "publisher": "",
        "city": "北京", "doi": "", "url": "", "citation": "[3]",
        "verified": False, "raw": "", "note": "示例文献，请替换为真实文献",
    },
]


def make_example_refs(title: str, major: str) -> list[dict]:
    """构造示例参考文献条目（标注示例，需替换为真实文献）。"""
    refs = [dict(r) for r in EXAMPLE_REFS]
    for r in refs:
        r["title"] = r["title"].format(title=title, major=major)
    return refs


def inject_charts_into_sections(sections: list[dict],
                                charts: list[dict]) -> list[dict]:
    """把图表按一级章节分配并插入（图号自动编号 图1-1、图1-2…）。"""
    n = max(1, sum(1 for s in sections if s["type"] == "h1"))
    seq_counter: dict[int, int] = {}
    by_chapter: dict[int, list[dict]] = {}
    for k, chart in enumerate(charts):
        chapter = (k % n) + 1
        seq_counter[chapter] = seq_counter.get(chapter, 0) + 1
        chart["number"] = f"{chapter}-{seq_counter[chapter]}"
        chart["caption"] = f"图{chart['number']} {chart['title']}"
        by_chapter.setdefault(chapter, []).append(chart)

    def chart_blocks(chapter: int) -> list[dict]:
        blocks: list[dict] = []
        for chart in by_chapter.get(chapter, []):
            blocks.append({"type": "p", "text": (
                f"如图{chart['number']}所示，该{chart['label']}用于展示相关数据的"
                f"分布与趋势（示例数据，需替换为真实数据）。"
            )})
            blocks.append({"type": "figure",
                           "path": f"charts/{chart['file']}",
                           "title": chart["caption"]})
        return blocks

    out: list[dict] = []
    chapter = 0
    for item in sections:
        if item["type"] == "h1":
            if chapter > 0 and chapter in by_chapter:
                out.extend(chart_blocks(chapter))
            chapter += 1
        out.append(item)
    if chapter > 0 and chapter in by_chapter:
        out.extend(chart_blocks(chapter))
    return out


def _sample_data():
    return [
        {"年份": 2021, "指标": 120},
        {"年份": 2022, "指标": 168},
        {"年份": 2023, "指标": 205},
        {"年份": 2024, "指标": 246},
    ]


def _placeholder_paragraph(title: str, major: str, index: int,
                           requirement: str = "") -> str:
    text = (
        f"本节围绕“{title}”展开论述。结合{major}专业背景，本节对相关概念与"
        f"研究进展进行归纳[2]，并在此基础上提出本文的分析思路。"
        f"（【示例内容】占位段落 {index}，请由 LLM/人工替换为真实内容。）"
    )
    if requirement:
        text += f" 本节已结合特殊要求“{requirement}”进行针对性处理。"
    return text


def _sections_default(request: GenerateRequest, title: str,
                      major: str) -> list[dict]:
    sections: list[dict] = []
    requirement = (request.special_requirements or "").strip()
    for idx, heading in enumerate(OUTLINES.get(request.paper_type, OUTLINES["课程论文"])):
        if idx > 0:
            sections.append({"type": "p", "text": _placeholder_paragraph(
                title, major, idx, requirement)})
        sections.append({"type": "h1", "text": heading})
    return sections


def _sections_from_outline(outline: str, title: str, major: str,
                           word_count: int, requirement: str = "") -> list[dict]:
    chapters = parse_outline(outline)
    tops = [c for c in chapters if c["level"] == 1] or chapters
    alloc = allocate_words(len(tops), word_count)
    top_index = -1
    sections: list[dict] = []
    for chapter in chapters:
        level = min(3, chapter["level"])
        sections.append({"type": f"h{level}", "text": chapter["title"]})
        if chapter["level"] == 1:
            top_index += 1
            words = alloc[min(top_index, len(alloc) - 1)] if alloc else word_count
            n_paras = max(1, min(6, round(words / 180)))
            for p in range(1, n_paras + 1):
                sections.append({"type": "p", "text": _placeholder_paragraph(
                    title, major, p, requirement)})
    return sections


def _sections_with_charts(request: GenerateRequest, title: str, major: str,
                          charts: list[dict]) -> list[dict]:
    """按大纲/默认结构生成章节，并把图表按章分配、自动编号（图1-1、图1-2…）。"""
    requirement = (request.special_requirements or "").strip()
    outline_mode = request.generation_mode == "outline" and \
        (request.outline or "").strip()
    if outline_mode:
        chapters = parse_outline(request.outline or "")
        tops = [c for c in chapters if c["level"] == 1] or chapters
        n_chapters = len(tops)
    else:
        chapters = []
        n_chapters = len(OUTLINES.get(request.paper_type, OUTLINES["课程论文"]))

    n = max(1, n_chapters)
    seq_counter: dict[int, int] = {}
    by_chapter: dict[int, list[dict]] = {}
    for k, chart in enumerate(charts):
        chapter = (k % n) + 1
        seq_counter[chapter] = seq_counter.get(chapter, 0) + 1
        chart["chapter"] = chapter
        chart["number"] = f"{chapter}-{seq_counter[chapter]}"
        chart["caption"] = f"图{chart['number']} {chart['title']}"
        by_chapter.setdefault(chapter, []).append(chart)

    def chart_blocks(chapter: int) -> list[dict]:
        blocks: list[dict] = []
        for chart in by_chapter.get(chapter, []):
            blocks.append({"type": "p", "text": (
                f"如图{chart['number']}所示，该{chart['label']}用于展示相关数据的"
                f"分布与趋势（示例数据，需替换为真实数据）。"
            )})
            blocks.append({"type": "figure",
                           "path": f"charts/{chart['file']}",
                           "title": chart["caption"]})
        return blocks

    sections: list[dict] = []
    if outline_mode:
        alloc = allocate_words(n_chapters, request.word_count)
        top_index = -1
        for chapter in chapters:
            level = min(3, chapter["level"])
            sections.append({"type": f"h{level}", "text": chapter["title"]})
            if chapter["level"] == 1:
                top_index += 1
                words = alloc[min(top_index, len(alloc) - 1)] if alloc \
                    else request.word_count
                n_paras = max(1, min(6, round(words / 180)))
                for p in range(1, n_paras + 1):
                    sections.append({"type": "p", "text": _placeholder_paragraph(
                        title, major, p, requirement)})
                sections.extend(chart_blocks(top_index + 1))
    else:
        for idx, heading in enumerate(
                OUTLINES.get(request.paper_type, OUTLINES["课程论文"])):
            if idx > 0:
                sections.append({"type": "p", "text": _placeholder_paragraph(
                    title, major, idx, requirement)})
            sections.append({"type": "h1", "text": heading})
            sections.extend(chart_blocks(idx + 1))
    return sections


def build_spec(request: GenerateRequest, charts: list[dict] | None = None) -> dict:
    """Return a paper_spec.json dict consumable by build_docx.py."""
    title = request.title
    major = request.major
    requirement = (request.special_requirements or "").strip()
    refs = make_example_refs(title, major)

    abstract = (
        f"本文围绕“{title}”这一主题，结合{major}领域的相关理论与研究进展，"
        f"对该问题进行了系统梳理与分析[1]。研究发现，该主题具有重要的理论意义"
        f"与实践价值，但现有研究仍存在一定的拓展空间。"
        f"（【示例内容】此摘要由 API 自动生成，正式使用请替换为真实摘要。）"
    )
    if requirement:
        abstract += f" 本文特别考虑了以下特殊要求：{requirement}。"
    keywords = [major, title[:8] if len(title) > 8 else title, "研究"]

    if charts:
        sections = _sections_with_charts(request, title, major, charts)
    elif request.generation_mode == "outline" and (request.outline or "").strip():
        sections = _sections_from_outline(
            request.outline or "", title, major, request.word_count, requirement)
    else:
        sections = _sections_default(request, title, major)

    if charts is None and request.chart_enabled:
        sections.extend([
            {"type": "p", "text": (
                "图1展示了示例数据的变化趋势，数据为 API 自动构造的示例数据，"
                "需替换为真实数据后使用。" 
            )},
            {"type": "figure", "path": "figures/fig1.png",
             "title": "图1 示例数据变化趋势"},
            {"type": "table", "title": "表1 示例数据",
             "headers": ["年份", "指标"],
             "rows": [[str(d["年份"]), str(d["指标"])] for d in _sample_data()]},
        ])

    sections.append({"type": "references", "items": []})  # filled by paper_service

    return {
        "meta": {
            "title": title,
            "abstract": abstract,
            "keywords": keywords,
            "reference_style": request.reference_style,
            "citation_style": "numeric",
        },
        "sections": sections,
        "references": refs,
    }
