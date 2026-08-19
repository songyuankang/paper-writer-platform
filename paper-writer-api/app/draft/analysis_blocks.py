"""Convert persisted AnalysisResult data into native paper blocks.

The implementation intentionally reuses ordinary TableBlock and chart block shapes
so DOCX export and figure numbering continue to use the established pipeline.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.draft.chart_runtime import normalize_appearance, now, render_chart_assets
from app.draft.service import DraftService


def _fmt(value: object, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def _reference(analysis: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_id": analysis["id"],
        "analysis_result_id": result["id"],
        "dataset_id": result["dataset_id"],
        "dataset_version": result["dataset_version"],
        "dataset_version_id": result["dataset_version_id"],
        "data_fingerprint": result.get("data_fingerprint"),
    }


def _table_specs(analysis: dict[str, Any], result: dict[str, Any]) -> list[tuple[str, list[str], list[list[str]]]]:
    payload = result.get("result") or {}
    if payload.get("method") in {"pearson", "spearman"}:
        coefficient = "r" if payload["method"] == "pearson" else "rho"
        title = f"{analysis.get('name') or '相关分析'}结果"
        return [(title, ["变量 X", "变量 Y", "N", coefficient, "P 值", "显著性"], [[
            str(payload.get("x") or ""), str(payload.get("y") or ""), _fmt(payload.get("n")),
            _fmt(payload.get(coefficient)), _fmt(payload.get("p_value")), "是" if payload.get("significant") else "否",
        ]])]
    specs: list[tuple[str, list[str], list[list[str]]]] = []
    numeric = payload.get("numeric") or []
    if numeric:
        rows = [[
            str(item.get("variable") or ""), _fmt(item.get("count")), _fmt(item.get("missing")),
            _fmt(item.get("mean")), _fmt(item.get("median")), _fmt(item.get("std")),
            _fmt(item.get("min")), _fmt(item.get("max")), _fmt(item.get("q1")), _fmt(item.get("q3")),
        ] for item in numeric]
        specs.append((f"{analysis.get('name') or '描述统计'}：数值变量", ["变量", "N", "Missing", "Mean", "Median", "Std", "Min", "Max", "Q1", "Q3"], rows))
    categorical = payload.get("categorical") or []
    if categorical:
        rows: list[list[str]] = []
        for item in categorical:
            frequency = item.get("frequency") or []
            if not frequency:
                rows.append([str(item.get("variable") or ""), _fmt(item.get("count")), _fmt(item.get("missing")), "—", "0", "0.00%"])
            for row in frequency[:95]:
                rows.append([
                    str(item.get("variable") or ""), _fmt(item.get("count")), _fmt(item.get("missing")),
                    str(row.get("category") or ""), _fmt(row.get("frequency")), f"{float(row.get('percentage') or 0):.2f}%",
                ])
        specs.append((f"{analysis.get('name') or '描述统计'}：分类变量", ["变量", "N", "Missing", "类别", "Frequency", "Percentage"], rows[:100]))
    if not specs:
        raise ValueError("AnalysisResult 没有可插入的统计表")
    return specs


def _insert_table(task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str) -> list[dict[str, Any]]:
    service = DraftService(task_id, settings.output_dir / task_id)
    reference = _reference(analysis, result)
    inserted: list[dict[str, Any]] = []
    with service.lock:
        draft = service.load()
        section = service._find_section(draft, section_id)
        for title, headers, rows in _table_specs(analysis, result):
            block = {
                "id": service._next_paragraph_id(section), "type": "table", "title": title,
                "headers": headers, "rows": rows,
                "analysis": reference, "provenance": "user_provided", "generated_at": now(),
            }
            section.setdefault("paragraphs", []).append(block)
            inserted.append(block)
        service.save(draft)
    return inserted


def _insert_correlation_chart(task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str) -> dict[str, Any]:
    payload = result.get("result") or {}
    method = str(payload.get("method") or "")
    if method not in {"pearson", "spearman"}:
        raise ValueError("当前仅 Pearson 与 Spearman 结果支持生成散点图")
    pairs = payload.get("pairs") or []
    if len(pairs) < 3:
        raise ValueError("有效观测不足，无法生成相关散点图")
    service = DraftService(task_id, settings.output_dir / task_id)
    reference = _reference(analysis, result)
    chart_id = f"chart_analysis_{uuid.uuid4().hex[:12]}"
    x_name, y_name = str(payload.get("x") or "X"), str(payload.get("y") or "Y")
    coefficient_key = "r" if method == "pearson" else "rho"
    coefficient = payload.get(coefficient_key)
    spec = {
        "id": chart_id, "schema_version": 2, "kind": "scatter",
        "title": f"{x_name}与{y_name}的{method.title()}相关散点图",
        "caption": f"{method.title()} {coefficient_key}={_fmt(coefficient)}，p={_fmt(payload.get('p_value'))}，n={_fmt(payload.get('n'))}。",
        "binding": {
            "source_type": "research_dataset", "dataset_id": result["dataset_id"],
            "dataset_version": result["dataset_version"], "data_fingerprint": result.get("data_fingerprint"),
            "analysis_id": analysis["id"], "analysis_result_id": result["id"],
        },
        "data": {
            "categories": [_fmt(item.get("x"), 8) for item in pairs],
            "series": [{"name": y_name, "values": [float(item["y"]) for item in pairs], "axis": "left"}],
            "row_count": len(pairs),
        },
        "appearance": normalize_appearance({"template": "academic", "legend": False, "x_label": x_name, "y_label": y_name}, "scatter"),
        "provenance": {"status": "user_provided", "source_note": "数据来源：AnalysisResult 的成对有效观测。"},
    }
    asset = render_chart_assets(service.task_dir, chart_id, 1, spec)
    block = {
        "id": chart_id, "type": "chart", "status": "ready", "version": 1, "text": "",
        "title": spec["title"], "caption": spec["caption"], "chart_spec": spec,
        "chart": {"schema_version": 2, "kind": "scatter", "title": spec["title"], "caption": spec["caption"], **spec["data"]},
        "asset": asset, "display_scale": .75, "provenance": "user_provided", "source_ids": [],
        "analysis": reference, "in_paper": True, "generated_at": now(),
    }
    with service.lock:
        draft = service.load()
        section = service._find_section(draft, section_id)
        section.setdefault("paragraphs", []).append(block)
        service.save(draft)
    return block


def insert_analysis_result(*, task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str, artifact: str) -> dict[str, Any]:
    if result.get("status") != "ready":
        raise ValueError("仅可插入已成功运行的 AnalysisResult")
    if artifact == "table":
        return {"type": "table", "blocks": _insert_table(task_id, analysis, result, section_id)}
    if artifact == "chart":
        return {"type": "chart", "block": _insert_correlation_chart(task_id, analysis, result, section_id)}
    raise ValueError("不支持的分析结果插入类型")
