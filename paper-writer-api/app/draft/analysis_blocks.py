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
    if payload.get("analysis_type") == "independent_t":
        title = f"{analysis.get('name') or '独立样本 t 检验'}结果"
        groups = [[str(item.get("group") or ""), _fmt(item.get("count")), _fmt(item.get("mean")), _fmt(item.get("std"))] for item in payload.get("group_statistics") or []]
        test = [[_fmt(payload.get("mean_difference")), _fmt(payload.get("t_statistic")), _fmt(payload.get("df")), _fmt(payload.get("p_value")), _fmt(payload.get("effect_size")), str(payload.get("effect_size_interpretation") or "")]]
        return [
            (f"{title}：组统计", ["组别", "N", "Mean", "SD"], groups),
            (f"{title}：检验结果", ["Mean Difference", "t", "df", "p", "Cohen's d", "效应量解释"], test),
        ]
    if payload.get("method") == "anova":
        title = f"{analysis.get('name') or '单因素方差分析'}结果"
        groups = [[str(item.get("group") or ""), _fmt(item.get("count")), _fmt(item.get("mean")), _fmt(item.get("std"))] for item in payload.get("group_statistics") or []]
        anova_rows = [
            ["组间", _fmt(payload.get("ss_between")), _fmt(payload.get("df_between")), _fmt(payload.get("ms_between")), _fmt(payload.get("f_statistic")), _fmt(payload.get("p_value")), _fmt(payload.get("eta_squared"))],
            ["组内", _fmt(payload.get("ss_within")), _fmt(payload.get("df_within")), _fmt(payload.get("ms_within")), "—", "—", "—"],
        ]
        specs = [
            (f"{title}：组统计", ["组别", "N", "Mean", "SD"], groups),
            (f"{title}：ANOVA", ["来源", "SS", "df", "MS", "F", "p", "eta squared"], anova_rows),
        ]
        tukey = payload.get("tukey_hsd") or []
        if tukey:
            specs.append((f"{title}：Tukey HSD", ["Group 1", "Group 2", "Mean Difference", "Adjusted p", "CI", "Reject"], [[
                str(item.get("group1") or ""), str(item.get("group2") or ""), _fmt(item.get("mean_difference")), _fmt(item.get("p_adjusted")),
                f"[{_fmt(item.get('lower'))}, {_fmt(item.get('upper'))}]", "是" if item.get("reject") else "否",
            ] for item in tukey]))
        return specs
    if payload.get("method") == "ols":
        title = f"{analysis.get('name') or '普通线性回归'}结果"
        summary = [[_fmt(payload.get("r_squared")), _fmt(payload.get("adjusted_r_squared")), _fmt(payload.get("f_statistic")), f"{_fmt(payload.get('df_model'))}, {_fmt(payload.get('df_resid'))}", _fmt(payload.get("f_p_value")), _fmt(payload.get("n"))]]
        coefficients = [[str(item.get("variable") or ""), _fmt(item.get("coefficient")), _fmt(item.get("standard_error")), _fmt(item.get("standardized_coefficient")), _fmt(item.get("t_statistic")), _fmt(item.get("p_value")), _fmt(item.get("ci_lower")), _fmt(item.get("ci_upper")), _fmt(item.get("vif"))] for item in payload.get("coefficients") or []]
        return [
            (f"{title}：模型摘要", ["R²", "Adjusted R²", "F", "df", "p", "N"], summary),
            (f"{title}：系数", ["Variable", "B", "SE", "Beta", "t", "p", "95% CI Lower", "95% CI Upper", "VIF"], coefficients),
        ]
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


def _insert_group_boxplot(task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str) -> dict[str, Any]:
    payload = result.get("result") or {}
    if payload.get("analysis_type") != "independent_t" and payload.get("method") != "anova":
        raise ValueError("当前分析结果不支持组间箱线图")
    groups = payload.get("group_statistics") or []
    if len(groups) < 2:
        raise ValueError("有效分组不足，无法生成箱线图")
    service = DraftService(task_id, settings.output_dir / task_id)
    chart_id = f"chart_analysis_{uuid.uuid4().hex[:12]}"
    method = "独立样本 t 检验" if payload.get("analysis_type") == "independent_t" else "单因素 ANOVA"
    spec = {
        "id": chart_id, "schema_version": 2, "kind": "boxplot",
        "title": f"{payload.get('value_column') or '数值'}按{payload.get('group_column') or '组别'}的组间分布",
        "caption": f"基于 {method} 的各组有效观测绘制箱线图。",
        "binding": {"source_type": "research_dataset", "dataset_id": result["dataset_id"], "dataset_version": result["dataset_version"], "data_fingerprint": result.get("data_fingerprint"), "analysis_id": analysis["id"], "analysis_result_id": result["id"]},
        "data": {"categories": [str(item.get("group") or "") for item in groups], "series": [{"name": str(item.get("group") or "组别"), "values": [float(value) for value in item.get("values") or []], "axis": "left"} for item in groups], "row_count": sum(int(item.get("count") or 0) for item in groups)},
        "appearance": normalize_appearance({"template": "academic", "legend": False, "y_label": str(payload.get("value_column") or "")}, "boxplot"),
        "provenance": {"status": "user_provided", "source_note": "数据来源：AnalysisResult 的分组有效观测。"},
    }
    asset = render_chart_assets(service.task_dir, chart_id, 1, spec)
    block = {"id": chart_id, "type": "chart", "status": "ready", "version": 1, "text": "", "title": spec["title"], "caption": spec["caption"], "chart_spec": spec, "chart": {"schema_version": 2, "kind": "boxplot", "title": spec["title"], "caption": spec["caption"], **spec["data"]}, "asset": asset, "display_scale": .75, "provenance": "user_provided", "source_ids": [], "analysis": _reference(analysis, result), "in_paper": True, "generated_at": now()}
    with service.lock:
        draft = service.load()
        section = service._find_section(draft, section_id)
        section.setdefault("paragraphs", []).append(block)
        service.save(draft)
    return block


def _insert_regression_chart(task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str, chart_type: str) -> dict[str, Any]:
    payload = result.get("result") or {}
    if payload.get("method") != "ols":
        raise ValueError("当前分析结果不支持回归图表")
    points = payload.get("points") or []
    if not points:
        raise ValueError("AnalysisResult 没有可绘制的回归观测")
    labels = {"actual_predicted": "实际值与预测值散点图", "residual": "残差诊断图", "coefficient": "回归系数图"}
    if chart_type not in labels:
        raise ValueError("不支持的回归图表类型")
    service = DraftService(task_id, settings.output_dir / task_id)
    chart_id = f"chart_analysis_{uuid.uuid4().hex[:12]}"
    if chart_type == "actual_predicted":
        kind, categories, series, appearance = "scatter", [_fmt(item.get("predicted"), 8) for item in points], [{"name": "实际值", "values": [float(item["actual"]) for item in points], "axis": "left"}], {"template": "academic", "legend": False, "x_label": "Predicted", "y_label": "Actual"}
        caption = "横轴为 OLS 预测值，纵轴为真实因变量观测值。"
    elif chart_type == "residual":
        kind, categories, series, appearance = "scatter", [_fmt(item.get("predicted"), 8) for item in points], [{"name": "残差", "values": [float(item["residual"]) for item in points], "axis": "left"}], {"template": "academic", "legend": False, "x_label": "Predicted", "y_label": "Residual"}
        caption = "残差诊断图：横轴为预测值，纵轴为残差；未对正态性或异方差性作自动结论。"
    else:
        coefficients = payload.get("coefficients") or []
        kind, categories, series, appearance = "bar", [str(item.get("variable") or "") for item in coefficients], [{"name": "回归系数 B", "values": [float(item.get("coefficient") or 0) for item in coefficients], "axis": "left", "confidence_intervals": [[float(item.get("ci_lower") or 0), float(item.get("ci_upper") or 0)] for item in coefficients]}], {"template": "academic", "legend": False, "y_label": "Coefficient B"}
        caption = "回归系数图；AnalysisResult 中同时保存各系数的 95% 置信区间。"
    spec = {"id": chart_id, "schema_version": 2, "kind": kind, "title": f"{payload.get('dependent_variable') or '因变量'}：{labels[chart_type]}", "caption": caption, "binding": {"source_type": "research_dataset", "dataset_id": result["dataset_id"], "dataset_version": result["dataset_version"], "data_fingerprint": result.get("data_fingerprint"), "analysis_id": analysis["id"], "analysis_result_id": result["id"], "regression_chart_type": chart_type}, "data": {"categories": categories, "series": series, "row_count": len(points)}, "appearance": normalize_appearance(appearance, kind), "provenance": {"status": "user_provided", "source_note": "数据来源：AnalysisResult 的 OLS 真实计算结果。"}}
    asset = render_chart_assets(service.task_dir, chart_id, 1, spec)
    block = {"id": chart_id, "type": "chart", "status": "ready", "version": 1, "text": "", "title": spec["title"], "caption": spec["caption"], "chart_spec": spec, "chart": {"schema_version": 2, "kind": kind, "title": spec["title"], "caption": spec["caption"], **spec["data"]}, "asset": asset, "display_scale": .75, "provenance": "user_provided", "source_ids": [], "analysis": _reference(analysis, result), "in_paper": True, "generated_at": now()}
    with service.lock:
        draft = service.load(); section = service._find_section(draft, section_id); section.setdefault("paragraphs", []).append(block); service.save(draft)
    return block


def insert_analysis_result(*, task_id: str, analysis: dict[str, Any], result: dict[str, Any], section_id: str, artifact: str) -> dict[str, Any]:
    if result.get("status") != "ready":
        raise ValueError("仅可插入已成功运行的 AnalysisResult")
    if artifact == "table":
        return {"type": "table", "blocks": _insert_table(task_id, analysis, result, section_id)}
    if artifact in {"chart", "actual_predicted", "residual", "coefficient"}:
        payload = result.get("result") or {}
        if payload.get("method") == "ols":
            block = _insert_regression_chart(task_id, analysis, result, section_id, "actual_predicted" if artifact == "chart" else artifact)
        elif payload.get("method") in {"pearson", "spearman"}:
            block = _insert_correlation_chart(task_id, analysis, result, section_id)
        else:
            block = _insert_group_boxplot(task_id, analysis, result, section_id)
        return {"type": "chart", "block": block}
    raise ValueError("不支持的分析结果插入类型")
