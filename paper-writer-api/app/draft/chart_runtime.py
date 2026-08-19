"""Draft chart domain runtime.

This module owns the minimum reproducible chart pipeline used by the draft editor:
TableBlock -> DatasetVersion -> ChartSpec -> PNG/SVG ChartAsset -> FigureBlock.

It deliberately stores a renderer-neutral business specification rather than a
browser-library option object.  The same ChartSpec is used for the editor preview,
asset generation and DOCX export.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ChartKind = Literal["bar", "line", "pie"]


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


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _column_kind(values: list[object]) -> str:
    meaningful = [item for item in values if clean(item)]
    if meaningful and all(number(item) is not None for item in meaningful):
        return "number"
    return "string"


def build_dataset_version(table: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a structured DatasetVersion from one editable TableBlock.

    Dataset ids are stable for the lifetime of a table; versions increase only when
    the normalized table content changes.  Rows remain JSON in the task draft for
    the first implementation phase, which keeps task bundles self-contained.
    """
    table_id = clean(table.get("id"), 80)
    if not table_id:
        raise ValueError("数据表缺少稳定 ID")
    headers = [clean(item, 80) for item in (table.get("headers") or [])]
    headers = [item or f"列{index + 1}" for index, item in enumerate(headers)]
    if len(headers) < 2:
        raise ValueError("数据表至少需要两列才能生成图表")
    rows = []
    for raw_row in table.get("rows") or []:
        values = list(raw_row) if isinstance(raw_row, list) else []
        rows.append({headers[index]: clean(values[index] if index < len(values) else "", 200) for index in range(len(headers))})
    if not rows:
        raise ValueError("数据表没有可用于图表的行")
    schema = [
        {
            "name": name,
            "kind": _column_kind([row.get(name, "") for row in rows]),
            "position": index,
        }
        for index, name in enumerate(headers)
    ]
    content = {"headers": headers, "rows": rows, "source_table_id": table_id}
    fingerprint = _fingerprint(content)
    dataset_id = clean((previous or {}).get("id"), 100) or f"dataset_{table_id}"
    previous_fingerprint = (previous or {}).get("fingerprint")
    version = int((previous or {}).get("version") or 0)
    if previous_fingerprint != fingerprint:
        version += 1
    version = max(version, 1)
    return {
        "id": dataset_id,
        "schema_version": 1,
        "source_type": "table_block",
        "source_table_id": table_id,
        "version": version,
        "title": clean(table.get("title"), 100) or "数据表",
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "fingerprint": fingerprint,
        "updated_at": now(),
    }


def upsert_table_dataset(draft: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    """Persist the current DatasetVersion on the draft and annotate its TableBlock."""
    datasets = draft.setdefault("datasets", [])
    if not isinstance(datasets, list):
        datasets = []
        draft["datasets"] = datasets
    table_id = table.get("id")
    old = next((item for item in datasets if item.get("source_table_id") == table_id), None)
    dataset = build_dataset_version(table, old)
    if old is None:
        datasets.append(dataset)
    else:
        index = datasets.index(old)
        datasets[index] = dataset
    table["dataset_id"] = dataset["id"]
    table["dataset_version"] = dataset["version"]
    table["dataset_fingerprint"] = dataset["fingerprint"]
    return dataset


def dataset_for_table(draft: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    return upsert_table_dataset(draft, table)


def _eligible_measure_columns(dataset: dict[str, Any]) -> list[str]:
    return [item["name"] for item in dataset.get("schema") or [] if item.get("position", 0) > 0 and item.get("kind") == "number"]


def chart_spec_from_dataset(dataset: dict[str, Any], chart_id: str, kind: str, title_hint: str = "") -> dict[str, Any]:
    """Build the stable, renderer-neutral ChartSpec for bar/line/pie charts."""
    safe_kind: ChartKind = kind if kind in {"bar", "line", "pie"} else "bar"  # type: ignore[assignment]
    schema = dataset.get("schema") or []
    if len(schema) < 2:
        raise ValueError("数据集至少需要两列")
    category_column = schema[0]["name"]
    measures = _eligible_measure_columns(dataset)
    if not measures:
        raise ValueError("数据表没有完整的数值列，无法生成图表")
    rows = dataset.get("rows") or []
    categories = [clean(row.get(category_column), 48) for row in rows]
    if len(categories) < 2 or any(not item for item in categories):
        raise ValueError("图表至少需要两条带类别名称的数据")
    series = []
    for index, name in enumerate(measures[:3]):
        values = [number(row.get(name)) for row in rows]
        if any(value is None for value in values):
            continue
        series.append({"name": name, "values": [float(value) for value in values if value is not None], "axis": "left" if index == 0 else "right"})
    if not series:
        raise ValueError("数据表没有可用于图表的完整数值列")
    title = clean(title_hint, 100) or f"{dataset.get('title') or '数据表'}关键指标对比"
    binding = {
        "dataset_id": dataset["id"],
        "dataset_version": dataset["version"],
        "source_table_id": dataset["source_table_id"],
        "category_column": category_column,
        "measure_columns": [item["name"] for item in series],
        "data_fingerprint": dataset["fingerprint"],
    }
    spec: dict[str, Any] = {
        "id": chart_id,
        "schema_version": 2,
        "kind": safe_kind,
        "title": title,
        "caption": "基于论文中用户维护的数据表自动生成。",
        "binding": binding,
        "data": {"categories": categories, "series": series},
        "appearance": {"theme": "academic", "legend": True, "value_labels": safe_kind == "bar"},
        "provenance": {"status": "user_provided", "source_note": "数据来源：论文内用户维护的数据表。"},
    }
    if safe_kind == "pie":
        spec["data"]["pie"] = [
            {"name": category, "value": value}
            for category, value in zip(categories, series[0]["values"])
        ]
    return spec


def _svg_escape(value: object) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _write_svg(spec: dict[str, Any], destination: Path) -> None:
    """Write a dependency-free SVG preview from the same ChartSpec data."""
    title = _svg_escape(spec.get("title") or "图表")
    kind = spec.get("kind")
    data = spec.get("data") or {}
    categories = data.get("categories") or []
    series = data.get("series") or []
    width, height = 960, 560
    if kind == "pie":
        pie = data.get("pie") or []
        total = sum(max(float(item.get("value") or 0), 0) for item in pie) or 1
        colors = ["#2f5597", "#70ad47", "#ed7d31", "#a5a5a5", "#5b9bd5", "#ffc000"]
        start = -90.0
        paths = []
        legend = []
        cx, cy, radius = 285, 300, 155
        for index, item in enumerate(pie):
            value = max(float(item.get("value") or 0), 0)
            sweep = value / total * 360
            end = start + sweep
            import math as _math
            x1, y1 = cx + radius * _math.cos(_math.radians(start)), cy + radius * _math.sin(_math.radians(start))
            x2, y2 = cx + radius * _math.cos(_math.radians(end)), cy + radius * _math.sin(_math.radians(end))
            large = 1 if sweep > 180 else 0
            color = colors[index % len(colors)]
            paths.append(f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large} 1 {x2:.2f} {y2:.2f} Z" fill="{color}"/>')
            legend.append(f'<rect x="540" y="{185 + index * 42}" width="16" height="16" fill="{color}"/><text x="570" y="{198 + index * 42}" font-size="18" fill="#27364b">{_svg_escape(item.get("name"))}：{value:g}</text>')
            start = end
        content = "".join(paths + legend)
    else:
        values = [float(value) for item in series for value in (item.get("values") or [])]
        maximum = max(values) if values else 1.0
        maximum = maximum if maximum > 0 else 1.0
        left, top, plot_width, plot_height = 95, 120, 790, 320
        grid = "".join(f'<line x1="{left}" y1="{top + plot_height * r / 4:.1f}" x2="{left + plot_width}" y2="{top + plot_height * r / 4:.1f}" stroke="#dbe3ec"/>' for r in range(5))
        x_step = plot_width / max(len(categories), 1)
        labels = "".join(f'<text x="{left + x_step * (index + .5):.1f}" y="{top + plot_height + 35}" font-size="16" text-anchor="middle" fill="#4b5563">{_svg_escape(category)}</text>' for index, category in enumerate(categories))
        colors = ["#2f5597", "#70ad47", "#ed7d31"]
        marks: list[str] = []
        for series_index, item in enumerate(series):
            color = colors[series_index % len(colors)]
            vals = item.get("values") or []
            if kind == "line":
                points = " ".join(f'{left + x_step * (index + .5):.1f},{top + plot_height - float(value) / maximum * plot_height:.1f}' for index, value in enumerate(vals))
                marks.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="4"/>')
                marks.extend(f'<circle cx="{left + x_step * (index + .5):.1f}" cy="{top + plot_height - float(value) / maximum * plot_height:.1f}" r="5" fill="{color}"/>' for index, value in enumerate(vals))
            else:
                group_width = min(58, x_step * .72 / max(len(series), 1))
                for index, value in enumerate(vals):
                    bar_height = float(value) / maximum * plot_height
                    x = left + x_step * (index + .5) - group_width * len(series) / 2 + group_width * series_index
                    y = top + plot_height - bar_height
                    marks.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{group_width - 3:.1f}" height="{bar_height:.1f}" rx="2" fill="{color}"/>')
        legend = "".join(f'<rect x="{left + index * 160}" y="70" width="16" height="16" fill="{colors[index % len(colors)]}"/><text x="{left + 23 + index * 160}" y="84" font-size="16" fill="#27364b">{_svg_escape(item.get("name"))}</text>' for index, item in enumerate(series))
        content = f'{grid}<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#64748b"/><line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#64748b"/>{labels}{legend}{"".join(marks)}'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{width / 2}" y="42" font-size="24" font-family="Microsoft YaHei, SimHei, sans-serif" font-weight="700" text-anchor="middle" fill="#172033">{title}</text>
<g font-family="Microsoft YaHei, SimHei, sans-serif">{content}</g>
</svg>'''
    destination.write_text(svg, encoding="utf-8")


def _write_png(spec: dict[str, Any], destination: Path) -> None:
    """Render a deterministic academic PNG suitable for python-docx embedding."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    kind = spec.get("kind")
    data = spec.get("data") or {}
    title = str(spec.get("title") or "图表")
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=180)
    if kind == "pie":
        pie = data.get("pie") or []
        labels = [str(item.get("name") or "") for item in pie]
        values = [float(item.get("value") or 0) for item in pie]
        ax.pie(values, labels=labels, autopct="%.1f%%", startangle=90, textprops={"fontsize": 9})
        ax.axis("equal")
    else:
        categories = [str(item) for item in (data.get("categories") or [])]
        series = data.get("series") or []
        x = list(range(len(categories)))
        if kind == "line":
            for index, item in enumerate(series):
                ax.plot(x, item.get("values") or [], marker="o", linewidth=2, label=str(item.get("name") or f"指标{index + 1}"))
        else:
            group_width = 0.76 / max(len(series), 1)
            for index, item in enumerate(series):
                shift = (index - (len(series) - 1) / 2) * group_width
                bars = ax.bar([value + shift for value in x], item.get("values") or [], group_width * .9, label=str(item.get("name") or f"指标{index + 1}"))
                if spec.get("appearance", {}).get("value_labels"):
                    ax.bar_label(bars, fmt="%.2g", fontsize=8, padding=2)
        ax.set_xticks(x, categories, rotation=0)
        ax.grid(axis="y", linestyle="--", alpha=.3)
        if len(series) > 1:
            ax.legend(frameon=False)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)
    fig.tight_layout()
    fig.savefig(destination, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_chart_assets(task_dir: Path, chart_id: str, version: int, spec: dict[str, Any]) -> dict[str, Any]:
    charts_dir = task_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{chart_id}_v{version}"
    svg_rel = f"charts/{stem}.svg"
    png_rel = f"charts/{stem}.png"
    _write_svg(spec, task_dir / svg_rel)
    _write_png(spec, task_dir / png_rel)
    return {
        "id": f"asset_{chart_id}_v{version}",
        "schema_version": 1,
        "png_path": png_rel,
        "svg_path": svg_rel,
        "data_fingerprint": spec.get("binding", {}).get("data_fingerprint", ""),
        "generated_at": now(),
    }


def mark_charts_stale_for_table(draft: dict[str, Any], table_id: str) -> list[str]:
    """Mark chart blocks stale when their bound TableBlock receives a new dataset version."""
    changed: list[str] = []
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("type") != "chart":
                continue
            binding = (block.get("chart_spec") or {}).get("binding") or {}
            if binding.get("source_table_id") == table_id or table_id in (block.get("source_ids") or []):
                block["status"] = "stale"
                block["stale_reason"] = "关联数据表已修改，请重新计算图表。"
                block["updated_at"] = now()
                changed.append(str(block.get("id")))
    return changed


def recompute_chart_block(draft: dict[str, Any], task_dir: Path, block: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    """Rebuild ChartSpec and assets from the current bound TableBlock."""
    binding = (block.get("chart_spec") or {}).get("binding") or {}
    table_id = binding.get("source_table_id") or ((block.get("source_ids") or [None])[0])
    if not table_id:
        raise ValueError("图表没有可重新计算的数据表绑定")
    _, table = locate_block(draft, str(table_id))
    if table.get("type") != "table":
        raise ValueError("图表绑定的数据表已不存在")
    dataset = upsert_table_dataset(draft, table)
    chart_id = str(block.get("id") or "")
    if not chart_id:
        raise ValueError("图表缺少稳定 ID")
    old_spec = block.get("chart_spec") or {}
    chart_kind = kind or old_spec.get("kind") or (block.get("chart") or {}).get("kind") or "bar"
    spec = chart_spec_from_dataset(dataset, chart_id, chart_kind, clean(block.get("title"), 100))
    if block.get("caption"):
        spec["caption"] = clean(block.get("caption"), 180)
    next_version = int(block.get("version") or 0) + 1
    asset = render_chart_assets(task_dir, chart_id, next_version, spec)
    block.update({
        "status": "ready",
        "version": next_version,
        "title": spec["title"],
        "caption": spec["caption"],
        "chart_spec": spec,
        # `chart` remains as a compatibility projection for existing React clients.
        "chart": {"schema_version": 2, "kind": spec["kind"], "title": spec["title"], "caption": spec["caption"], **spec["data"]},
        "asset": asset,
        "source_ids": [dataset["source_table_id"]],
        "provenance": "user_provided",
        "stale_reason": None,
        "updated_at": now(),
    })
    return block


def create_chart_block_from_table(draft: dict[str, Any], task_dir: Path, section: dict[str, Any], chart_id: str, kind: str, title_hint: str, display_scale: float) -> dict[str, Any]:
    table = next((item for item in section.get("paragraphs") or [] if item.get("type") == "table"), None)
    if table is None:
        raise ValueError("当前小节没有可用于定量图表的数据表。请先新增数据表。")
    dataset = upsert_table_dataset(draft, table)
    spec = chart_spec_from_dataset(dataset, chart_id, kind, title_hint)
    asset = render_chart_assets(task_dir, chart_id, 1, spec)
    return {
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
        "display_scale": display_scale,
        "provenance": "user_provided",
        "source_ids": [dataset["source_table_id"]],
        "generated_at": now(),
    }


def figure_sections_for_draft(draft: dict[str, Any]) -> dict[str, str]:
    """Assign stable document-order figure numbers immediately before export."""
    numbers: dict[str, str] = {}
    index = 0
    for section in walk_sections(draft.get("sections") or []):
        for block in section.get("paragraphs") or []:
            if block.get("type") != "chart" or block.get("status") != "ready":
                continue
            asset = block.get("asset") or {}
            if not asset.get("png_path"):
                continue
            index += 1
            number = f"图{index}"
            block["figure_number"] = number
            numbers[str(block.get("id"))] = number
    return numbers
