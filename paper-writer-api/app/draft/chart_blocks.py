"""Safe chart-block creation for the draft editor.

The service deliberately stores a small JSON chart contract rather than arbitrary
ECharts options. Browser preview and export assets therefore use the same data.
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Literal
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

ChartKind = Literal["bar", "line", "mixed", "pie"]


class ChartCreateRequest(BaseModel):
    title_hint: str = Field(default="", max_length=80)
    chart_kind: ChartKind = "mixed"
    display_scale: float = Field(default=0.75, ge=0.5, le=1.0)
    illustrative: bool = False


class ChartPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    caption: str | None = Field(default=None, max_length=180)
    display_scale: float | None = Field(default=None, ge=0.5, le=1.0)


class ChartRegenerateRequest(BaseModel):
    chart_kind: ChartKind | None = None
    illustrative: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: object, limit: int = 200) -> str:
    text = re.sub(r"[<>\\x00-\\x1f]", " ", str(value or ""))
    return re.sub(r"\\s+", " ", text).strip()[:limit]


def _walk_sections(items: list[dict]):
    for section in items:
        yield section
        children = section.get("children") or section.get("sections") or []
        if isinstance(children, list):
            yield from _walk_sections(children)


def _section(draft: dict, section_id: str) -> dict:
    for item in _walk_sections(draft.get("sections") or []):
        if item.get("id") == section_id:
            item.setdefault("paragraphs", [])
            return item
    raise ValueError("未找到目标小节")


def _locate_block(draft: dict, block_id: str) -> tuple[dict, dict]:
    for section in _walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("id") == block_id:
                return section, block
    raise ValueError("未找到图表块")


def _number(value: object) -> float | None:
    try:
        cleaned = re.sub(r"[^0-9.\\-]", "", str(value))
        if not cleaned:
            return None
        parsed = float(cleaned)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _table_chart(section: dict, kind: str, title_hint: str) -> tuple[dict, str] | None:
    for block in section.get("paragraphs") or []:
        if block.get("type") != "table":
            continue
        headers = [_plain(v, 40) for v in block.get("headers") or []]
        rows = block.get("rows") or []
        if len(headers) < 2 or len(rows) < 2:
            continue
        categories = [_plain(row[0] if row else "", 32) for row in rows[:10]]
        valid_indexes = []
        for index in range(1, min(len(headers), 5)):
            values = [_number(row[index] if len(row) > index else None) for row in rows[:10]]
            if all(value is not None for value in values):
                valid_indexes.append((index, [float(value) for value in values]))
        if not categories or not valid_indexes:
            continue
        series = []
        for position, (index, values) in enumerate(valid_indexes):
            series.append({
                "name": headers[index] or f"指标{position + 1}",
                "values": values,
                "axis": "left" if position == 0 else "right",
            })
        safe_kind = kind if kind in {"bar", "line", "mixed", "pie"} else "bar"
        if safe_kind == "pie":
            pie = [{"name": name, "value": value} for name, value in zip(categories, series[0]["values"])]
            chart = {"schema_version": 1, "kind": "pie", "title": title_hint or _plain(block.get("title") or section.get("title")) + "构成对比", "caption": "基于当前小节数据表自动生成。", "pie": pie}
        else:
            chart = {"schema_version": 1, "kind": safe_kind, "title": title_hint or _plain(block.get("title") or section.get("title")) + "关键指标对比", "caption": "基于当前小节数据表自动生成。", "categories": categories, "series": series}
        return chart, "user_provided"
    return None


def _fallback_chart(section: dict, kind: str, title_hint: str) -> dict:
    title = title_hint or f"{_plain(section.get('title') or '本小节')}分析示意"
    labels = ["现状", "方案一", "方案二", "优化后"]
    return {
        "schema_version": 1,
        "kind": kind if kind in {"bar", "line", "mixed", "pie"} else "mixed",
        "title": title,
        "caption": "示意性模型图，数值仅用于表达比较关系，未核验外部来源。",
        "categories": labels,
        "series": [
            {"name": "综合指标", "values": [42, 58, 71, 86], "axis": "left"},
            {"name": "风险水平", "values": [78, 61, 46, 28], "axis": "right"},
        ],
    }


def _ai_chart(section: dict, kind: str, title_hint: str) -> dict | None:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    text = "\\n".join(_plain(block.get("text"), 600) for block in section.get("paragraphs") or [] if block.get("type", "paragraph") == "paragraph")[:2400]
    if not text:
        return None
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    prompt = {
        "role": "user",
        "content": "Create a compact Chinese academic chart specification. Return JSON only. Use no HTML. The values are illustrative and must be labelled as unverified. Schema: {kind,title,caption,categories,series:[{name,values,axis}]}. Allowed kinds: bar,line,mixed,pie. 2-8 categories, 1-3 series, finite numeric values only. Requested kind: %s. Title hint: %s. Section: %s. Text: %s" % (kind, _plain(title_hint, 80), _plain(section.get("title"), 100), text),
    }
    payload = {"model": model, "messages": [prompt], "temperature": 0.2, "max_tokens": 1000, "response_format": {"type": "json_object"}}
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=35) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        spec = json.loads(content)
        return _validate_ai_spec(spec, kind, title_hint)
    except (URLError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _validate_ai_spec(spec: dict, requested_kind: str, title_hint: str) -> dict | None:
    kind = spec.get("kind") if spec.get("kind") in {"bar", "line", "mixed", "pie"} else requested_kind
    categories = [_plain(item, 32) for item in spec.get("categories") or []][:10]
    series = []
    for item in (spec.get("series") or [])[:3]:
        values = [_number(value) for value in item.get("values") or []]
        if not values or any(value is None for value in values):
            continue
        values = [float(value) for value in values]
        if categories and len(values) != len(categories):
            continue
        series.append({"name": _plain(item.get("name"), 48) or "指标", "values": values, "axis": "right" if item.get("axis") == "right" else "left"})
    if kind == "pie":
        if not categories or not series:
            return None
        return {"schema_version": 1, "kind": "pie", "title": _plain(title_hint or spec.get("title"), 80) or "指标构成对比", "caption": "模型生成的示意性比较图，未核验外部来源。", "pie": [{"name": name, "value": value} for name, value in zip(categories, series[0]["values"])]}
    if len(categories) < 2 or not series:
        return None
    return {"schema_version": 1, "kind": kind, "title": _plain(title_hint or spec.get("title"), 80) or "关键指标对比", "caption": "模型生成的示意性比较图，未核验外部来源。", "categories": categories, "series": series}


def _build_chart(section: dict, request: ChartCreateRequest) -> tuple[dict, str]:
    table_result = _table_chart(section, request.chart_kind, request.title_hint)
    if table_result:
        return table_result
    if not request.illustrative:
        raise ValueError("当前小节没有可用于定量图表的数据表。请先新增数据表，或勾选示意图生成。")
    chart = _ai_chart(section, request.chart_kind, request.title_hint) or _fallback_chart(section, request.chart_kind, request.title_hint)
    return chart, "model_generated" if os.getenv("DEEPSEEK_API_KEY", "").strip() else "illustrative"


def create_chart_block(service, section_id: str, request: ChartCreateRequest) -> dict:
    draft = service.load()
    section = _section(draft, section_id)
    chart, provenance = _build_chart(section, request)
    block = {
        "id": "chart_" + uuid.uuid4().hex[:12],
        "type": "chart",
        "status": "ready",
        "version": 1,
        "text": "",
        "title": chart["title"],
        "caption": chart["caption"],
        "chart": chart,
        "display_scale": request.display_scale,
        "provenance": provenance,
        "source_ids": [],
        "generated_at": _now(),
    }
    section.setdefault("paragraphs", []).append(block)
    service.save(draft)
    return block


def regenerate_chart_block(service, block_id: str, request: ChartRegenerateRequest) -> dict:
    draft = service.load()
    section, block = _locate_block(draft, block_id)
    if block.get("type") != "chart":
        raise ValueError("目标内容块不是图表")
    create = ChartCreateRequest(title_hint=_plain(block.get("title"), 80), chart_kind=request.chart_kind or (block.get("chart") or {}).get("kind", "mixed"), display_scale=block.get("display_scale", 0.75), illustrative=request.illustrative)
    chart, provenance = _build_chart(section, create)
    block.update({"status": "ready", "version": int(block.get("version", 0)) + 1, "title": chart["title"], "caption": chart["caption"], "chart": chart, "provenance": provenance, "generated_at": _now(), "error": None})
    service.save(draft)
    return block


def patch_chart_block(service, block_id: str, request: ChartPatchRequest) -> dict:
    draft = service.load()
    _, block = _locate_block(draft, block_id)
    if block.get("type") != "chart":
        raise ValueError("目标内容块不是图表")
    if request.title is not None:
        block["title"] = _plain(request.title, 80)
        block.setdefault("chart", {})["title"] = block["title"]
    if request.caption is not None:
        block["caption"] = _plain(request.caption, 180)
        block.setdefault("chart", {})["caption"] = block["caption"]
    if request.display_scale is not None:
        block["display_scale"] = request.display_scale
    block["updated_at"] = _now()
    service.save(draft)
    return block
