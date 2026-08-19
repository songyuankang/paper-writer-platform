"""Unified chart runtime for draft charts and Visualization Lab.

The persistent contract remains DatasetVersion -> ChartSpec v2 -> ChartAsset.
This module materializes every visual result on the server, so the browser never
calculates final aggregates or stores renderer-library option objects.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

ChartKind = Literal[
    "bar", "line", "pie", "scatter", "area", "boxplot", "histogram", "heatmap", "combo"
]
Aggregation = Literal["none", "count", "sum", "avg", "median", "min", "max"]

SUPPORTED_CHART_KINDS = {
    "bar", "line", "pie", "scatter", "area", "boxplot", "histogram", "heatmap", "combo"
}
SUPPORTED_AGGREGATIONS = {"none", "count", "sum", "avg", "median", "min", "max"}
SUPPORTED_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "in", "between"}

VISUAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "academic": {
        "label": "学术论文",
        "palette": ["#2F5597", "#70AD47", "#ED7D31", "#A5A5A5", "#5B9BD5", "#FFC000"],
        "grid": True,
        "value_labels": False,
        "font_size": 10,
    },
    "cn_thesis": {
        "label": "中文毕业论文",
        "palette": ["#1F4E79", "#548235", "#C55A11", "#7F6000", "#7030A0"],
        "grid": True,
        "value_labels": True,
        "font_size": 10,
    },
    "clean_report": {
        "label": "简洁报告",
        "palette": ["#2563EB", "#14B8A6", "#F97316", "#64748B", "#A855F7"],
        "grid": False,
        "value_labels": False,
        "font_size": 10,
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: object, limit: int = 200) -> str:
    text = re.sub(r"[<>\x00-\x1f]", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def number(value: object) -> float | None:
    try:
        raw = re.sub(r"[^0-9.\-]", "", str(value or ""))
        if not raw:
            return None
        parsed = float(raw)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def walk_sections(items: list[dict[str, Any]]):
    for section in items:
        yield section
        children = section.get("children") or section.get("sections") or []
        if isinstance(children, list):
            yield from walk_sections(children)


def locate_block(draft: dict[str, Any], block_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("id") == block_id:
                return section, block
    raise ValueError("未找到内容块")


def locate_chart(draft: dict[str, Any], chart_id: str) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    """Find a chart in paper paragraphs or the Lab's not-yet-inserted library."""
    for section in walk_sections(draft.get("sections") or []):
        paragraphs = section.get("paragraphs") or []
        for block in paragraphs:
            if block.get("id") == chart_id and block.get("type") == "chart":
                return section, block, paragraphs
    library = draft.get("chart_library") or []
    for block in library:
        if block.get("id") == chart_id and block.get("type") == "chart":
            return None, block, library
    raise ValueError("未找到图表")


def _column_kind(values: list[object]) -> str:
    meaningful = [item for item in values if clean(item)]
    if meaningful and all(number(item) is not None for item in meaningful):
        return "number"
    return "string"


def build_dataset_version(table: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    table_id = clean(table.get("id"), 80)
    if not table_id:
        raise ValueError("数据表缺少稳定 ID")
    headers = [clean(item, 80) for item in (table.get("headers") or [])]
    headers = [item or f"列{index + 1}" for index, item in enumerate(headers)]
    if len(headers) < 2:
        raise ValueError("数据表至少需要两列才能生成图表")
    rows: list[dict[str, str]] = []
    for raw_row in table.get("rows") or []:
        values = list(raw_row) if isinstance(raw_row, list) else []
        rows.append({headers[index]: clean(values[index] if index < len(values) else "", 200) for index in range(len(headers))})
    if not rows:
        raise ValueError("数据表没有可用于图表的行")
    schema = [{
        "name": name,
        "kind": _column_kind([row.get(name, "") for row in rows]),
        "position": index,
    } for index, name in enumerate(headers)]
    fingerprint = _fingerprint({"headers": headers, "rows": rows, "source_table_id": table_id})
    dataset_id = clean((previous or {}).get("id"), 100) or f"dataset_{table_id}"
    version = int((previous or {}).get("version") or 0)
    if (previous or {}).get("fingerprint") != fingerprint:
        version += 1
    return {
        "id": dataset_id,
        "schema_version": 1,
        "source_type": "table_block",
        "source_table_id": table_id,
        "version": max(version, 1),
        "title": clean(table.get("title"), 100) or "数据表",
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "fingerprint": fingerprint,
        "updated_at": now(),
    }


def upsert_table_dataset(draft: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    datasets = draft.setdefault("datasets", [])
    if not isinstance(datasets, list):
        datasets = []
        draft["datasets"] = datasets
    old = next((item for item in datasets if item.get("source_table_id") == table.get("id")), None)
    dataset = build_dataset_version(table, old)
    if old is None:
        datasets.append(dataset)
    else:
        datasets[datasets.index(old)] = dataset
    table["dataset_id"] = dataset["id"]
    table["dataset_version"] = dataset["version"]
    table["dataset_fingerprint"] = dataset["fingerprint"]
    return dataset


def dataset_for_table(draft: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    return upsert_table_dataset(draft, table)


def external_dataset_version(version: dict[str, Any]) -> dict[str, Any]:
    """Adapt a file-backed research DatasetVersion to the existing renderer input.

    Rows are loaded only by the backend service. The returned object is ephemeral
    and is never copied into draft.json.
    """
    schema = []
    for index, column in enumerate(version.get("schema") or []):
        column_type = str(column.get("type") or column.get("kind") or "text")
        schema.append({
            "name": column.get("name"), "kind": "number" if column_type == "numeric" else "string",
            "position": index, "dataset_type": column_type,
        })
    return {
        "id": version["dataset_id"], "schema_version": 1, "source_type": "research_dataset",
        "source_table_id": None, "version": version["version"],
        "title": version.get("dataset_name") or "研究数据集", "schema": schema,
        "rows": version.get("rows") or [], "row_count": version.get("row_count", 0),
        "fingerprint": version["fingerprint"], "updated_at": version.get("created_at"),
    }


def dataset_by_id(draft: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    dataset = next((item for item in draft.get("datasets") or [] if item.get("id") == dataset_id), None)
    if dataset is None:
        raise ValueError("未找到数据集")
    return dataset


def dataset_profile(dataset: dict[str, Any], limit: int = 50, offset: int = 0) -> dict[str, Any]:
    rows = list(dataset.get("rows") or [])
    fields: list[dict[str, Any]] = []
    for column in dataset.get("schema") or []:
        name = column["name"]
        values = [row.get(name, "") for row in rows]
        missing = sum(1 for value in values if not clean(value))
        unique = len({clean(value) for value in values if clean(value)})
        item: dict[str, Any] = {**column, "missing_count": missing, "unique_count": unique}
        numeric = [number(value) for value in values]
        numeric = [value for value in numeric if value is not None]
        if column.get("kind") == "number" and numeric:
            item["statistics"] = {
                "min": min(numeric), "max": max(numeric), "avg": sum(numeric) / len(numeric),
                "median": statistics.median(numeric),
            }
        fields.append(item)
    safe_offset = max(0, offset)
    safe_limit = min(max(1, limit), 200)
    return {
        "dataset": {key: dataset.get(key) for key in ("id", "title", "version", "row_count", "source_table_id", "fingerprint")},
        "fields": fields,
        "rows": rows[safe_offset:safe_offset + safe_limit],
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": safe_offset + safe_limit < len(rows),
    }


def _names(dataset: dict[str, Any]) -> set[str]:
    return {str(item.get("name")) for item in dataset.get("schema") or []}


def _numeric_columns(dataset: dict[str, Any]) -> list[str]:
    return [str(item["name"]) for item in dataset.get("schema") or [] if item.get("position", 0) > 0 and item.get("kind") == "number"]


def normalize_binding(dataset: dict[str, Any], raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or {}
    schema = dataset.get("schema") or []
    if len(schema) < 2:
        raise ValueError("数据集至少需要两列")
    names = _names(dataset)
    category = raw.get("category_column") if raw.get("category_column") in names else schema[0]["name"]
    requested = raw.get("measure_columns") or []
    measures = [str(value) for value in requested if str(value) in names and str(value) in _numeric_columns(dataset)]
    measures = measures or _numeric_columns(dataset)
    if not measures:
        raise ValueError("数据集没有可用于图表的数值列")
    series_column = raw.get("series_column")
    if series_column not in names or series_column == category or series_column in measures:
        series_column = None
    aggregation = str(raw.get("aggregation") or "none")
    if aggregation not in SUPPORTED_AGGREGATIONS:
        aggregation = "none"
    filters = []
    for condition in raw.get("filters") or []:
        column = str(condition.get("column") or "")
        operator = str(condition.get("operator") or "")
        if column in names and operator in SUPPORTED_FILTER_OPERATORS:
            filters.append({"column": column, "operator": operator, "value": condition.get("value")})
    return {
        "dataset_id": dataset["id"],
        "dataset_version": dataset["version"],
        "source_type": dataset.get("source_type", "table_block"),
        "source_table_id": dataset.get("source_table_id"),
        "category_column": category,
        "measure_columns": measures[:6],
        "series_column": series_column,
        "aggregation": aggregation,
        "filters": filters,
        "data_fingerprint": dataset["fingerprint"],
    }


def _filter_match(raw: object, condition: dict[str, Any]) -> bool:
    operator = condition["operator"]
    value = condition.get("value")
    actual_text = clean(raw, 200)
    if operator == "in":
        values = value if isinstance(value, list) else str(value or "").split(",")
        return actual_text in {clean(item, 200) for item in values}
    if operator == "between":
        values = value if isinstance(value, list) else []
        if len(values) != 2:
            return False
        actual, low, high = number(raw), number(values[0]), number(values[1])
        return actual is not None and low is not None and high is not None and low <= actual <= high
    if operator in {">", "<", ">=", "<="}:
        actual, expected = number(raw), number(value)
        if actual is None or expected is None:
            return False
        return {">": actual > expected, "<": actual < expected, ">=": actual >= expected, "<=": actual <= expected}[operator]
    expected = clean(value, 200)
    return actual_text == expected if operator == "=" else actual_text != expected


def filtered_rows(dataset: dict[str, Any], binding: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(dataset.get("rows") or [])
    for condition in binding.get("filters") or []:
        rows = [row for row in rows if _filter_match(row.get(condition["column"]), condition)]
    return rows


def _aggregate(values: list[float], method: str) -> float:
    if not values:
        return 0.0
    if method == "count":
        return float(len(values))
    if method == "sum":
        return float(sum(values))
    if method == "avg":
        return float(sum(values) / len(values))
    if method == "median":
        return float(statistics.median(values))
    if method == "min":
        return float(min(values))
    if method == "max":
        return float(max(values))
    return float(values[-1])


def materialize_chart_data(dataset: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Apply server-side filters, group fields and aggregation to a ChartSpec payload."""
    rows = filtered_rows(dataset, binding)
    category_column = binding["category_column"]
    measures = binding["measure_columns"]
    series_column = binding.get("series_column")
    aggregation = binding.get("aggregation", "none")
    categories: OrderedDict[str, None] = OrderedDict()
    buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    groups: OrderedDict[str, None] = OrderedDict()
    for row in rows:
        category = clean(row.get(category_column), 60)
        if not category:
            continue
        categories[category] = None
        group = clean(row.get(series_column), 60) if series_column else ""
        groups[group] = None
        for measure in measures:
            value = number(row.get(measure))
            if value is not None:
                buckets[(category, group, measure)].append(value)
    category_list = list(categories)
    if len(category_list) < 1:
        raise ValueError("筛选后没有可用于图表的数据")
    series: list[dict[str, Any]] = []
    effective_groups = list(groups) if series_column else [""]
    for measure_index, measure in enumerate(measures):
        for group_index, group in enumerate(effective_groups):
            values = [_aggregate(buckets[(category, group, measure)], aggregation) for category in category_list]
            label = measure if not series_column else f"{measure} · {group or '未分组'}"
            series.append({"name": label, "values": values, "axis": "left" if measure_index == 0 else "right", "group": group or None})
    payload: dict[str, Any] = {"categories": category_list, "series": series, "row_count": len(rows)}
    return payload


def normalize_appearance(raw: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    raw = raw or {}
    template_id = str(raw.get("template") or raw.get("theme") or "academic")
    if template_id not in VISUAL_TEMPLATES:
        template_id = "academic"
    base = VISUAL_TEMPLATES[template_id]
    return {
        "template": template_id,
        "theme": template_id,
        "legend": bool(raw.get("legend", True)),
        "value_labels": bool(raw.get("value_labels", base["value_labels"])),
        "grid": bool(raw.get("grid", base["grid"])),
        "palette": list(raw.get("palette") or base["palette"]),
        "font_size": int(raw.get("font_size") or base["font_size"]),
        "x_label": clean(raw.get("x_label"), 80),
        "y_label": clean(raw.get("y_label"), 80),
        "title_position": "top",
        "kind": kind,
    }


def chart_spec_from_dataset(
    dataset: dict[str, Any], chart_id: str, kind: str, title_hint: str = "",
    binding: dict[str, Any] | None = None, appearance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_kind = kind if kind in SUPPORTED_CHART_KINDS else "bar"
    binding = normalize_binding(dataset, binding)
    data = materialize_chart_data(dataset, binding)
    binding["data_fingerprint"] = _fingerprint({"dataset": dataset["fingerprint"], "binding": binding, "data": data})
    title = clean(title_hint, 100) or f"{dataset.get('title') or '数据表'}关键指标对比"
    spec: dict[str, Any] = {
        "id": chart_id,
        "schema_version": 2,
        "kind": safe_kind,
        "title": title,
        "caption": "基于论文中用户维护的数据表自动生成。",
        "binding": binding,
        "data": data,
        "appearance": normalize_appearance(appearance, safe_kind),
        "provenance": {"status": "user_provided", "source_note": "数据来源：研究数据集。" if dataset.get("source_type") == "research_dataset" else "数据来源：论文内用户维护的数据表。"},
    }
    if safe_kind == "pie":
        first = data["series"][0] if data["series"] else {"values": []}
        spec["data"]["pie"] = [{"name": category, "value": value} for category, value in zip(data["categories"], first["values"])]
    return spec


def _setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _x_values(categories: list[str]) -> tuple[list[float], list[str] | None]:
    numeric = [number(value) for value in categories]
    if categories and all(value is not None for value in numeric):
        return [float(value) for value in numeric if value is not None], None
    return list(range(len(categories))), categories


def _draw_chart(spec: dict[str, Any], destination: Path, output_format: str) -> None:
    plt = _setup_matplotlib()
    appearance = spec.get("appearance") or {}
    colors = appearance.get("palette") or VISUAL_TEMPLATES["academic"]["palette"]
    kind = spec.get("kind", "bar")
    data = spec.get("data") or {}
    categories = [str(value) for value in data.get("categories") or []]
    series = data.get("series") or []
    fig, ax = plt.subplots(figsize=(8.8, 5.0), dpi=180)
    if kind == "pie":
        pie = data.get("pie") or []
        values = [max(float(item.get("value") or 0), 0) for item in pie]
        if not any(values):
            raise ValueError("饼图没有大于零的数据")
        ax.pie(values, labels=[str(item.get("name") or "") for item in pie], autopct="%.1f%%", startangle=90, colors=colors)
        ax.axis("equal")
    elif kind == "heatmap":
        matrix = [[float(value) for value in item.get("values") or []] for item in series]
        image = ax.imshow(matrix, aspect="auto", cmap="Blues")
        ax.set_xticks(range(len(categories)), categories)
        ax.set_yticks(range(len(series)), [str(item.get("name") or "指标") for item in series])
        fig.colorbar(image, ax=ax, fraction=.046, pad=.04)
        for row, values in enumerate(matrix):
            for column, value in enumerate(values):
                ax.text(column, row, f"{value:.2g}", ha="center", va="center", fontsize=8)
    elif kind == "boxplot":
        ax.boxplot([item.get("values") or [] for item in series], tick_labels=[str(item.get("name") or "指标") for item in series], patch_artist=True)
        for patch, color in zip(ax.patches, colors * max(1, len(series))):
            patch.set_facecolor(color)
    elif kind == "histogram":
        for index, item in enumerate(series):
            ax.hist(item.get("values") or [], bins="auto", alpha=.62, color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
    else:
        x, tick_labels = _x_values(categories)
        if kind == "scatter":
            for index, item in enumerate(series):
                ax.scatter(x, item.get("values") or [], color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
        elif kind == "area":
            for index, item in enumerate(series):
                values = item.get("values") or []
                ax.fill_between(x, values, alpha=.35, color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
                ax.plot(x, values, color=colors[index % len(colors)], linewidth=2)
        elif kind == "line":
            for index, item in enumerate(series):
                ax.plot(x, item.get("values") or [], marker="o", linewidth=2, color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
        elif kind == "combo":
            group_width = .72 / max(len(series), 1)
            for index, item in enumerate(series):
                if index == 0:
                    bars = ax.bar([value - .18 for value in x], item.get("values") or [], .36, color=colors[0], label=str(item.get("name") or "指标"))
                    if appearance.get("value_labels"):
                        ax.bar_label(bars, fmt="%.2g", fontsize=8, padding=2)
                else:
                    ax.plot(x, item.get("values") or [], marker="o", linewidth=2, color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
        else:  # bar
            group_width = .76 / max(len(series), 1)
            for index, item in enumerate(series):
                shift = (index - (len(series) - 1) / 2) * group_width
                bars = ax.bar([value + shift for value in x], item.get("values") or [], group_width * .9, color=colors[index % len(colors)], label=str(item.get("name") or "指标"))
                if appearance.get("value_labels"):
                    ax.bar_label(bars, fmt="%.2g", fontsize=8, padding=2)
        if tick_labels is not None:
            ax.set_xticks(x, tick_labels)
        if appearance.get("grid"):
            ax.grid(axis="y", linestyle="--", alpha=.3)
        if appearance.get("legend") and len(series) > 1:
            ax.legend(frameon=False)
        if appearance.get("x_label"):
            ax.set_xlabel(appearance["x_label"])
        if appearance.get("y_label"):
            ax.set_ylabel(appearance["y_label"])
    ax.set_title(str(spec.get("title") or "图表"), fontsize=13, fontweight="bold", pad=14)
    fig.tight_layout()
    fig.savefig(destination, format=output_format, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_chart_assets(task_dir: Path, chart_id: str, version: int, spec: dict[str, Any]) -> dict[str, Any]:
    charts_dir = task_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{chart_id}_v{version}"
    svg_rel, png_rel = f"charts/{stem}.svg", f"charts/{stem}.png"
    _draw_chart(spec, task_dir / svg_rel, "svg")
    _draw_chart(spec, task_dir / png_rel, "png")
    return {
        "id": f"asset_{chart_id}_v{version}", "schema_version": 1,
        "png_path": png_rel, "svg_path": svg_rel,
        "data_fingerprint": spec.get("binding", {}).get("data_fingerprint", ""),
        "template": (spec.get("appearance") or {}).get("template", "academic"),
        "generated_at": now(),
    }


def _all_chart_blocks(draft: dict[str, Any]):
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("type") == "chart":
                yield block
    for block in draft.get("chart_library") or []:
        if block.get("type") == "chart":
            yield block


def mark_charts_stale_for_table(draft: dict[str, Any], table_id: str) -> list[str]:
    changed = []
    for block in _all_chart_blocks(draft):
        binding = (block.get("chart_spec") or {}).get("binding") or {}
        if binding.get("source_table_id") == table_id or table_id in (block.get("source_ids") or []):
            block.update(status="stale", stale_reason="关联数据表已修改，请重新计算图表。", updated_at=now())
            changed.append(str(block.get("id")))
    return changed


def _compatibility_chart(spec: dict[str, Any]) -> dict[str, Any]:
    data = spec.get("data") or {}
    return {"schema_version": 2, "kind": spec["kind"], "title": spec["title"], "caption": spec["caption"], **data}


def resolve_bound_dataset(draft: dict[str, Any], binding: dict[str, Any], dataset_loader: Callable[[str, int | None], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve either a task-local TableBlock dataset or a file-backed DatasetVersion."""
    if binding.get("source_type") == "research_dataset":
        if dataset_loader is None:
            raise ValueError("研究数据集需要由数据中心服务加载")
        dataset_id = str(binding.get("dataset_id") or "")
        if not dataset_id:
            raise ValueError("图表没有研究数据集绑定")
        version = binding.get("dataset_version")
        return external_dataset_version(dataset_loader(dataset_id, int(version) if version else None))
    table_id = binding.get("source_table_id")
    if not table_id:
        raise ValueError("图表没有可用的数据源绑定")
    _, table = locate_block(draft, str(table_id))
    if table.get("type") != "table":
        raise ValueError("图表绑定的数据表已不存在")
    return upsert_table_dataset(draft, table)


def _source_ids(dataset: dict[str, Any]) -> list[str]:
    return [str(dataset["source_table_id"])] if dataset.get("source_table_id") else []


def recompute_chart_block(draft: dict[str, Any], task_dir: Path, block: dict[str, Any], kind: str | None = None, dataset_loader: Callable[[str, int | None], dict[str, Any]] | None = None) -> dict[str, Any]:
    old_spec = block.get("chart_spec") or {}
    old_binding = dict(old_spec.get("binding") or {})
    if not old_binding.get("source_table_id") and (block.get("source_ids") or []):
        old_binding["source_table_id"] = (block.get("source_ids") or [None])[0]
    dataset = resolve_bound_dataset(draft, old_binding, dataset_loader)
    chart_id = str(block.get("id") or "")
    if not chart_id:
        raise ValueError("图表缺少稳定 ID")
    spec = chart_spec_from_dataset(
        dataset, chart_id, kind or old_spec.get("kind") or "bar", clean(block.get("title"), 100),
        old_binding, old_spec.get("appearance"),
    )
    if block.get("caption"):
        spec["caption"] = clean(block["caption"], 180)
    version = int(block.get("version") or 0) + 1
    asset = render_chart_assets(task_dir, chart_id, version, spec)
    block.update({
        "status": "ready", "version": version, "title": spec["title"], "caption": spec["caption"],
        "chart_spec": spec, "chart": _compatibility_chart(spec), "asset": asset,
        "source_ids": _source_ids(dataset), "provenance": "user_provided",
        "stale_reason": None, "updated_at": now(),
    })
    return block


def update_chart_configuration(draft: dict[str, Any], task_dir: Path, chart_id: str, patch: dict[str, Any], dataset_loader: Callable[[str, int | None], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Update ChartSpec and render a new asset from either supported Dataset source."""
    _, block, _ = locate_chart(draft, chart_id)
    old = block.get("chart_spec") or {}
    binding = dict(old.get("binding") or {})
    binding.update(patch.get("binding") or {})
    if not binding.get("source_type") and binding.get("source_table_id"):
        binding["source_type"] = "table_block"
    if not binding.get("source_table_id") and (block.get("source_ids") or []) and binding.get("source_type") != "research_dataset":
        binding["source_table_id"] = (block.get("source_ids") or [None])[0]
    dataset = resolve_bound_dataset(draft, binding, dataset_loader)
    appearance = dict(old.get("appearance") or {})
    appearance.update(patch.get("appearance") or {})
    title = clean(patch.get("title") if patch.get("title") is not None else block.get("title"), 100)
    spec = chart_spec_from_dataset(dataset, chart_id, patch.get("kind") or old.get("kind") or "bar", title, binding, appearance)
    caption = patch.get("caption") if patch.get("caption") is not None else block.get("caption")
    if caption:
        spec["caption"] = clean(caption, 180)
    version = int(block.get("version") or 0) + 1
    block.update({
        "status": "ready", "version": version, "title": spec["title"], "caption": spec["caption"],
        "chart_spec": spec, "chart": _compatibility_chart(spec), "asset": render_chart_assets(task_dir, chart_id, version, spec),
        "source_ids": _source_ids(dataset), "stale_reason": None, "updated_at": now(),
    })
    return block


def create_chart_block_from_table(draft: dict[str, Any], task_dir: Path, section: dict[str, Any], chart_id: str, kind: str, title_hint: str, display_scale: float, table_id: str | None = None, inserted: bool = True) -> dict[str, Any]:
    table = None
    for candidate in section.get("paragraphs") or []:
        if candidate.get("type") == "table" and (not table_id or candidate.get("id") == table_id):
            table = candidate
            break
    if table is None:
        raise ValueError("未找到可用于定量图表的数据表")
    dataset = upsert_table_dataset(draft, table)
    spec = chart_spec_from_dataset(dataset, chart_id, kind, title_hint)
    block = {
        "id": chart_id, "type": "chart", "status": "ready", "version": 1, "text": "",
        "title": spec["title"], "caption": spec["caption"], "chart_spec": spec,
        "chart": _compatibility_chart(spec), "asset": render_chart_assets(task_dir, chart_id, 1, spec),
        "display_scale": display_scale, "provenance": "user_provided", "source_ids": _source_ids(dataset),
        "in_paper": inserted, "generated_at": now(),
    }
    return block


def create_chart_block_from_dataset(task_dir: Path, dataset: dict[str, Any], chart_id: str, kind: str, title_hint: str = "", display_scale: float = .75, inserted: bool = False) -> dict[str, Any]:
    """Create a chart from an already loaded independent DatasetVersion."""
    spec = chart_spec_from_dataset(dataset, chart_id, kind, title_hint)
    return {
        "id": chart_id, "type": "chart", "status": "ready", "version": 1, "text": "",
        "title": spec["title"], "caption": spec["caption"], "chart_spec": spec,
        "chart": _compatibility_chart(spec), "asset": render_chart_assets(task_dir, chart_id, 1, spec),
        "display_scale": display_scale, "provenance": "user_provided", "source_ids": [],
        "in_paper": inserted, "generated_at": now(),
    }


def create_lab_chart(draft: dict[str, Any], task_dir: Path, chart_id: str, table_id: str, title_hint: str = "", kind: str = "bar") -> dict[str, Any]:
    section, table = locate_block(draft, table_id)
    if table.get("type") != "table":
        raise ValueError("请选择论文中的数据表")
    block = create_chart_block_from_table(draft, task_dir, section, chart_id, kind, title_hint, .75, table_id, inserted=False)
    draft.setdefault("chart_library", []).append(block)
    return block


def create_lab_chart_from_dataset(draft: dict[str, Any], task_dir: Path, chart_id: str, dataset: dict[str, Any], title_hint: str = "", kind: str = "bar") -> dict[str, Any]:
    block = create_chart_block_from_dataset(task_dir, dataset, chart_id, kind, title_hint, inserted=False)
    draft.setdefault("chart_library", []).append(block)
    return block


def insert_chart_into_section(draft: dict[str, Any], chart_id: str, section_id: str) -> dict[str, Any]:
    target = next((item for item in walk_sections(draft.get("sections") or []) if item.get("id") == section_id), None)
    if target is None:
        raise ValueError("未找到插入目标小节")
    current_section, block, container = locate_chart(draft, chart_id)
    if current_section is not None and current_section.get("id") == section_id:
        block["in_paper"] = True
        return block
    container.remove(block)
    target.setdefault("paragraphs", []).append(block)
    block["in_paper"] = True
    block["inserted_section_id"] = section_id
    block["updated_at"] = now()
    return block


def adapt_insight_chart(draft: dict[str, Any], task_dir: Path, insight_id: str) -> dict[str, Any]:
    """Compatibility adapter for legacy ``insight.chart`` data.

    When the legacy insight points to a TableBlock we retain its binding and use
    the single renderer. Otherwise a small synthetic dataset is persisted solely
    for backward-compatible rendering; it is explicitly marked as synthesized.
    """
    section, insight = locate_block(draft, insight_id)
    if insight.get("type") != "insight" or insight.get("kind") != "chart":
        raise ValueError("目标内容块不是洞察图表")
    legacy = insight.get("chart") or {}
    table_id = legacy.get("source_table_id")
    if table_id:
        _, table = locate_block(draft, str(table_id))
        dataset = upsert_table_dataset(draft, table)
    else:
        categories = legacy.get("categories") or [item.get("name") for item in legacy.get("pie") or []]
        series = legacy.get("series") or []
        if legacy.get("pie") and not series:
            series = [{"name": "数值", "values": [item.get("value") for item in legacy.get("pie") or []]}]
        rows = [{"类别": clean(category), **{clean(item.get("name"), 60) or "数值": str((item.get("values") or [])[index] if index < len(item.get("values") or []) else "") for item in series}} for index, category in enumerate(categories)]
        table = {"id": f"insight_source_{insight_id}", "type": "table", "title": insight.get("title") or "洞察图表数据", "headers": ["类别"] + [clean(item.get("name"), 60) or "数值" for item in series], "rows": [[row.get(key, "") for key in ["类别"] + [clean(item.get("name"), 60) or "数值" for item in series]] for row in rows]}
        dataset = upsert_table_dataset(draft, table)
        dataset["source_type"] = "insight_adapter"
    spec = chart_spec_from_dataset(dataset, insight_id, legacy.get("kind") or "bar", insight.get("title") or "洞察图表")
    spec["provenance"] = {"status": insight.get("source_status") or "text_synthesis", "source_note": "由洞察图表适配器生成。"}
    version = int(insight.get("version") or 0) + 1
    legacy_metadata = {
        "kind": insight.get("kind"), "scope": insight.get("scope"),
        "source_status": insight.get("source_status"), "evidence": insight.get("evidence") or [],
    }
    insight.update({
        "type": "chart", "status": "ready", "version": version, "text": "",
        "title": spec["title"], "caption": spec["caption"], "chart_spec": spec,
        "chart": _compatibility_chart(spec), "asset": render_chart_assets(task_dir, insight_id, version, spec),
        "source_ids": [dataset.get("source_table_id")], "provenance": spec["provenance"]["status"],
        "legacy_insight": legacy_metadata,
        "chart_adapter": {"schema_version": 1, "adapted_at": now(), "source_table_id": dataset.get("source_table_id")},
        "updated_at": now(),
    })
    return insight


def figure_sections_for_draft(draft: dict[str, Any]) -> dict[str, str]:
    numbers: dict[str, str] = {}
    index = 0
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("type") != "chart" or block.get("status") != "ready":
                continue
            if not (block.get("asset") or {}).get("png_path"):
                continue
            index += 1
            number_label = f"图{index}"
            block["figure_number"] = number_label
            numbers[str(block.get("id"))] = number_label
    return numbers
