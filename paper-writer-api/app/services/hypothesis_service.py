"""Research hypotheses and discussion framework grounded in immutable AnalysisResult.

No model may decide a hypothesis.  Decisions and all numerical evidence are
calculated here from persisted result payloads; discussion output is a small,
controlled evidence framework rather than an automatically written discussion.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

DIRECTIONS = {"positive", "negative", "difference", "association", "unknown"}
HYPOTHESIS_STATUSES = {"pending", "supported", "not_supported", "insufficient_evidence", "inconclusive"}
DECISIONS = HYPOTHESIS_STATUSES - {"pending"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: str, prefix: str) -> str:
    if not re.fullmatch(prefix + r"_[A-Za-z0-9]+", value or ""):
        raise ValueError(f"{prefix} ID 无效")
    return value


def _task(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id or ""):
        raise ValueError("任务 ID 无效")
    return task_id


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class HypothesisService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.analyses = AnalysisService(settings)
        self.datasets = DatasetService(settings)
        self.root = settings.db_path.parent / "hypotheses"
        self.framework_root = settings.db_path.parent / "discussion_frameworks"
        self.root.mkdir(parents=True, exist_ok=True)
        self.framework_root.mkdir(parents=True, exist_ok=True)

    def _hypothesis_path(self, hypothesis_id: str) -> Path:
        return self.root / "items" / f"{_safe(hypothesis_id, 'hp')}.json"

    def _evaluation_path(self, hypothesis_id: str, evaluation_id: str) -> Path:
        return self.root / "evaluations" / _safe(hypothesis_id, "hp") / f"{_safe(evaluation_id, 'he')}.json"

    def _framework_path(self, framework_id: str) -> Path:
        return self.framework_root / f"{_safe(framework_id, 'df')}.json"

    def _save(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _clean(value: Any, limit: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    def create(self, *, task_id: str, title: str, statement: str, direction: str = "unknown", variable_bindings: dict[str, Any] | None = None, analysis_ids: list[str] | None = None) -> dict[str, Any]:
        task_id = _task(task_id); direction = str(direction or "unknown")
        if direction not in DIRECTIONS:
            raise ValueError("假设方向无效")
        statement = self._clean(statement, 1000)
        if not statement:
            raise ValueError("研究假设陈述不能为空")
        analysis_ids = list(dict.fromkeys(str(item) for item in analysis_ids or [] if str(item)))
        for analysis_id in analysis_ids:
            analysis = self.analyses.get(analysis_id)
            if analysis.get("task_id") != task_id:
                raise ValueError("Hypothesis 只能绑定同一论文任务的 Analysis")
        created = _now()
        item = {"id": f"hp_{uuid.uuid4().hex[:16]}", "task_id": task_id, "title": self._clean(title, 160) or statement[:80], "statement": statement, "direction": direction, "status": "pending", "variable_bindings": variable_bindings if isinstance(variable_bindings, dict) else {}, "analysis_ids": analysis_ids, "created_at": created, "updated_at": created}
        self._save(self._hypothesis_path(item["id"]), item)
        return item

    def _raw_hypotheses(self, task_id: str | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in (self.root / "items").glob("hp_*.json") if (self.root / "items").exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if not task_id or item.get("task_id") == task_id:
                    entries.append(item)
            except json.JSONDecodeError:
                continue
        return sorted(entries, key=lambda item: item.get("updated_at") or "", reverse=True)

    def get(self, hypothesis_id: str) -> dict[str, Any]:
        path = self._hypothesis_path(hypothesis_id)
        if not path.is_file():
            raise ValueError("未找到研究假设")
        item = json.loads(path.read_text(encoding="utf-8"))
        return self._with_status(item)

    def list(self, task_id: str) -> list[dict[str, Any]]:
        return [self._with_status(item) for item in self._raw_hypotheses(_task(task_id))]

    def update(self, hypothesis_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        item = self.get(hypothesis_id)
        editable = {"title", "statement", "direction", "variable_bindings", "analysis_ids"}
        if not any(key in changes for key in editable):
            raise ValueError("没有可更新的假设字段")
        if "title" in changes:
            item["title"] = self._clean(changes["title"], 160) or item["title"]
        if "statement" in changes:
            statement = self._clean(changes["statement"], 1000)
            if not statement:
                raise ValueError("研究假设陈述不能为空")
            item["statement"] = statement
        if "direction" in changes:
            direction = str(changes["direction"])
            if direction not in DIRECTIONS:
                raise ValueError("假设方向无效")
            item["direction"] = direction
        if "variable_bindings" in changes:
            if not isinstance(changes["variable_bindings"], dict):
                raise ValueError("variable_bindings 必须为对象")
            item["variable_bindings"] = changes["variable_bindings"]
        if "analysis_ids" in changes:
            ids = list(dict.fromkeys(str(value) for value in changes["analysis_ids"] if str(value)))
            for analysis_id in ids:
                if self.analyses.get(analysis_id).get("task_id") != item["task_id"]:
                    raise ValueError("Hypothesis 只能绑定同一论文任务的 Analysis")
            item["analysis_ids"] = ids
        item["updated_at"] = _now()
        # Edits create no retrospective judgement; earlier evaluation snapshots remain intact.
        item["status"] = "pending"
        self._save(self._hypothesis_path(item["id"]), item)
        return item

    def _result_status(self, source: dict[str, Any]) -> str:
        dataset_id, version = source.get("dataset_id"), source.get("dataset_version")
        if not dataset_id or version is None:
            return "missing"
        try:
            latest = int(self.datasets.get_dataset(str(dataset_id)).get("latest_version") or version)
        except ValueError:
            return "missing"
        return "stale_source" if int(version) < latest else "current"

    def _with_status(self, item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        evaluations = self.evaluations(item["id"])
        if evaluations:
            latest = evaluations[0]
            result["latest_evaluation_id"] = latest["id"]
            result["evaluation_status"] = latest["data_status"]
            if latest["data_status"] == "current":
                result["status"] = latest["decision"]
        return result

    @staticmethod
    def _alpha(analysis: dict[str, Any], payload: dict[str, Any]) -> float:
        alpha = _number(payload.get("alpha")) or _number((analysis.get("parameters") or {}).get("alpha")) or .05
        return alpha if .001 <= alpha <= .2 else .05

    @staticmethod
    def _direction(value: float | None) -> str:
        if value is None or value == 0:
            return "zero" if value == 0 else "unknown"
        return "positive" if value > 0 else "negative"

    def _evaluate_payload(self, hypothesis: dict[str, Any], analysis: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        payload = result.get("result") or {}; method = str(payload.get("method") or "")
        alpha = self._alpha(analysis, payload); direction = hypothesis["direction"]
        base = {"method": method, "analysis_type": analysis.get("type"), "sample_size": payload.get("n") or payload.get("raw_sample_size"), "alpha": alpha, "dataset_version_id": result.get("dataset_version_id"), "data_fingerprint": result.get("data_fingerprint")}
        if method in {"pearson", "spearman"}:
            statistic = _number(payload.get("r" if method == "pearson" else "rho")); p = _number(payload.get("p_value")); observed = self._direction(statistic)
            base.update({"statistic_name": "r" if method == "pearson" else "rho", "statistic": statistic, "p_value": p, "direction_observed": observed, "variables": {"x": payload.get("x"), "y": payload.get("y")}})
            if p is None or statistic is None: return "inconclusive", base
            if p >= alpha: return "insufficient_evidence", base
            if direction in {"association", "unknown"}: return "supported", base
            return ("supported" if observed == direction else "not_supported"), base
        if method in {"student_t", "welch_t"}:
            p = _number(payload.get("p_value")); difference = _number(payload.get("mean_difference")); observed = self._direction(difference)
            base.update({"statistic_name": "t", "statistic": _number(payload.get("t_statistic")), "p_value": p, "mean_difference": difference, "effect_size": _number(payload.get("effect_size")), "direction_observed": observed, "groups": [payload.get("group_a"), payload.get("group_b")]})
            if p is None: return "inconclusive", base
            if p >= alpha: return "insufficient_evidence", base
            if direction in {"difference", "association", "unknown"}: return "supported", base
            return ("supported" if observed == direction else "not_supported"), base
        if method == "anova":
            p = _number(payload.get("p_value")); pairs = [item for item in payload.get("tukey_hsd") or [] if item.get("reject")]
            base.update({"statistic_name": "F", "statistic": _number(payload.get("f_statistic")), "p_value": p, "eta_squared": _number(payload.get("eta_squared")), "tukey_significant_pairs": [{"group1": item.get("group1"), "group2": item.get("group2"), "mean_difference": item.get("mean_difference"), "p_adjusted": item.get("p_adjusted")} for item in pairs], "groups": payload.get("groups") or []})
            if p is None: return "inconclusive", base
            return ("supported" if p < alpha else "insufficient_evidence"), base
        if method == "ols":
            model_p = _number(payload.get("f_p_value")); bindings = hypothesis.get("variable_bindings") or {}; expected = bindings.get("predictors") or []
            expected = [str(item) for item in expected] if isinstance(expected, list) else []
            predictors = []
            for row in payload.get("coefficients") or []:
                coefficient = _number(row.get("coefficient")); predictor = {"variable": row.get("variable"), "coefficient": coefficient, "beta": _number(row.get("standardized_coefficient")), "p_value": _number(row.get("p_value")), "direction_observed": self._direction(coefficient)}
                predictor["supported"] = bool(predictor["p_value"] is not None and predictor["p_value"] < alpha and (direction in {"unknown", "association", "difference"} or predictor["direction_observed"] == direction))
                predictors.append(predictor)
            selected = [item for item in predictors if not expected or item["variable"] in expected]
            base.update({"statistic_name": "F", "statistic": _number(payload.get("f_statistic")), "model_p_value": model_p, "r_squared": _number(payload.get("r_squared")), "predictors": predictors, "evaluated_predictors": selected, "model_supported": bool(model_p is not None and model_p < alpha)})
            if model_p is None: return "inconclusive", base
            if model_p >= alpha: return "insufficient_evidence", base
            if expected and any(not item["supported"] for item in selected): return "inconclusive", base
            return "supported", base
        base.update({"reason": "描述性统计不自动判定研究假设。"})
        return "inconclusive", base

    def evaluate(self, *, hypothesis_id: str, analysis_id: str, analysis_result_id: str) -> dict[str, Any]:
        hypothesis = self.get(hypothesis_id); analysis = self.analyses.get(analysis_id)
        if analysis.get("task_id") != hypothesis["task_id"] or analysis_id not in hypothesis.get("analysis_ids", []):
            raise ValueError("Analysis 未绑定到该 Hypothesis")
        result = self.analyses.get_result(analysis_id, analysis_result_id)
        if result.get("analysis_id") != analysis_id or result.get("status") != "ready":
            raise ValueError("Analysis 与 AnalysisResult 不匹配或结果未就绪")
        version = self.datasets.get_version(str(result["dataset_id"]), int(result["dataset_version"]), include_rows=False)
        if version.get("fingerprint") != result.get("data_fingerprint"):
            raise ValueError("AnalysisResult 与 DatasetVersion 指纹不匹配")
        decision, evidence = self._evaluate_payload(hypothesis, analysis, result)
        evaluation = {"id": f"he_{uuid.uuid4().hex[:16]}", "hypothesis_id": hypothesis_id, "task_id": hypothesis["task_id"], "analysis_id": analysis_id, "analysis_result_id": analysis_result_id, "dataset_id": result["dataset_id"], "dataset_version": result["dataset_version"], "dataset_version_id": result["dataset_version_id"], "data_fingerprint": result["data_fingerprint"], "decision": decision, "evidence": evidence, "created_at": _now()}
        self._save(self._evaluation_path(hypothesis_id, evaluation["id"]), evaluation)
        hypothesis["status"] = decision; hypothesis["updated_at"] = _now(); self._save(self._hypothesis_path(hypothesis_id), hypothesis)
        return self._evaluation_with_status(evaluation)

    def _evaluation_with_status(self, item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item); result["data_status"] = self._result_status(item); return result

    def evaluations(self, hypothesis_id: str) -> list[dict[str, Any]]:
        directory = self.root / "evaluations" / _safe(hypothesis_id, "hp")
        entries: list[dict[str, Any]] = []
        for path in directory.glob("he_*.json") if directory.exists() else []:
            try: entries.append(self._evaluation_with_status(json.loads(path.read_text(encoding="utf-8"))))
            except json.JSONDecodeError: continue
        return sorted(entries, key=lambda item: item.get("created_at") or "", reverse=True)

    @staticmethod
    def _contains_digit(value: Any) -> bool:
        if isinstance(value, str): return bool(re.search(r"\d", value))
        if isinstance(value, list): return any(HypothesisService._contains_digit(item) for item in value)
        if isinstance(value, dict): return any(str(key).lower() in {"decision", "p_value", "statistic", "r_squared", "number"} or HypothesisService._contains_digit(item) for key, item in value.items())
        return False

    def _guard_ai_suggestion(self, suggestion: Any) -> None:
        if suggestion is None: return
        if not isinstance(suggestion, dict): raise ValueError("AI 讨论建议必须为对象")
        # Untrusted AI prose may not provide a decision or invent/change numerical facts.
        if self._contains_digit(suggestion): raise ValueError("AI 讨论建议不能包含 decision 或未经验证的统计数字")

    def create_framework(self, *, task_id: str, hypothesis_ids: list[str], finding_ids: list[str] | None = None, evaluation_ids: list[str] | None = None, ai_suggestion: dict[str, Any] | None = None) -> dict[str, Any]:
        task_id = _task(task_id); self._guard_ai_suggestion(ai_suggestion)
        hypotheses = [self.get(item) for item in list(dict.fromkeys(hypothesis_ids))]
        if not hypotheses or any(item.get("task_id") != task_id for item in hypotheses):
            raise ValueError("Discussion Framework 至少需要同一任务的一个 Hypothesis")
        evaluation_map = {item["id"]: item for hypothesis in hypotheses for item in self.evaluations(hypothesis["id"])}
        if evaluation_ids:
            selected = [evaluation_map[item] for item in evaluation_ids if item in evaluation_map]
            if len(selected) != len(set(evaluation_ids)): raise ValueError("evaluation 不属于所选 Hypothesis")
        else:
            selected = [items[0] for hypothesis in hypotheses if (items := self.evaluations(hypothesis["id"]))]
        summaries = []
        for hypothesis in hypotheses:
            evaluation = next((item for item in selected if item["hypothesis_id"] == hypothesis["id"]), None)
            decision = evaluation["decision"] if evaluation else "inconclusive"
            summaries.append({"hypothesis_id": hypothesis["id"], "statement": hypothesis["statement"], "decision": decision, "evaluation_id": evaluation["id"] if evaluation else None, "evidence": evaluation.get("evidence") if evaluation else None})
        sections = {"main_findings": [{"type": "evidence_card", "hypothesis_id": item["hypothesis_id"], "decision": item["decision"], "statement": item["statement"]} for item in summaries], "hypothesis_evaluation": summaries, "interpretation": ["请结合研究设计、样本范围与已验证统计证据讨论可能解释；本框架不作因果推断。"], "limitations": ["需要结合样本、测量、模型前提与未观测因素补充限制讨论。"], "practical_implications": ["需要由作者基于研究情境补充实践含义；系统不会自动引用文献或生成完整 Discussion。"]}
        # External evidence is selected only from user-created Hypothesis-Literature
        # links.  Framework creation never asks a model to infer a literature claim.
        link_path = self.settings.db_path.parent / "literature" / "hypothesis_links" / f"{task_id}.json"
        try:
            literature_links = (json.loads(link_path.read_text(encoding="utf-8")) or {}).get("links") or [] if link_path.is_file() else []
        except json.JSONDecodeError:
            literature_links = []
        linked_literature = {str(item.get("literature_id")) for item in literature_links if str(item.get("hypothesis_id")) in {item["id"] for item in hypotheses}}
        evidence_root = self.settings.db_path.parent / "literature" / "evidence"
        literature_evidence_ids: list[str] = []
        for path in evidence_root.glob("lit_*/le_*.json") if evidence_root.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if str(item.get("literature_id")) in linked_literature and item.get("id"):
                    literature_evidence_ids.append(str(item["id"]))
            except json.JSONDecodeError:
                continue
        framework = {"id": f"df_{uuid.uuid4().hex[:16]}", "task_id": task_id, "hypothesis_ids": [item["id"] for item in hypotheses], "finding_ids": list(dict.fromkeys(finding_ids or [])), "evaluation_ids": [item["id"] for item in selected], "literature_evidence_ids": sorted(set(literature_evidence_ids)), "sections": sections, "provider": "controlled_evidence_framework", "status": "current", "created_at": _now()}
        if any(item["data_status"] != "current" for item in selected): framework["status"] = "stale_source"
        self._save(self._framework_path(framework["id"]), framework)
        return framework

    def list_frameworks(self, task_id: str) -> list[dict[str, Any]]:
        task_id = _task(task_id); values: list[dict[str, Any]] = []
        for path in self.framework_root.glob("df_*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    values.append(self.get_framework(str(item.get("id"))))
            except (ValueError, json.JSONDecodeError):
                continue
        return sorted(values, key=lambda item: item.get("created_at") or "", reverse=True)

    def get_framework(self, framework_id: str) -> dict[str, Any]:
        path = self._framework_path(framework_id)
        if not path.is_file(): raise ValueError("未找到 Discussion Framework")
        framework = json.loads(path.read_text(encoding="utf-8"))
        evaluations = {item["id"]: item for hypothesis_id in framework.get("hypothesis_ids") or [] for item in self.evaluations(hypothesis_id)}
        framework["status"] = "stale_source" if any(evaluations.get(item, {}).get("data_status") != "current" for item in framework.get("evaluation_ids") or []) else "current"
        return framework

    def evidence(self, evaluation_id: str) -> dict[str, Any]:
        for path in (self.root / "evaluations").glob("hp_*/he_*.json") if (self.root / "evaluations").exists() else []:
            try:
                evaluation = json.loads(path.read_text(encoding="utf-8"))
                if evaluation.get("id") != evaluation_id: continue
                hypothesis = self.get(evaluation["hypothesis_id"]); analysis = self.analyses.get(evaluation["analysis_id"]); result = self.analyses.get_result(evaluation["analysis_id"], evaluation["analysis_result_id"])
                dataset = self.datasets.get_version(str(evaluation["dataset_id"]), int(evaluation["dataset_version"]), include_rows=False)
                return {"hypothesis": hypothesis, "evaluation": self._evaluation_with_status(evaluation), "analysis": analysis, "analysis_result": result, "dataset": dataset}
            except (ValueError, json.JSONDecodeError):
                continue
        raise ValueError("未找到 HypothesisEvaluation")
