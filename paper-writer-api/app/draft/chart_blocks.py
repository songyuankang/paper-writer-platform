"""Chart block API adapters for the draft editor.

The business implementation lives in :mod:`chart_runtime`: TableBlock data is
versioned, a renderer-neutral ChartSpec is created, and PNG/SVG assets are
persisted before the block is returned to the UI.
"""
from __future__ import annotations

import copy
import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.draft.chart_runtime import (
    clean,
    create_chart_block_from_table,
    locate_block,
    now,
    normalize_appearance,
    recompute_chart_block,
    render_chart_assets,
)
from app.draft.chart_versions import bootstrap_chart_version, commit_chart_version

# ``mixed`` remains a legacy alias; all current kinds are rendered by the
# single ChartRenderer in chart_runtime.
ChartKind = Literal["bar", "line", "pie", "scatter", "area", "boxplot", "histogram", "heatmap", "combo", "mixed"]


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


class AIChartRegenerateRequest(BaseModel):
    confirmed: bool = False
    chart_kind: ChartKind | None = None
    candidate_chart_spec: dict[str, Any] | None = None


class ChartSpecUpdateRequest(BaseModel):
    """正文内编辑器提交的完整 ChartSpec v2。

    ResearchObject 编号、数据绑定和来源快照由既有领域对象维护，正文
    编辑器只能修改图表语义数据及可视化外观，避免破坏交叉引用和血缘关系。
    """

    chart_spec: dict[str, Any]


def _kind(value: str | None) -> str:
    if value == "mixed":
        return "combo"
    return value if value in {"bar", "line", "pie", "scatter", "area", "boxplot", "histogram", "heatmap", "combo"} else "bar"


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


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field} 必须是有限数值")
    return float(value)


def _label(value: Any, field: str, limit: int = 100) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是文本")
    cleaned = clean(value, limit)
    if not cleaned:
        raise ValueError(f"{field} 不能为空")
    return cleaned


def _manual_chart_spec(block: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Validate editable ChartSpec fields while preserving protected provenance.

    The browser may edit the complete JSON document in advanced mode, but changes
    to ``id``/``binding``/``provenance`` are rejected rather than silently
    disconnecting an existing FigureBlock from its Dataset/Evidence lineage.
    """
    old = dict(block.get("chart_spec") or {})
    if not isinstance(raw, dict):
        raise ValueError("chart_spec 必须是对象")
    if raw.get("schema_version") != 2:
        raise ValueError("仅支持 schema_version 为 2 的 ChartSpec")
    chart_id = str(block.get("id") or "")
    if raw.get("id") not in {None, chart_id}:
        raise ValueError("ChartSpec 的 id 必须与当前图表一致")
    old_binding = old.get("binding") or {}
    old_provenance = old.get("provenance") or {}
    if "binding" in raw and raw.get("binding") != old_binding:
        raise ValueError("数据绑定由既有数据追踪保护，当前正文编辑器不可修改")
    if "provenance" in raw and raw.get("provenance") != old_provenance:
        raise ValueError("来源追踪由既有研究对象保护，当前正文编辑器不可修改")

    kind = _kind(raw.get("kind"))
    if raw.get("kind") not in {"bar", "line", "pie", "scatter", "area", "boxplot", "histogram", "heatmap", "combo", "mixed"}:
        raise ValueError("不支持的图表类型")
    data = raw.get("data")
    if not isinstance(data, dict):
        raise ValueError("chart_spec.data 必须是对象")

    categories = data.get("categories")
    series = data.get("series")
    if kind == "pie":
        pie = data.get("pie")
        if not isinstance(pie, list) or not (1 <= len(pie) <= 80):
            raise ValueError("饼图需要 1 至 80 个数据项")
        normalized_pie = []
        for index, item in enumerate(pie):
            if not isinstance(item, dict):
                raise ValueError("饼图数据项必须是对象")
            normalized_pie.append({
                "name": _label(item.get("name"), f"第 {index + 1} 个类别", 80),
                "value": _finite_number(item.get("value"), f"第 {index + 1} 个数值"),
            })
        normalized_categories = [item["name"] for item in normalized_pie]
        normalized_series = [{"name": "数值", "values": [item["value"] for item in normalized_pie], "axis": "left"}]
        normalized_data = {"categories": normalized_categories, "series": normalized_series, "pie": normalized_pie}
    else:
        if not isinstance(categories, list) or not (1 <= len(categories) <= 80):
            raise ValueError("类别必须为 1 至 80 项的数组")
        if not isinstance(series, list) or not (1 <= len(series) <= 8):
            raise ValueError("系列必须为 1 至 8 项的数组")
        normalized_categories = [_label(item, f"第 {index + 1} 个类别", 80) for index, item in enumerate(categories)]
        normalized_series = []
        for index, item in enumerate(series):
            if not isinstance(item, dict):
                raise ValueError("系列必须是对象")
            values = item.get("values")
            if not isinstance(values, list) or len(values) != len(normalized_categories):
                raise ValueError("每个系列的数值数量必须与类别数量一致")
            axis = item.get("axis", "left")
            if axis not in {"left", "right"}:
                raise ValueError("系列坐标轴只能为 left 或 right")
            normalized_series.append({
                "name": _label(item.get("name"), f"第 {index + 1} 个系列名称", 80),
                "values": [_finite_number(value, f"第 {index + 1} 个系列数值") for value in values],
                "axis": axis,
            })
        normalized_data = {"categories": normalized_categories, "series": normalized_series}

    title = _label(raw.get("title", block.get("title") or "图表"), "图表标题")
    caption_raw = raw.get("caption", block.get("caption") or "")
    if not isinstance(caption_raw, str):
        raise ValueError("图注必须是文本")
    appearance = normalize_appearance(raw.get("appearance") if isinstance(raw.get("appearance"), dict) else old.get("appearance"), kind)
    return {
        "id": chart_id,
        "schema_version": 2,
        "kind": kind,
        "title": title,
        "caption": clean(caption_raw, 180),
        "binding": old_binding,
        "data": normalized_data,
        "appearance": appearance,
        "provenance": old_provenance,
    }


def update_chart_spec_block(service, block_id: str, request: ChartSpecUpdateRequest) -> dict:
    """Persist a manual ChartSpec edit and regenerate the existing ChartAsset.

    The FigureBlock ID and formal figure number remain untouched, so all existing
    ResearchObject/CrossReference records continue to resolve to this same block.
    """
    with service.lock:
        draft = service.load()
        before_draft = copy.deepcopy(draft)
        _, block = locate_block(draft, block_id)
        if block.get("type") != "chart":
            raise ValueError("目标内容块不是图表")
        previous_block = copy.deepcopy(block)
        spec = _manual_chart_spec(block, request.chart_spec)
        version = int(block.get("version") or 0) + 1
        block.update({
            "status": "ready",
            "version": version,
            "title": spec["title"],
            "caption": spec["caption"],
            "chart_spec": spec,
            "chart": {"schema_version": 2, "kind": spec["kind"], "title": spec["title"], "caption": spec["caption"], **spec["data"]},
            "asset": _asset_from_spec(service, str(block["id"]), version, spec),
            "manual_data_override": True,
            "stale_reason": None,
            "updated_at": now(),
        })
        commit_chart_version(
            service, draft, before_draft, block, previous_block,
            editor={"type": "user", "name": "用户"}, reason="user_edit",
        )
        return block


def ai_chart_candidate(service, block_id: str, request: AIChartRegenerateRequest) -> dict[str, Any]:
    """Return or explicitly confirm an AI-proposed ChartSpec without source mutation.

    The current task has no authority to let an AI alter provenance. The candidate
    is therefore a structured proposal based only on the FigureBlock's existing
    ChartSpec, binding and Evidence snapshot; it is persisted only after the
    caller sends ``confirmed=True``.
    """
    with service.lock:
        draft = service.load()
        _, block = locate_block(draft, block_id)
        if block.get("type") != "chart":
            raise ValueError("目标内容块不是图表")
        current = copy.deepcopy(block.get("chart_spec") or {})
        if not current:
            raise ValueError("图表缺少可供 AI 生成的 ChartSpec")
        if request.candidate_chart_spec is not None:
            candidate = request.candidate_chart_spec
        else:
            candidate = current
            if request.chart_kind:
                candidate["kind"] = _kind(request.chart_kind)
        # Enforce the same protected binding/provenance checks at preview time.
        candidate = _manual_chart_spec(block, candidate)
        if not request.confirmed:
            return {"requires_confirmation": True, "candidate_chart_spec": candidate, "message": "AI 候选仅使用当前已绑定的数据和来源；确认后才创建新版本。"}

        before_draft = copy.deepcopy(draft)
        previous_block = copy.deepcopy(block)
        render_version = int(block.get("version") or 0) + 1
        block.update({
            "status": "ready",
            "version": render_version,
            "title": candidate["title"],
            "caption": candidate["caption"],
            "chart_spec": candidate,
            "chart": {"schema_version": 2, "kind": candidate["kind"], "title": candidate["title"], "caption": candidate["caption"], **candidate["data"]},
            "asset": _asset_from_spec(service, str(block["id"]), render_version, candidate),
            "stale_reason": None,
            "updated_at": now(),
        })
        commit_chart_version(
            service, draft, before_draft, block, previous_block,
            editor={"type": "ai", "name": "AI（已确认候选）"}, reason="ai_regenerate",
        )
        return {"requires_confirmation": False, "block": block, "message": "已根据确认的 AI 候选创建新图表版本。"}


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
        before_draft = copy.deepcopy(draft)
        section.setdefault("paragraphs", []).append(block)
        bootstrap_chart_version(service, draft, block, before_draft)
        return block


def regenerate_chart_block(service, block_id: str, request: ChartRegenerateRequest) -> dict:
    with service.lock:
        draft = service.load()
        before_draft = copy.deepcopy(draft)
        _, block = locate_block(draft, block_id)
        previous_block = copy.deepcopy(block)
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
        commit_chart_version(
            service, draft, before_draft, block, previous_block,
            editor={"type": "system", "name": "系统重新计算"}, reason="recompute",
        )
        return block


def patch_chart_block(service, block_id: str, request: ChartPatchRequest) -> dict:
    with service.lock:
        draft = service.load()
        before_draft = copy.deepcopy(draft)
        _, block = locate_block(draft, block_id)
        previous_block = copy.deepcopy(block)
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
        if request.title is not None or request.caption is not None:
            commit_chart_version(
                service, draft, before_draft, block, previous_block,
                editor={"type": "user", "name": "用户"}, reason="user_edit",
            )
        else:
            service.save(draft)
        return block
