"""AI research-method recommendation and confirmed Analysis orchestration.

The assistant never receives Dataset rows and never produces statistical results.
"""
from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.services import deepseek
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.model_service import resolve_model

ALLOWED_METHODS = {"descriptive", "pearson", "spearman", "independent_t", "anova", "regression"}
_METHOD_CHART = {"descriptive": "bar", "pearson": "scatter", "spearman": "scatter", "independent_t": "boxplot", "anova": "boxplot", "regression": "scatter"}


class ResearchAssistantService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.datasets = DatasetService(settings)
        self.analyses = AnalysisService(settings)

    @staticmethod
    def _profile(version: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"name": str(item.get("name") or ""), "type": str(item.get("type") or "text"), "missing_count": int(item.get("missing_count") or 0), "unique_count": int(item.get("unique_count") or 0), "summary": item.get("summary") or {}} for item in version.get("schema") or []]

    @staticmethod
    def _variables_for(method: str, names: list[str], profile: list[dict[str, Any]]) -> dict[str, Any]:
        numeric = [item["name"] for item in profile if item["type"] == "numeric"]
        categorical = [item["name"] for item in profile if item["type"] == "categorical"]
        if method == "descriptive": return {"columns": names or [item["name"] for item in profile]}
        if method in {"pearson", "spearman"}: return {"x": names[0], "y": names[1]}
        if method in {"independent_t", "anova"}: return {"group_column": names[0], "value_column": names[1]}
        if method == "regression": return {"dependent_variable": names[0], "predictors": names[1:]}
        raise ValueError("不支持的推荐方法")

    @staticmethod
    def _valid_variables(method: str, names: list[str], profile: list[dict[str, Any]]) -> bool:
        types = {item["name"]: item["type"] for item in profile}
        if not names or any(name not in types for name in names): return False
        if method == "descriptive": return True
        if method in {"pearson", "spearman"}: return len(names) == 2 and all(types[name] == "numeric" for name in names) and names[0] != names[1]
        if method in {"independent_t", "anova"}: return len(names) == 2 and types[names[0]] == "categorical" and types[names[1]] == "numeric"
        if method == "regression": return len(names) >= 2 and len(set(names)) == len(names) and all(types[name] == "numeric" for name in names)
        return False

    @staticmethod
    def _pick_name(question: str, choices: list[str], fallback: str = "") -> str:
        lowered = question.lower()
        return next((name for name in choices if name.lower() in lowered), fallback or (choices[0] if choices else ""))

    def _rule_recommendation(self, question: str, hypothesis: str, profile: list[dict[str, Any]]) -> dict[str, Any]:
        text = f"{question} {hypothesis}".lower()
        numeric = [item["name"] for item in profile if item["type"] == "numeric"]
        categorical = [item for item in profile if item["type"] == "categorical"]
        warnings = ["当前未配置可用模型，已按变量类型与研究问题关键词生成受约束候选；请在运行前确认变量与方法。"]
        dependent = self._pick_name(question, numeric, next((name for name in numeric if any(key in name.lower() for key in ("满意", "score", "satisfaction", "得分"))), numeric[0] if numeric else ""))
        if any(key in text for key in ("回归", "预测", "影响", "解释")) and len(numeric) >= 2 and not (categorical and any(item["name"].lower() in text for item in categorical) and any(key in text for key in ("不同", "差异", "影响"))):
            names = [dependent, *[name for name in numeric if name != dependent]]
            method, reason = "regression", "研究问题包含影响或预测语义，且存在一个数值因变量和多个数值自变量。"
        elif categorical and numeric and any(item["name"].lower() in text for item in categorical) and any(key in text for key in ("不同", "差异", "影响")):
            group = self._pick_name(question, [item["name"] for item in categorical], categorical[0]["name"])
            item = next(value for value in categorical if value["name"] == group)
            method = "independent_t" if item["unique_count"] == 2 else "anova"
            reason = f"分组变量 {group} 包含 {item['unique_count']} 个类别，结果变量为连续数值变量。"
            names = [group, dependent]
        elif any(key in text for key in ("相关", "关系", "关联")) and len(numeric) >= 2:
            names = [self._pick_name(question, numeric, numeric[0]), next(name for name in numeric if name != self._pick_name(question, numeric, numeric[0]))]
            method = "spearman" if any(key in text for key in ("等级", "秩", "非正态")) else "pearson"
            reason = "研究问题关注两个数值变量的关联，可将其作为相关分析候选。"
        else:
            names, method, reason = numeric[:2] or [item["name"] for item in profile][:3], "descriptive", "当前问题主要适合先了解变量分布、缺失情况与基础统计。"
        return {"research_goal": question.strip(), "variable_roles": [{"variable": name, "role": "dependent" if index == 0 and method == "regression" else "group" if index == 0 and method in {"independent_t", "anova"} else "measure"} for index, name in enumerate(names)], "recommended_methods": [{"type": method, "confidence": "medium", "reason": reason, "variables": names}], "recommended_charts": [{"type": _METHOD_CHART[method], "reason": f"{_METHOD_CHART[method]} 可与 {method} 的现有图表能力配合展示真实 AnalysisResult。"}], "required_variables": names, "warnings": warnings}

    def _validate(self, payload: dict[str, Any], profile: list[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
        methods = []
        for item in payload.get("recommended_methods") or []:
            method = str(item.get("type") or "")
            names = [str(value) for value in item.get("variables") or payload.get("required_variables") or []]
            if method in ALLOWED_METHODS and self._valid_variables(method, names, profile):
                methods.append({"type": method, "confidence": str(item.get("confidence") or "medium")[:24], "reason": str(item.get("reason") or "变量类型与研究问题匹配。")[:500], "variables": names})
        if not methods: return fallback
        allowed = {item["name"] for item in profile}
        roles = [{"variable": str(item.get("variable")), "role": str(item.get("role") or "measure")} for item in payload.get("variable_roles") or [] if str(item.get("variable")) in allowed]
        charts = [{"type": _METHOD_CHART[methods[0]["type"]], "reason": str((payload.get("recommended_charts") or [{}])[0].get("reason") or "推荐图表与当前方法匹配。")[:500]}]
        return {"research_goal": str(payload.get("research_goal") or fallback["research_goal"])[:1000], "variable_roles": roles or fallback["variable_roles"], "recommended_methods": methods, "recommended_charts": charts, "required_variables": methods[0]["variables"], "warnings": [str(item)[:300] for item in payload.get("warnings") or []]}

    def recommend(self, *, question: str, hypothesis: str, dataset_id: str, dataset_version: int, model_id: str | None = None) -> dict[str, Any]:
        if not question.strip(): raise ValueError("研究问题不能为空")
        if not dataset_id or not dataset_version: raise ValueError("必须选择 Dataset 与 DatasetVersion")
        version = self.datasets.get_version(dataset_id, dataset_version, include_rows=False)
        profile = self._profile(version); fallback = self._rule_recommendation(question, hypothesis, profile)
        runtime = resolve_model(model_id)
        provider = "rule_fallback"
        if runtime:
            prompt = {"research_question": question, "hypothesis": hypothesis, "dataset": {"dataset_id": dataset_id, "dataset_version": dataset_version, "row_count": version.get("row_count"), "schema": profile}, "allowed_methods": sorted(ALLOWED_METHODS), "instruction": "仅输出 JSON。不得输出或猜测 N、p、F、r、R² 或任何统计结果。recommended_methods 每项必须包含 type、confidence、reason、variables。只推荐 allowed_methods 中的方法；variables 只能来自 schema。"}
            try:
                text = deepseek.chat_with(runtime.base_url, runtime.api_key, runtime.model, [{"role": "system", "content": "你是研究方法助手，只做候选方法推荐与变量角色识别，绝不计算统计数值。"}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}], temperature=0.1, max_tokens=min(runtime.max_tokens, 1600), timeout=min(self.settings.deepseek_timeout, 90))
                result = self._validate(json.loads(text.strip().removeprefix("```json").removesuffix("```").strip()), profile, fallback); provider = "configured_model"
            except Exception as exc:  # keep local workflow usable without fabricating results
                result = fallback; result["warnings"].append(f"模型推荐不可用，已使用变量类型规则候选：{type(exc).__name__}。")
        else: result = fallback
        return {"recommendation": result, "dataset": {"dataset_id": dataset_id, "dataset_version": dataset_version, "fingerprint": version.get("fingerprint"), "row_count": version.get("row_count"), "schema": profile}, "provider": provider}

    def run_confirmed(self, *, task_id: str, dataset_id: str, dataset_version: int, method: str, variables: dict[str, Any], parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in ALLOWED_METHODS: raise ValueError("推荐的方法不受当前 Analysis 引擎支持")
        version = self.datasets.get_version(dataset_id, dataset_version, include_rows=False)
        names = variables.get("columns") if method == "descriptive" else list(variables.values())
        flattened = [item for value in (names or []) for item in (value if isinstance(value, list) else [value])]
        if method == "regression": flattened = [variables.get("dependent_variable"), *(variables.get("predictors") or [])]
        if not self._valid_variables(method, [str(item) for item in flattened if item], self._profile(version)):
            raise ValueError("确认运行的变量与 DatasetVersion 类型不匹配")
        analysis = self.analyses.create(task_id=task_id, dataset_id=dataset_id, dataset_version=dataset_version, analysis_type=method, variables=variables, parameters=parameters or {})
        result = self.analyses.run(analysis["id"])
        return {"analysis": self.analyses.get(analysis["id"]), "result": result}
