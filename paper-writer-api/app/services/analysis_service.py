"""Persistent, reproducible analysis service built on DatasetVersion.

Analysis definitions never store source rows or calculated values. Every execution
loads the selected immutable DatasetVersion, calculates server-side with pandas /
SciPy, and writes an append-only AnalysisResult JSON file.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.config import Settings
from app.services.dataset_service import DatasetService

SUPPORTED_ANALYSIS_TYPES = {"descriptive", "pearson", "spearman", "independent_t", "anova"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


def _version_id(dataset_id: str, version: int) -> str:
    return f"{dataset_id}:v{int(version)}"


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


class AnalysisService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.db_path.parent / "analyses"
        self.root.mkdir(parents=True, exist_ok=True)
        self.datasets = DatasetService(settings)

    def _dir(self, analysis_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", analysis_id)
        if safe != analysis_id or not safe:
            raise ValueError("分析 ID 无效")
        return self.root / safe

    def _metadata_path(self, analysis_id: str) -> Path:
        return self._dir(analysis_id) / "metadata.json"

    def _load(self, analysis_id: str) -> dict[str, Any]:
        path = self._metadata_path(analysis_id)
        if not path.is_file():
            raise ValueError("未找到分析")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, analysis: dict[str, Any]) -> None:
        directory = self._dir(str(analysis["id"]))
        directory.mkdir(parents=True, exist_ok=True)
        self._metadata_path(str(analysis["id"])).write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _refresh_stale(self, analysis: dict[str, Any]) -> bool:
        """Mark completed definitions stale when a newer DatasetVersion exists."""
        try:
            metadata = self.datasets.get_dataset(str(analysis["dataset_id"]))
            latest = int(metadata.get("latest_version") or 0)
        except ValueError:
            return False
        if latest > int(analysis.get("dataset_version") or 0) and analysis.get("status") == "ready":
            analysis.update(
                status="stale",
                stale_reason="数据集已有更新版本；请重新运行以使用最新 DatasetVersion。",
                updated_at=_now(),
            )
            self._save(analysis)
            return True
        return False

    @staticmethod
    def summary(analysis: dict[str, Any]) -> dict[str, Any]:
        return {
            key: analysis.get(key)
            for key in (
                "id", "task_id", "dataset_id", "dataset_version", "dataset_version_id", "type",
                "name", "description", "variables", "parameters", "status", "stale_reason",
                "error_message", "created_at", "updated_at", "last_result_id",
            )
        }

    def create(
        self,
        *,
        task_id: str,
        dataset_id: str,
        dataset_version: int | None,
        analysis_type: str,
        variables: dict[str, Any],
        name: str = "",
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        analysis_type = str(analysis_type or "").lower()
        if analysis_type not in SUPPORTED_ANALYSIS_TYPES:
            raise ValueError("当前仅支持 descriptive、pearson、spearman、independent_t 与 anova 分析")
        version_info = self.datasets.get_version(dataset_id, dataset_version, include_rows=False)
        version = int(version_info["version"])
        analysis_id = f"an_{uuid.uuid4().hex[:16]}"
        created_at = _now()
        defaults = {"descriptive": "描述性统计", "pearson": "Pearson 相关分析", "spearman": "Spearman 相关分析", "independent_t": "独立样本 t 检验", "anova": "单因素方差分析"}
        analysis = {
            "id": analysis_id,
            "task_id": task_id,
            "dataset_id": dataset_id,
            "dataset_version": version,
            "dataset_version_id": _version_id(dataset_id, version),
            "type": analysis_type,
            "name": _clean(name, 120) or defaults[analysis_type],
            "description": _clean(description, 500),
            "variables": variables if isinstance(variables, dict) else {},
            "parameters": parameters if isinstance(parameters, dict) else {},
            "status": "ready",
            "stale_reason": None,
            "error_message": None,
            "created_at": created_at,
            "updated_at": created_at,
            "last_result_id": None,
        }
        self._save(analysis)
        return analysis

    def list(self, task_id: str | None = None, dataset_id: str | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for directory in self.root.iterdir() if self.root.exists() else []:
            path = directory / "metadata.json"
            if not path.is_file():
                continue
            try:
                analysis = json.loads(path.read_text(encoding="utf-8"))
                if task_id and analysis.get("task_id") != task_id:
                    continue
                if dataset_id and analysis.get("dataset_id") != dataset_id:
                    continue
                self._refresh_stale(analysis)
                results.append(self.summary(analysis))
            except (ValueError, json.JSONDecodeError):
                continue
        return sorted(results, key=lambda item: item.get("updated_at") or "", reverse=True)

    def get(self, analysis_id: str) -> dict[str, Any]:
        analysis = self._load(analysis_id)
        self._refresh_stale(analysis)
        return analysis

    def _result_path(self, analysis_id: str, result_id: str) -> Path:
        return self._dir(analysis_id) / "results" / f"{result_id}.json"

    def _save_result(self, result: dict[str, Any]) -> None:
        path = self._result_path(str(result["analysis_id"]), str(result["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_result(self, analysis_id: str, result_id: str | None = None) -> dict[str, Any]:
        analysis = self.get(analysis_id)
        target = result_id or analysis.get("last_result_id")
        if not target:
            raise ValueError("该分析尚未运行")
        path = self._result_path(analysis_id, str(target))
        if not path.is_file():
            raise ValueError("未找到分析结果")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _frame(version: dict[str, Any]) -> pd.DataFrame:
        frame = pd.DataFrame(version.get("rows") or [])
        if frame.empty:
            raise ValueError("DatasetVersion 没有可用于统计的记录")
        return frame.replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _requested_columns(analysis: dict[str, Any], frame: pd.DataFrame) -> list[str]:
        variables = analysis.get("variables") or {}
        columns = variables.get("columns") or variables.get("variables") or []
        if not isinstance(columns, list):
            columns = []
        requested = [str(column) for column in columns if str(column) in frame.columns]
        return requested or [str(column) for column in frame.columns]

    @staticmethod
    def _descriptive(analysis: dict[str, Any], version: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        frame = AnalysisService._frame(version)
        warnings: list[str] = []
        numeric: list[dict[str, Any]] = []
        categorical: list[dict[str, Any]] = []
        requested = AnalysisService._requested_columns(analysis, frame)
        if not requested:
            raise ValueError("未选择有效变量")
        schema = {str(item.get("name")): str(item.get("type") or "text") for item in version.get("schema") or []}
        for column in requested:
            series = frame[column]
            missing = int(series.isna().sum() + series.fillna("").astype(str).str.strip().eq("").sum() - series.isna().sum())
            numeric_series = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
            declared_numeric = schema.get(column) == "numeric"
            if declared_numeric:
                count = int(numeric_series.count())
                if count == 0:
                    warnings.append(f"{column}：没有有效数值观测。")
                    numeric.append({"variable": column, "count": 0, "missing": missing, "mean": None, "median": None, "std": None, "min": None, "max": None, "q1": None, "q3": None})
                    continue
                numeric.append({
                    "variable": column, "count": count, "missing": missing,
                    "mean": _finite(numeric_series.mean()), "median": _finite(numeric_series.median()),
                    "std": _finite(numeric_series.std(ddof=1)) if count > 1 else 0.0,
                    "min": _finite(numeric_series.min()), "max": _finite(numeric_series.max()),
                    "q1": _finite(numeric_series.quantile(.25)), "q3": _finite(numeric_series.quantile(.75)),
                })
            else:
                usable = series.dropna().astype(str).map(str.strip)
                usable = usable[usable.ne("")]
                frequency = usable.value_counts(dropna=True)
                count = int(usable.shape[0])
                categorical.append({
                    "variable": column, "count": count, "missing": missing, "unique": int(frequency.shape[0]),
                    "frequency": [
                        {"category": str(category), "frequency": int(value), "percentage": float(value / count * 100) if count else 0.0}
                        for category, value in frequency.items()
                    ],
                })
        return {"method": "descriptive", "numeric": numeric, "categorical": categorical}, warnings

    @staticmethod
    def _correlation(analysis: dict[str, Any], version: dict[str, Any], method: str) -> tuple[dict[str, Any], list[str]]:
        frame = AnalysisService._frame(version)
        variables = analysis.get("variables") or {}
        x_name, y_name = str(variables.get("x") or ""), str(variables.get("y") or "")
        if not x_name or not y_name:
            raise ValueError("相关分析必须选择 X 与 Y 两个变量")
        if x_name == y_name:
            raise ValueError("X 与 Y 必须是不同变量")
        if x_name not in frame.columns or y_name not in frame.columns:
            raise ValueError("选择的变量不存在于 DatasetVersion")
        schema = {str(item.get("name")): str(item.get("type") or "text") for item in version.get("schema") or []}
        if schema.get(x_name) != "numeric" or schema.get(y_name) != "numeric":
            raise ValueError("相关分析仅支持数值变量")
        warnings: list[str] = []
        pair = pd.DataFrame({
            "x": pd.to_numeric(frame[x_name], errors="coerce"),
            "y": pd.to_numeric(frame[y_name], errors="coerce"),
        }).replace([np.inf, -np.inf], np.nan).dropna()
        excluded = int(frame.shape[0] - pair.shape[0])
        if excluded:
            warnings.append(f"已按成对有效观测排除 {excluded} 行缺失或非数值数据。")
        n = int(pair.shape[0])
        if n < 3:
            raise ValueError("有效成对观测不足，相关分析至少需要 3 条记录")
        if pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
            raise ValueError("相关分析不支持常数变量")
        if method == "pearson":
            test = stats.pearsonr(pair["x"], pair["y"])
            coefficient_name, coefficient = "r", float(test.statistic)
        else:
            test = stats.spearmanr(pair["x"], pair["y"])
            coefficient_name, coefficient = "rho", float(test.statistic)
        p_value = float(test.pvalue)
        if not math.isfinite(coefficient) or not math.isfinite(p_value):
            raise ValueError("相关分析未能产生有限统计量")
        return {
            "method": method, "x": x_name, "y": y_name, "n": n,
            coefficient_name: coefficient, "p_value": p_value,
            "significant": p_value < .05,
            "pairs": [{"x": float(row.x), "y": float(row.y)} for row in pair.itertuples(index=False)],
        }, warnings

    @staticmethod
    def _grouped_values(analysis: dict[str, Any], version: dict[str, Any], minimum_groups: int) -> tuple[dict[str, np.ndarray], list[str], str, str]:
        frame = AnalysisService._frame(version)
        variables = analysis.get("variables") or {}
        group_column = str(variables.get("group_column") or "")
        value_column = str(variables.get("value_column") or "")
        if not group_column or not value_column:
            raise ValueError("组间分析必须选择分组变量与数值变量")
        if group_column not in frame.columns or value_column not in frame.columns:
            raise ValueError("选择的变量不存在于 DatasetVersion")
        schema = {str(item.get("name")): str(item.get("type") or "text") for item in version.get("schema") or []}
        if schema.get(group_column) == "numeric":
            raise ValueError("分组变量必须是分类变量")
        if schema.get(value_column) != "numeric":
            raise ValueError("检验变量必须是数值变量")
        grouped = pd.DataFrame({
            "group": frame[group_column].fillna("").astype(str).str.strip(),
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }).replace([np.inf, -np.inf], np.nan)
        valid = grouped[(grouped["group"] != "") & grouped["value"].notna()]
        warnings: list[str] = []
        excluded = int(frame.shape[0] - valid.shape[0])
        if excluded:
            warnings.append(f"已排除 {excluded} 行缺失、非数值或无分组数据。")
        groups = {str(name): values.to_numpy(dtype=float) for name, values in valid.groupby("group", sort=True)["value"]}
        if len(groups) < minimum_groups:
            raise ValueError("有效分组数量不足")
        empty = [name for name, values in groups.items() if len(values) == 0]
        if empty:
            raise ValueError("存在空组")
        return groups, warnings, group_column, value_column

    @staticmethod
    def _effect_interpretation(value: float) -> str:
        magnitude = abs(value)
        if magnitude < .2:
            return "negligible"
        if magnitude < .5:
            return "small"
        if magnitude < .8:
            return "medium"
        return "large"

    @staticmethod
    def _independent_t(analysis: dict[str, Any], version: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        groups, warnings, group_column, value_column = AnalysisService._grouped_values(analysis, version, 2)
        if len(groups) != 2:
            raise ValueError("独立样本 t 检验要求恰好两个有效组")
        (group_a, values_a), (group_b, values_b) = list(groups.items())
        if len(values_a) < 2 or len(values_b) < 2:
            raise ValueError("每个组至少需要 2 个有效观测")
        std_a, std_b = float(np.std(values_a, ddof=1)), float(np.std(values_b, ddof=1))
        if std_a == 0 or std_b == 0:
            raise ValueError("独立样本 t 检验不支持常数组")
        alpha = float((analysis.get("parameters") or {}).get("alpha") or .05)
        if not .001 <= alpha <= .2:
            alpha = .05
        levene = stats.levene(values_a, values_b, center="median")
        equal_variance = bool(float(levene.pvalue) >= alpha)
        test = stats.ttest_ind(values_a, values_b, equal_var=equal_variance)
        n_a, n_b = len(values_a), len(values_b)
        if equal_variance:
            method, df = "student_t", float(n_a + n_b - 2)
            reason = "Levene 方差齐性检验未拒绝方差相等假设。"
        else:
            method = "welch_t"
            numerator = (std_a ** 2 / n_a + std_b ** 2 / n_b) ** 2
            denominator = ((std_a ** 2 / n_a) ** 2 / (n_a - 1)) + ((std_b ** 2 / n_b) ** 2 / (n_b - 1))
            df = float(numerator / denominator) if denominator else 0.0
            reason = "Levene 方差齐性检验提示方差不齐，已使用 Welch t 检验。"
            warnings.append(reason)
        pooled_sd = math.sqrt((((n_a - 1) * std_a ** 2) + ((n_b - 1) * std_b ** 2)) / (n_a + n_b - 2))
        if pooled_sd == 0:
            raise ValueError("无法计算 Cohen's d：合并标准差为零")
        mean_a, mean_b = float(np.mean(values_a)), float(np.mean(values_b))
        effect_size = (mean_a - mean_b) / pooled_sd
        return {
            "method": method, "analysis_type": "independent_t", "group_column": group_column, "value_column": value_column,
            "group_a": group_a, "group_b": group_b, "n_a": n_a, "n_b": n_b,
            "mean_a": mean_a, "mean_b": mean_b, "std_a": std_a, "std_b": std_b,
            "mean_difference": mean_a - mean_b, "t_statistic": float(test.statistic), "df": df,
            "p_value": float(test.pvalue), "effect_size": float(effect_size), "effect_size_type": "cohens_d",
            "effect_size_interpretation": AnalysisService._effect_interpretation(effect_size),
            "group_statistics": [
                {"group": group_a, "count": n_a, "mean": mean_a, "std": std_a, "values": values_a.tolist()},
                {"group": group_b, "count": n_b, "mean": mean_b, "std": std_b, "values": values_b.tolist()},
            ],
            "assumptions": {"alpha": alpha, "levene_statistic": float(levene.statistic), "levene_p_value": float(levene.pvalue), "equal_variance_used": equal_variance, "method_reason": reason},
        }, warnings

    @staticmethod
    def _anova(analysis: dict[str, Any], version: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        groups, warnings, group_column, value_column = AnalysisService._grouped_values(analysis, version, 2)
        if any(len(values) < 2 for values in groups.values()):
            warnings.append("至少一个组的有效样本量小于 2，方差与前提判断需谨慎解释。")
        if all(np.std(values, ddof=1) == 0 if len(values) > 1 else True for values in groups.values()):
            raise ValueError("所有组内均无变异，无法执行 ANOVA")
        alpha = float((analysis.get("parameters") or {}).get("alpha") or .05)
        if not .001 <= alpha <= .2:
            alpha = .05
        arrays = list(groups.values())
        test = stats.f_oneway(*arrays)
        grand_mean = float(np.mean(np.concatenate(arrays)))
        # scipy computes F/p; SS terms are retained for an ANOVA table and eta squared traceability.
        ss_between = float(sum(len(values) * (float(np.mean(values)) - grand_mean) ** 2 for values in arrays))
        ss_within = float(sum(np.sum((values - float(np.mean(values))) ** 2) for values in arrays))
        df_between, df_within = len(arrays) - 1, sum(len(values) for values in arrays) - len(arrays)
        ms_between = ss_between / df_between if df_between else 0.0
        ms_within = ss_within / df_within if df_within else 0.0
        total_ss = ss_between + ss_within
        if total_ss == 0:
            raise ValueError("总变异为零，无法计算 eta squared")
        eta_squared = ss_between / total_ss
        group_statistics = [{
            "group": name, "count": len(values), "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0, "values": values.tolist(),
        } for name, values in groups.items()]
        levene = stats.levene(*arrays, center="median") if all(len(values) >= 2 for values in arrays) else None
        if levene is not None and float(levene.pvalue) < alpha:
            warnings.append("Levene 方差齐性检验提示组间方差可能不齐；ANOVA 结果未自动更换方法。")
        tukey_rows: list[dict[str, Any]] = []
        if float(test.pvalue) < alpha:
            tukey = stats.tukey_hsd(*arrays)
            interval = tukey.confidence_interval(confidence_level=1 - alpha)
            names = list(groups)
            for left in range(len(names)):
                for right in range(left + 1, len(names)):
                    tukey_rows.append({
                        "group1": names[left], "group2": names[right],
                        "mean_difference": float(tukey.statistic[left, right]),
                        "p_adjusted": float(tukey.pvalue[left, right]),
                        "lower": float(interval.low[left, right]), "upper": float(interval.high[left, right]),
                        "reject": bool(float(tukey.pvalue[left, right]) < alpha),
                    })
        else:
            warnings.append("ANOVA 未达显著水平，默认未执行 Tukey HSD 事后比较。")
        return {
            "method": "anova", "analysis_type": "anova", "group_column": group_column, "value_column": value_column,
            "groups": list(groups), "group_statistics": group_statistics, "grand_mean": grand_mean,
            "ss_between": ss_between, "ss_within": ss_within, "df_between": df_between, "df_within": df_within,
            "ms_between": ms_between, "ms_within": ms_within, "f_statistic": float(test.statistic),
            "p_value": float(test.pvalue), "eta_squared": float(eta_squared), "alpha": alpha,
            "tukey_hsd": tukey_rows, "assumptions": {"levene_statistic": float(levene.statistic) if levene is not None else None, "levene_p_value": float(levene.pvalue) if levene is not None else None},
        }, warnings

    def run(self, analysis_id: str) -> dict[str, Any]:
        analysis = self._load(analysis_id)
        analysis.update(status="running", stale_reason=None, error_message=None, updated_at=_now())
        self._save(analysis)
        result_id = f"ar_{uuid.uuid4().hex[:16]}"
        try:
            metadata = self.datasets.get_dataset(str(analysis["dataset_id"]))
            latest_version = int(metadata.get("latest_version") or analysis["dataset_version"])
            # A stale definition is deliberately re-bound to the current immutable version;
            # previous AnalysisResult files remain untouched and fully traceable.
            if latest_version > int(analysis["dataset_version"]):
                analysis["dataset_version"] = latest_version
                analysis["dataset_version_id"] = _version_id(str(analysis["dataset_id"]), latest_version)
            version = self.datasets.get_version(str(analysis["dataset_id"]), int(analysis["dataset_version"]), include_rows=True)
            if analysis["type"] == "descriptive":
                payload, warnings = self._descriptive(analysis, version)
            elif analysis["type"] in {"pearson", "spearman"}:
                payload, warnings = self._correlation(analysis, version, str(analysis["type"]))
            elif analysis["type"] == "independent_t":
                payload, warnings = self._independent_t(analysis, version)
            elif analysis["type"] == "anova":
                payload, warnings = self._anova(analysis, version)
            else:
                raise ValueError("不支持的分析类型")
            result = {
                "id": result_id, "analysis_id": analysis_id,
                "dataset_id": analysis["dataset_id"], "dataset_version": analysis["dataset_version"],
                "dataset_version_id": analysis["dataset_version_id"], "result": payload,
                "warnings": warnings, "data_fingerprint": version["fingerprint"],
                "status": "ready", "created_at": _now(),
            }
            self._save_result(result)
            analysis.update(status="ready", stale_reason=None, error_message=None, last_result_id=result_id, updated_at=_now())
            self._save(analysis)
            return result
        except (ValueError, KeyError, TypeError) as exc:
            result = {
                "id": result_id, "analysis_id": analysis_id,
                "dataset_id": analysis.get("dataset_id"), "dataset_version": analysis.get("dataset_version"),
                "dataset_version_id": analysis.get("dataset_version_id"), "result": {},
                "warnings": [str(exc)], "data_fingerprint": None,
                "status": "failed", "created_at": _now(),
            }
            self._save_result(result)
            analysis.update(status="failed", error_message=str(exc), last_result_id=result_id, updated_at=_now())
            self._save(analysis)
            return result


def analysis_service(settings: Settings) -> AnalysisService:
    return AnalysisService(settings)
