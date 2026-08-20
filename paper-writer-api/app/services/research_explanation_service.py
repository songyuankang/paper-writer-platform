"""Safe, traceable interpretation for completed AnalysisResult files.

Statistical facts are generated only from persisted results. A model may phrase
interpretations, limitations and cautions, but is prohibited from adding numbers.
"""
from __future__ import annotations
import json, re, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.config import Settings
from app.services import deepseek
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.model_service import resolve_model

_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", re.I)
def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _v(value: Any) -> str: return str(value)
def _sig(p: Any, alpha: Any = .05) -> bool:
    try: return float(p) < float(alpha)
    except (TypeError, ValueError): return False

class ResearchExplanationService:
    def __init__(self, settings: Settings):
        self.settings=settings; self.analyses=AnalysisService(settings); self.datasets=DatasetService(settings)
        self.root=settings.db_path.parent / "explanations"; self.root.mkdir(parents=True, exist_ok=True)
    def _path(self, analysis_id: str, explanation_id: str) -> Path:
        if not re.fullmatch(r"an_[A-Za-z0-9]+", analysis_id) or not re.fullmatch(r"ex_[A-Za-z0-9]+", explanation_id): raise ValueError("解释 ID 无效")
        return self.root / analysis_id / f"{explanation_id}.json"
    def _facts(self, analysis: dict, result: dict) -> tuple[str, list[str], list[str], list[str]]:
        data=result["result"]; method=data.get("method") or analysis["type"]; alpha=data.get("alpha") or (analysis.get("parameters") or {}).get("alpha") or .05
        facts: list[str]=[]; interpretation: list[str]=[]; cautions: list[str]=[]
        if method == "descriptive":
            for row in data.get("numeric", []): facts.append(f"{row['variable']}：有效观测 N = {_v(row.get('count'))}，均值 = {_v(row.get('mean'))}，标准差 = {_v(row.get('std'))}，缺失 = {_v(row.get('missing'))}。")
            for row in data.get("categorical", []): facts.append(f"{row['variable']}：有效观测 N = {_v(row.get('count'))}，类别数 = {_v(row.get('unique'))}，缺失 = {_v(row.get('missing'))}。")
            summary="描述性统计已基于当前 DatasetVersion 的有效观测生成。"; interpretation.append("这些统计量用于描述样本特征，不构成变量间关系或因果结论。")
        elif method in {"pearson", "spearman"}:
            coefficient="r" if method=="pearson" else "rho"; p=data.get("p_value")
            facts.append(f"{method.title()} 相关分析：{data.get('x')} 与 {data.get('y')} 的 N = {_v(data.get('n'))}，{coefficient} = {_v(data.get(coefficient))}，p = {_v(p)}。")
            direction="正向" if float(data.get(coefficient,0))>0 else "负向" if float(data.get(coefficient,0))<0 else "接近零"
            interpretation.append(f"两变量呈{direction}关联；{'结果具有统计学显著性。' if _sig(p,alpha) else '未发现统计学显著关联。'}")
            cautions.append("相关分析仅描述关联，不支持因果推断。") ; summary=f"已完成 {method.title()} 相关分析。"
        elif method in {"student_t", "welch_t"}:
            p=data.get("p_value"); label="Welch t-test" if method=="welch_t" else "Student t-test"
            facts.append(f"{label}：{data.get('group_a')}（N = {_v(data.get('n_a'))}，Mean = {_v(data.get('mean_a'))}）与 {data.get('group_b')}（N = {_v(data.get('n_b'))}，Mean = {_v(data.get('mean_b'))}）比较，均值差 = {_v(data.get('mean_difference'))}，t = {_v(data.get('t_statistic'))}，df = {_v(data.get('df'))}，p = {_v(p)}，Cohen's d = {_v(data.get('effect_size'))}。")
            interpretation.append("两组比较" + ("具有统计学显著性。" if _sig(p,alpha) else "未发现统计学显著差异。")); summary=f"已完成 {label}。"
        elif method == "anova":
            p=data.get("p_value"); facts.append(f"单因素 ANOVA：F = {_v(data.get('f_statistic'))}，df_between = {_v(data.get('df_between'))}，df_within = {_v(data.get('df_within'))}，p = {_v(p)}，eta squared = {_v(data.get('eta_squared'))}。")
            interpretation.append("各组总体比较" + ("具有统计学显著性。" if _sig(p,alpha) else "未发现统计学显著差异。"))
            if _sig(p,alpha):
                for row in data.get("tukey_hsd", []):
                    if row.get("reject"): facts.append(f"Tukey HSD：{row.get('group1')} 与 {row.get('group2')} 的均值差 = {_v(row.get('mean_difference'))}，调整后 p = {_v(row.get('p_adjusted'))}，CI = [{_v(row.get('lower'))}, {_v(row.get('upper'))}]。")
            summary="已完成单因素 ANOVA。"
        elif method == "ols":
            p=data.get("f_p_value"); facts.append(f"OLS 模型：N = {_v(data.get('n'))}，R² = {_v(data.get('r_squared'))}，Adjusted R² = {_v(data.get('adjusted_r_squared'))}，F = {_v(data.get('f_statistic'))}，模型 p = {_v(p)}。")
            for row in data.get("coefficients", []): facts.append(f"Predictor {row.get('variable')}：B = {_v(row.get('coefficient'))}，Beta = {_v(row.get('standardized_coefficient'))}，t = {_v(row.get('t_statistic'))}，p = {_v(row.get('p_value'))}，CI = [{_v(row.get('ci_lower'))}, {_v(row.get('ci_upper'))}]，VIF = {_v(row.get('vif'))}。")
            interpretation.append("模型整体" + ("具有统计学显著性。" if _sig(p,alpha) else "未发现统计学显著性。")); summary="已完成普通最小二乘线性回归。"
        else: raise ValueError("AnalysisResult 不包含受支持的统计方法")
        return summary, facts, interpretation, cautions
    @staticmethod
    def _safe_texts(value: Any) -> list[str]:
        if not isinstance(value,list) or any(not isinstance(item,str) or len(item)>800 or _NUMBER.search(item) for item in value): raise ValueError("模型解释包含非法结构或未验证数字")
        return [item.strip() for item in value if item.strip()]
    def _model_text(self, *, model_id: str|None, prompt: dict, fallback: tuple[list[str],list[str],list[str]]) -> tuple[list[str],list[str],list[str],str]:
        runtime=resolve_model(model_id)
        if not runtime: return *fallback, "rule_based_fallback"
        try:
            text=deepseek.chat_with(runtime.base_url,runtime.api_key,runtime.model,[{"role":"system","content":"你只能解释给定真实统计事实。输出 JSON object，键为 interpretation、limitations、cautions，值均为字符串数组。禁止输出任何阿拉伯数字、统计数值、变量名之外的新事实；禁止因果表述。"},{"role":"user","content":json.dumps(prompt,ensure_ascii=False)}],temperature=.1,max_tokens=min(runtime.max_tokens,1200),timeout=min(self.settings.deepseek_timeout,90))
            data=json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
            return self._safe_texts(data.get("interpretation",[])), self._safe_texts(data.get("limitations",[])), self._safe_texts(data.get("cautions",[])), "configured_model"
        except Exception: return *fallback, "rule_based_fallback"
    def explain(self, *, analysis_id:str, analysis_result_id:str, model_id:str|None=None) -> dict:
        analysis=self.analyses.get(analysis_id); result=self.analyses.get_result(analysis_id,analysis_result_id)
        if result.get("analysis_id")!=analysis_id or result.get("status")!="ready": raise ValueError("Analysis 与 AnalysisResult 不一致或结果不可解释")
        version=self.datasets.get_version(str(result["dataset_id"]),int(result["dataset_version"]),include_rows=False)
        if version.get("fingerprint")!=result.get("data_fingerprint"): raise ValueError("AnalysisResult 与 DatasetVersion 指纹不一致")
        summary,facts,rule_interpretation,rule_cautions=self._facts(analysis,result)
        warnings=[str(item) for item in result.get("warnings") or []]
        latest=int(self.datasets.get_dataset(str(result["dataset_id"])).get("latest_version") or result["dataset_version"])
        if latest>int(result["dataset_version"]): warnings.append("该解释对应旧 DatasetVersion；当前数据集已有更新版本。")
        profile=[{"name":item.get("name"),"type":item.get("type"),"missing_count":item.get("missing_count"),"unique_count":item.get("unique_count")} for item in version.get("schema") or []]
        interp,limits,cautions,provider=self._model_text(model_id=model_id,prompt={"analysis_type":analysis["type"],"variables":analysis.get("variables"),"parameters":analysis.get("parameters"),"statistical_facts":facts,"warnings":warnings,"dataset_profile":profile},fallback=(rule_interpretation,warnings,rule_cautions))
        explanation={"id":f"ex_{uuid.uuid4().hex[:16]}","analysis_id":analysis_id,"analysis_result_id":analysis_result_id,"dataset_id":result["dataset_id"],"dataset_version":result["dataset_version"],"dataset_version_id":result["dataset_version_id"],"data_fingerprint":result["data_fingerprint"],"model_id":model_id,"provider":provider,"analysis_summary":summary,"statistical_facts":[{"text":text,"source":"analysis_result"} for text in facts],"interpretation":interp,"limitations":limits,"cautions":cautions,"created_at":_now()}
        path=self._path(analysis_id,explanation["id"]); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(explanation,ensure_ascii=False,indent=2),encoding="utf-8")
        return explanation
