"""Chart block API adapters for the draft editor.

The business implementation lives in :mod:`chart_runtime`: TableBlock data is
versioned, a renderer-neutral ChartSpec is created, and PNG/SVG assets are
persisted before the block is returned to the UI.
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.draft.chart_runtime import (
    clean,
    create_chart_block_from_table,
    locate_block,
    now,
    recompute_chart_block,
    render_chart_assets,
)

# ``mixed`` remains accepted for existing requests, but new business behaviour is
# limited to bar/line/pie in this first refactor stage.
ChartKind = Literal["bar", "line", "pie", "mixed"]


class ChartCreateRequest(BaseModel):
    title_hint: str = Field(default="", max_length=80)
    chart_kind: ChartKind = "bar"
    display_scale: float = Field(default=0.75, ge=0.5, le=1.0)
    illustrative: bool = False


class ChartPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    caption: str | None = Field(default=None, max_length=180)
    display_scale: float | None = Field(default=None, ge=0.5, le=1.0)


class ChartRegenerateRequest(BaseModel):
    chart_kind: ChartKind | None = None
    illustrative: bool = False


def _kind(value: str | None) -> str:
    return value if value in {"bar", "line", "pie"} else "bar"


def _section(draft: dict, section_id: str) -> dict:
    for item in _walk_sections(draft.get("sections") or []):
        if item.get("id") == section_id:
            item.setdefault("paragraphs", [])
            return item
    raise ValueError("未找到目标小节")


def _walk_sections(items: list[dict]):
    for section in items:
        yield section
        children = section.get("children") or section.get("sections") or []
        if isinstance(children, list):
            yield from _walk_sections(children)


def _illustrative_block(chart_id: str, request: ChartCreateRequest) -> dict:
    """Compatibility-only explicit illustrative chart.

    It remains visibly labelled and is never connected to a user data table. The
    normal path always uses ``create_chart_block_from_table``.
    """
    kind = _kind(request.chart_kind)
    categories = ["现状", "方案一", "方案二", "优化后"]
    series = [{"name": "综合指标", "values": [42.0, 58.0, 71.0, 86.0], "axis": "left"}]
    spec = {
        "id": chart_id,
        "schema_version": 2,
        "kind": kind,
        "title": clean(request.title_hint, 100) or "示意性比较图",
        "caption": "示意性模型图，数值仅用于表达比较关系，未核验外部来源。",
        "binding": {"dataset_id": None, "dataset_version": 0, "source_table_id": None, "data_fingerprint": "illustrative"},
        "data": {"categories": categories, "series": series},
        "appearance": {"theme": "academic", "legend": True, "value_labels": kind == "bar"},
        "provenance": {"status": "illustrative", "source_note": "示意数据，不构成研究结论。"},
    }
    if kind == "pie":
        spec["data"]["pie"] = [
            {"name": category, "value": value}
            for category, value in zip(categories, series[0]["values"])
        ]
    return spec


def _asset_from_spec(service, chart_id: str, version: int, spec: dict) -> dict:
    return render_chart_assets(service.task_dir, chart_id, version, spec)


def create_chart_block(service, section_id: str, request: ChartCreateRequest) -> dict:
    with service.lock:
        draft = service.load()
        section = _section(draft, section_id)
        chart_id = "chart_" + uuid.uuid4().hex[:12]
        try:
            block = create_chart_block_from_table(
                draft=draft,
                task_dir=service.task_dir,
                section=section,
                chart_id=chart_id,
                kind=_kind(request.chart_kind),
                title_hint=request.title_hint,
                display_scale=request.display_scale,
            )
        except ValueError:
            if not request.illustrative:
                raise
            spec = _illustrative_block(chart_id, request)
            asset = _asset_from_spec(service, chart_id, 1, spec)
            block = {
                "id": chart_id,
                "type": "chart",
                "status": "ready",
                "version": 1,
                "text": "",
                "title": spec["title"],
                "caption": spec["caption"],
                "chart_spec": spec,
                "chart": {"schema_version": 2, "kind": spec["kind"], "title": spec["title"], "caption": spec["caption"], **spec["data"]},
                "asset": asset,
                "display_scale": request.display_scale,
                "provenance": "illustrative",
                "source_ids": ["illustrative:" + chart_id],
                "generated_at": now(),
            }
        section.setdefault("paragraphs", []).append(block)
        service.save(draft)
        return block


def regenerate_chart_block(service, block_id: str, request: ChartRegenerateRequest) -> dict:
    with service.lock:
        draft = service.load()
        _, block = locate_block(draft, block_id)
        if block.get("type") != "chart":
            raise ValueError("目标内容块不是图表")
        binding = (block.get("chart_spec") or {}).get("binding") or {}
        if binding.get("source_table_id"):
            recompute_chart_block(draft, service.task_dir, block, _kind(request.chart_kind))
        elif request.illustrative:
            create = ChartCreateRequest(
                title_hint=clean(block.get("title"), 80),
                chart_kind=_kind(request.chart_kind or (block.get("chart_spec") or {}).get("kind")),
                display_scale=float(block.get("display_scale") or 0.75),
                illustrative=True,
            )
            spec = _illustrative_block(str(block["id"]), create)
            version = int(block.get("version") or 0) + 1
            block.update({
                "status": "ready",
                "version": version,
                "title": spec["title"],
                "caption": spec["caption"],
                "chart_spec": spec,
                "chart": {"schema_version": 2, "kind": spec["kind"], "title": spec["title"], "caption": spec["caption"], **spec["data"]},
                "asset": _asset_from_spec(service, str(block["id"]), version, spec),
                "stale_reason": None,
                "updated_at": now(),
            })
        else:
            raise ValueError("图表没有可重新计算的数据表绑定")
        service.save(draft)
        return block


def patch_chart_block(service, block_id: str, request: ChartPatchRequest) -> dict:
    with service.lock:
        draft = service.load()
        _, block = locate_block(draft, block_id)
        if block.get("type") != "chart":
            raise ValueError("目标内容块不是图表")
        spec = block.setdefault("chart_spec", {})
        if request.title is not None:
            block["title"] = clean(request.title, 80)
            spec["title"] = block["title"]
        if request.caption is not None:
            block["caption"] = clean(request.caption, 180)
            spec["caption"] = block["caption"]
        if request.display_scale is not None:
            block["display_scale"] = request.display_scale
        # A title/caption is part of the rendered graphic; regenerate the asset
        # from the unchanged binding so editor and DOCX never diverge.
        if request.title is not None or request.caption is not None:
            version = int(block.get("version") or 0) + 1
            block["version"] = version
            block["asset"] = _asset_from_spec(service, str(block["id"]), version, spec)
        compatibility = block.setdefault("chart", {})
        compatibility["title"] = block.get("title", "")
        compatibility["caption"] = block.get("caption", "")
        block["updated_at"] = now()
        service.save(draft)
        return block
