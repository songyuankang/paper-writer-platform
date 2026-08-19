"""Evidence-first semantic insight blocks for the paper editor.

This module intentionally distinguishes verified numeric charts from qualitative
summaries. It never creates sample percentages, scores, trends, or other
unverifiable numeric claims.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

InsightIntent = Literal[
    "auto", "chart", "comparison_table", "problem_solution_table",
    "method_table", "framework_diagram",
]
InsightKind = Literal[
    "chart", "three_line_table", "comparison_table", "problem_solution_table",
    "method_table", "framework_diagram",
]


class InsightCreateRequest(BaseModel):
    scope: Literal["section", "chapter", "full_paper"] = "full_paper"
    intent: InsightIntent = "auto"
    placement: Literal["section_end", "after_current"] = "section_end"


class InsightRegenerateRequest(BaseModel):
    scope: Literal["section", "chapter", "full_paper"] = "full_paper"
    intent: InsightIntent = "auto"


class InsightPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    caption: str | None = Field(default=None, max_length=220)
    table: dict | None = None
    display_scale: float | None = Field(default=None, ge=0.5, le=1.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 180) -> str:
    text = re.sub(r"[<>\\x00-\\x1f]", " ", str(value or ""))
    return re.sub(r"\\s+", " ", text).strip()[:limit]


def _walk(items: list[dict]):
    for item in items:
        yield item
        children = item.get("children") or item.get("sections") or []
        if isinstance(children, list):
            yield from _walk(children)


def _section(draft: dict, section_id: str) -> dict:
    for item in _walk(draft.get("sections") or []):
        if item.get("id") == section_id:
            item.setdefault("paragraphs", [])
            return item
    raise ValueError("未找到目标小节")


def _locate(draft: dict, block_id: str) -> tuple[dict, dict]:
    for section in _walk(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("id") == block_id:
                return section, block
    raise ValueError("未找到总结块")


def _number(value: object) -> float | None:
    try:
        cleaned = re.sub(r"[^0-9.\\-]", "", str(value or ""))
        if not cleaned:
            return None
        parsed = float(cleaned)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _is_numeric_table(block: dict) -> bool:
    headers = block.get("headers") or []
    rows = block.get("rows") or []
    if len(headers) < 2 or len(rows) < 2:
        return False
    for column in range(1, len(headers)):
        if all(_number(row[column] if len(row) > column else None) is not None for row in rows):
            return True
    return False


def _scope_sections(draft: dict, target: dict, scope: str) -> list[dict]:
    all_sections = list(_walk(draft.get("sections") or []))
    if scope == "section":
        return [target]
    if scope == "chapter":
        prefix = str(target.get("id", "")).split("-")[0]
        selected = [item for item in all_sections if str(item.get("id", "")).split("-")[0] == prefix]
        return selected or [target]
    return all_sections or [target]


def _evidence(sections: list[dict]) -> list[dict]:
    result = []
    for section in sections:
        for paragraph in section.get("paragraphs") or []:
            if paragraph.get("type", "paragraph") != "paragraph":
                continue
            excerpt = _clean(paragraph.get("text"), 160)
            if excerpt:
                result.append({
                    "section_id": section.get("id"),
                    "paragraph_id": paragraph.get("id"),
                    "excerpt": excerpt,
                })
    return result[:24]


def _eligible_tables(sections: list[dict]) -> list[tuple[dict, dict]]:
    result = []
    for section in sections:
        for block in section.get("paragraphs") or []:
            if block.get("type") == "table" and _is_numeric_table(block):
                result.append((section, block))
    return result


def _intent_from_semantics(target: dict, intent: str) -> str:
    if intent != "auto":
        return intent
    title_probe = _clean(str(target.get("title") or ""), 160).lower()
    probe = _clean(" ".join([
        title_probe, str(target.get("gist") or ""),
        " ".join(target.get("keywords") or []),
    ]), 500).lower()
    # 标题代表当前插入位置的写作意图，优先级高于主旨和关键词中的泛化词。
    if any(word in title_probe for word in ("问题", "对策", "建议", "治理", "优化", "困境")):
        return "problem_solution_table"
    if any(word in title_probe for word in ("国内外", "研究进展", "研究现状", "文献综述", "比较", "已有积累", "研究基础")):
        return "comparison_table"
    if any(word in title_probe for word in ("方法", "技术路线", "实验", "样本", "设计")):
        return "method_table"
    if any(word in title_probe for word in ("理论", "机制", "框架", "影响因素", "关系")):
        return "framework_diagram"
    if any(word in probe for word in ("问题", "对策", "建议", "治理", "优化", "困境")):
        return "problem_solution_table"
    if any(word in probe for word in ("国内外", "研究进展", "研究现状", "文献综述", "比较")):
        return "comparison_table"
    if any(word in probe for word in ("方法", "技术路线", "实验", "样本", "设计", "模型")):
        return "method_table"
    if any(word in probe for word in ("理论", "机制", "框架", "路径", "影响因素", "关系")):
        return "framework_diagram"
    return "comparison_table"


def _chart_from_table(table: dict, title_hint: str) -> dict:
    headers = [_clean(item, 40) for item in table.get("headers") or []]
    rows = table.get("rows") or []
    categories = [_clean(row[0] if row else "", 32) for row in rows[:10]]
    series = []
    for column in range(1, min(len(headers), 4)):
        values = [_number(row[column] if len(row) > column else None) for row in rows[:10]]
        if values and all(value is not None for value in values):
            series.append({"name": headers[column] or f"指标{column}", "values": [float(value) for value in values], "axis": "left"})
    if len(categories) < 2 or not series:
        raise ValueError("数据表没有可用于图表的完整数值列")
    return {
        "kind": "bar" if len(series) == 1 else "mixed",
        "title": _clean(title_hint, 100) or "数据指标对比",
        "caption": "图表数值逐项来自用户维护的数据表。",
        "categories": categories,
        "series": series,
        "source_table_id": table.get("id"),
    }



def _compact_evidence(value: object, limit: int = 56) -> str:
    """把证据摘录收束为适合正文三线表的一句短摘要，不改变原始证据留存。"""
    text = _clean(value, 240)
    for marker in ("。", "；", ";", "！", "!", "？", "?"):
        position = text.find(marker)
        if 8 <= position < limit:
            return text[: position + 1]
    return _clean(text, limit)


def _fallback_table(target: dict, sections: list[dict], evidence: list[dict], intent: str) -> tuple[str, dict, str]:
    """生成正文友好的紧凑三线表；完整原文仅保留在 evidence 字段中供展开查看。"""
    title = _clean(target.get("title"), 70) or "本节要点"
    relevant = evidence[:3]
    if not relevant:
        raise ValueError("当前范围尚无可归纳的正文证据。")
    keywords = [str(item).strip() for item in (target.get("keywords") or []) if str(item).strip()]

    def keyword_for(index: int) -> str:
        return _clean(keywords[index] if index < len(keywords) else f"要点 {index + 1}", 18)

    if intent == "problem_solution_table":
        headers = ["问题要点", "关联线索", "讨论方向"]
        rows = [
            [f"问题 {index + 1}", _compact_evidence(item.get("excerpt"), 42), "结合本节证据进一步讨论"]
            for index, item in enumerate(relevant)
        ]
        return "problem_solution_table", {"style": "three_line", "headers": headers, "rows": rows}, f"基于“{title}”正文证据的紧凑问题归纳。"

    if intent == "method_table":
        headers = ["研究方法", "应用重点", "正文依据"]
        rows = [
            [keyword_for(index), _compact_evidence(item.get("excerpt"), 38), "本节论述摘要"]
            for index, item in enumerate(relevant)
        ]
        return "method_table", {"style": "three_line", "headers": headers, "rows": rows}, f"基于“{title}”正文证据的紧凑方法归纳。"

    headers = ["研究要点", "关键词", "主要内容"]
    rows = [
        [f"要点 {index + 1}", keyword_for(index), _compact_evidence(item.get("excerpt"), 52)]
        for index, item in enumerate(relevant)
    ]
    return "comparison_table", {"style": "three_line", "headers": headers, "rows": rows}, f"基于“{title}”正文证据的紧凑归纳；完整证据可展开查看。"

def _framework(target: dict, sections: list[dict], evidence: list[dict]) -> dict:
    title = _clean(target.get("title"), 80) or "研究框架"
    keywords = [_clean(item, 26) for item in (target.get("keywords") or []) if _clean(item, 26)]
    labels = [title] + keywords[:4]
    if len(labels) < 3:
        labels += [_clean(item.get("title"), 26) for item in sections if item.get("title")][:3]
    labels = [label for index, label in enumerate(labels) if label and label not in labels[:index]][:5]
    if len(labels) < 2:
        raise ValueError("目录与关键词不足，无法形成可核验的结构框架。")
    groups = ["input", "process", "process", "output", "constraint"]
    nodes = [{"id": f"n{index}", "label": label, "group": groups[min(index, len(groups) - 1)]} for index, label in enumerate(labels)]
    edges = [{"from": nodes[index]["id"], "to": nodes[index + 1]["id"], "label": "衔接"} for index in range(len(nodes) - 1)]
    return {"nodes": nodes, "edges": edges}


def _make_block(draft: dict, target: dict, request: InsightCreateRequest) -> dict:
    sections = _scope_sections(draft, target, request.scope)
    evidence = _evidence(sections)
    tables = _eligible_tables([target])  # 数据图只取当前插入小节的用户表，避免跨章节误用。
    selected_intent = _intent_from_semantics(target, request.intent)

    if request.intent == "chart" and not tables:
        raise ValueError("当前小节没有可追溯的结构化数值表，不能生成数据图表。请补充数据表，或改用自动判断 / 总结表。")
    if request.intent == "auto" and tables:
        selected_intent = "chart"

    block = {
        "id": "insight_" + uuid.uuid4().hex[:12],
        "type": "insight",
        "version": 1,
        "scope": request.scope,
        "generated_at": _now(),
        "display_scale": 0.75,
        "evidence": evidence,
    }
    if selected_intent == "chart":
        _, table = tables[0]
        chart = _chart_from_table(table, f"{_clean(target.get('title'), 70)}数据对比")
        block.update({
            "kind": "chart", "title": chart["title"], "caption": chart["caption"],
            "source_status": "user_data", "chart": chart,
            "evidence": [{"section_id": target.get("id"), "table_id": table.get("id"), "excerpt": "用户维护的结构化数据表", "field": "图表数据来源"}],
        })
        return block
    if selected_intent == "framework_diagram":
        framework = _framework(target, sections, evidence)
        title = f"{_clean(target.get('title'), 70)}研究逻辑框架"
        block.update({
            "kind": "framework_diagram", "title": title,
            "caption": "本图依据论文题目、目录结构、章节主旨与关键词归纳，用于呈现研究逻辑，不表示统计数据或实证结论。",
            "source_status": "outline_synthesis", "framework": framework,
        })
        return block
    kind, table, caption = _fallback_table(target, sections, evidence, selected_intent)
    block.update({
        "kind": kind, "title": f"{_clean(target.get('title'), 70)}要点归纳",
        "caption": caption, "source_status": "text_synthesis", "table": table,
    })
    return block


def create_insight_block(service, section_id: str, request: InsightCreateRequest) -> dict:
    draft = service.load()
    target = _section(draft, section_id)
    block = _make_block(draft, target, request)
    target.setdefault("paragraphs", []).append(block)
    service.save(draft)
    return block


def regenerate_insight_block(service, block_id: str, request: InsightRegenerateRequest) -> dict:
    draft = service.load()
    target, existing = _locate(draft, block_id)
    if existing.get("type") != "insight":
        raise ValueError("目标内容块不是总结块")
    replacement = _make_block(draft, target, InsightCreateRequest(scope=request.scope, intent=request.intent))
    replacement["id"] = existing["id"]
    replacement["version"] = int(existing.get("version", 0)) + 1
    target["paragraphs"] = [replacement if item.get("id") == block_id else item for item in target.get("paragraphs") or []]
    service.save(draft)
    return replacement


def patch_insight_block(service, block_id: str, request: InsightPatchRequest) -> dict:
    draft = service.load()
    _, block = _locate(draft, block_id)
    if block.get("type") != "insight":
        raise ValueError("目标内容块不是总结块")
    if request.title is not None:
        block["title"] = _clean(request.title, 100)
    if request.caption is not None:
        block["caption"] = _clean(request.caption, 220)
    if request.display_scale is not None:
        block["display_scale"] = request.display_scale
    if request.table is not None and block.get("kind") != "chart":
        headers = [_clean(item, 60) for item in (request.table.get("headers") or [])[:6]]
        rows = [[_clean(cell, 180) for cell in row[:6]] for row in (request.table.get("rows") or [])[:8]]
        if len(headers) < 2 or not rows:
            raise ValueError("三线表至少需要两列且包含一行内容")
        block["table"] = {"style": "three_line", "headers": headers, "rows": rows}
    block["updated_at"] = _now()
    service.save(draft)
    return block
