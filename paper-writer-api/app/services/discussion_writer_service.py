"""Traceable, evidence-bounded DiscussionDraft generation.

DiscussionDraft is intentionally separate from DiscussionFramework: the framework
selects evidence and structure; this service creates a versioned language draft
from that frozen selection.  A model may phrase non-numeric commentary only;
all statistical facts, decisions, source labels and evidence identities remain
server-owned and are validated before persistence.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.draft.service import DraftService
from app.services import deepseek
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.model_service import resolve_model
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService
from app.services.research_object_service import ResearchObjectService
from app.services.dependency_graph_service import DependencyGraphService

SECTION_TYPES = {"main_findings", "hypothesis_discussion", "literature_comparison", "possible_explanations", "theoretical_implications", "practical_implications", "limitations"}
CAUSAL = re.compile(r"导致|造成|引起|证明.*(?:正确|有效)|决定了|因果|effect\s+of|caus(?:e|al)", re.I)
MODEL_DECISION = re.compile(r"获得统计支持|未获得支持|未获得统计支持|证据不足|结果不确定|supported|not[ _-]?supported|inconclusive", re.I)
NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", re.I)


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _clean(value: Any, limit: int = 3000) -> str: return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
def _safe_task(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id or ""): raise ValueError("任务 ID 无效")
    return task_id

def _valid_id(value: str, prefix: str) -> str:
    if not re.fullmatch(prefix + r"_[A-Za-z0-9]+", value or ""): raise ValueError(f"{prefix} ID 无效")
    return value


class DiscussionWriterService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.db_path.parent / "discussion_drafts"; self.root.mkdir(parents=True, exist_ok=True)
        self.analyses = AnalysisService(settings); self.datasets = DatasetService(settings)
        self.hypotheses = HypothesisService(settings); self.findings = ResearchFindingService(settings)
        self.literature = LiteratureService(settings); self.explanations = ResearchExplanationService(settings)
        self.objects = ResearchObjectService(settings); self.graph = DependencyGraphService(settings)

    def _path(self, draft_id: str) -> Path: return self.root / f"{_valid_id(draft_id, 'dd')}.json"
    def _write(self, value: dict[str, Any]) -> None: self._path(value["id"]).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    def _raw(self, draft_id: str) -> dict[str, Any]:
        path = self._path(draft_id)
        if not path.is_file(): raise ValueError("未找到 DiscussionDraft")
        return json.loads(path.read_text(encoding="utf-8"))
    def _all(self, task_id: str) -> list[dict[str, Any]]:
        values=[]
        for path in self.root.glob("dd_*.json"):
            try:
                item=json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id")==task_id: values.append(item)
            except json.JSONDecodeError: continue
        return sorted(values,key=lambda item:item.get("created_at") or "",reverse=True)

    def _explanation_for(self, analysis_id: str, result_id: str) -> dict[str, Any] | None:
        root = self.settings.db_path.parent / "explanations" / analysis_id
        for path in root.glob("ex_*.json") if root.exists() else []:
            try:
                value=json.loads(path.read_text(encoding="utf-8"))
                if value.get("analysis_result_id")==result_id: return value
            except json.JSONDecodeError: continue
        return None

    def _literature_evidence(self, evidence_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not re.fullmatch(r"le_[A-Za-z0-9]+", evidence_id or ""): raise ValueError("LiteratureEvidence ID 无效")
        root=self.settings.db_path.parent / "literature" / "evidence"
        for path in root.glob("lit_*/"+evidence_id+".json") if root.exists() else []:
            value=json.loads(path.read_text(encoding="utf-8")); literature=self.literature.get(str(value.get("literature_id")))
            return value,literature
        raise ValueError("未找到 LiteratureEvidence")

    def _finding(self, finding_id: str, task_id: str) -> dict[str, Any]:
        value=self.findings.get(finding_id)
        if value.get("task_id")!=task_id: raise ValueError("ResearchFinding 不属于当前任务")
        return value

    def build_fact_package(self, *, task_id: str, framework_id: str, hypothesis_ids: list[str] | None = None, finding_ids: list[str] | None = None, literature_evidence_ids: list[str] | None = None, research_context: str = "", practical_context: str = "") -> dict[str, Any]:
        task_id=_safe_task(task_id); framework=self.hypotheses.get_framework(framework_id)
        if framework.get("task_id")!=task_id: raise ValueError("DiscussionFramework 不属于当前任务")
        allowed_hypotheses={str(item) for item in framework.get("hypothesis_ids") or []}; selected_hypotheses=list(dict.fromkeys(hypothesis_ids or list(allowed_hypotheses)))
        if not selected_hypotheses or not set(selected_hypotheses).issubset(allowed_hypotheses): raise ValueError("只能选择 Framework 内的 Hypothesis")
        selected_hypotheses_data=[self.hypotheses.get(item) for item in selected_hypotheses]
        evaluation_map={item["id"]: item for hid in selected_hypotheses for item in self.hypotheses.evaluations(hid)}
        selected_evaluation_ids=[str(item) for item in framework.get("evaluation_ids") or [] if str(item) in evaluation_map]
        evaluations=[evaluation_map[item] for item in selected_evaluation_ids]
        if any(item.get("task_id")!=task_id for item in evaluations): raise ValueError("HypothesisEvaluation 不属于当前任务")
        analysis_results=[]; explanations=[]
        for evaluation in evaluations:
            result=self.analyses.get_result(str(evaluation["analysis_id"]),str(evaluation["analysis_result_id"]))
            if result.get("analysis_id")!=evaluation.get("analysis_id") or result.get("data_fingerprint")!=evaluation.get("data_fingerprint"): raise ValueError("HypothesisEvaluation 与 AnalysisResult 不一致")
            analysis=self.analyses.get(str(evaluation["analysis_id"])); summary,facts,interpretation,cautions=self.explanations._facts(analysis,result)
            analysis_results.append({"id":result["id"],"analysis_id":analysis["id"],"dataset_id":result["dataset_id"],"dataset_version":result["dataset_version"],"dataset_version_id":result["dataset_version_id"],"data_fingerprint":result["data_fingerprint"],"method":(result.get("result") or {}).get("method"),"statistical_facts":facts,"warnings":[str(item) for item in result.get("warnings") or []],"rule_interpretation":interpretation,"cautions":cautions,"payload":result.get("result") or {}})
            explanation=self._explanation_for(analysis["id"],result["id"])
            if explanation: explanations.append(explanation)
        allowed_findings={str(item) for item in framework.get("finding_ids") or []}; selected_findings=list(dict.fromkeys(finding_ids or list(allowed_findings)))
        if not set(selected_findings).issubset(allowed_findings): raise ValueError("只能选择 Framework 内的 ResearchFinding")
        findings=[self._finding(item,task_id) for item in selected_findings]
        allowed_literature={str(item) for item in framework.get("literature_evidence_ids") or []}; selected_literature=list(dict.fromkeys(literature_evidence_ids or list(allowed_literature)))
        if not set(selected_literature).issubset(allowed_literature): raise ValueError("不能引用未选择或不属于 Framework 的 LiteratureEvidence")
        literature=[]
        for evidence_id in selected_literature:
            evidence,item=self._literature_evidence(evidence_id)
            if item.get("task_id")!=task_id: raise ValueError("LiteratureEvidence 不属于当前任务")
            literature.append({"evidence":evidence,"literature":{"id":item["id"],"title":item.get("title"),"authors":item.get("authors") or [],"year":item.get("year"),"doi":item.get("doi"),"status":item.get("status")}})
        snapshot={"dataset_version_ids":[item["dataset_version_id"] for item in analysis_results],"analysis_result_ids":[item["id"] for item in analysis_results],"explanation_ids":[item["id"] for item in explanations],"literature_evidence_ids":selected_literature,"data_fingerprints":[item["data_fingerprint"] for item in analysis_results]}
        return {"task_id":task_id,"framework":{"id":framework["id"],"status":framework.get("status"),"sections":framework.get("sections") or {}},"hypotheses":selected_hypotheses_data,"evaluations":evaluations,"analysis_results":analysis_results,"explanations":explanations,"findings":findings,"literature_evidence":literature,"research_context":_clean(research_context,3000),"practical_context":_clean(practical_context,3000),"source_snapshot":snapshot}

    @staticmethod
    def _decision_label(value: str) -> str:
        return {"supported":"获得统计支持","not_supported":"未获得统计支持","insufficient_evidence":"证据不足","inconclusive":"结果不确定"}.get(value,"结果不确定")
    @staticmethod
    def _lit_label(literature: dict[str, Any]) -> str:
        authors=literature.get("authors") or []; first=_clean(authors[0] if authors else "匿名",160).split()[-1]; year=literature.get("year") or "n.d."
        return f"{first} et al. ({year})" if len(authors)>=3 else f"{first} ({year})"
    def _rule_paragraphs(self, section_type: str, package: dict[str, Any], length: str) -> list[dict[str, Any]]:
        result_by_id={item["id"]:item for item in package["analysis_results"]}; evals=package["evaluations"]; literature=package["literature_evidence"]
        output: list[dict[str, Any]]=[]
        def add(text: str, refs: list[str], kind: str="controlled") -> None:
            text=_clean(text,2600)
            if text: output.append({"text":text,"evidence_refs":refs,"kind":kind})
        if section_type=="main_findings":
            for finding in package["findings"]:
                for text in (finding.get("paragraphs") or [])[:(1 if length=="short" else 2)]: add(text,[f"finding:{finding['id']}",f"analysis_result:{finding['analysis_result_id']}"])
            if not output:
                for result in package["analysis_results"]:
                    for fact in result["statistical_facts"][:(1 if length=="short" else 2)]: add(f"主要发现的统计事实如下：{fact}",[f"analysis_result:{result['id']}"])
        elif section_type=="hypothesis_discussion":
            for evaluation in evals:
                hypothesis=next((item for item in package["hypotheses"] if item["id"]==evaluation["hypothesis_id"]),None); result=result_by_id.get(evaluation["analysis_result_id"])
                if hypothesis and result:
                    fact=result["statistical_facts"][0] if result["statistical_facts"] else "当前分析结果已完成。"
                    add(f"对于假设“{hypothesis['statement']}”，当前评价为“{self._decision_label(evaluation['decision'])}”。这一判断基于以下真实统计证据：{fact}",[f"hypothesis_evaluation:{evaluation['id']}",f"analysis_result:{result['id']}"])
        elif section_type=="literature_comparison":
            for item in literature:
                evidence=item["evidence"]; lit=item["literature"]; label=self._lit_label(lit); location=evidence.get("source_location")
                if location=="abstract": prefix="该研究摘要显示"
                elif location=="metadata": prefix="该研究的公开元数据表明"
                else: prefix="根据用户记录"
                add(f"与本研究相关的外部证据中，{label} 的{prefix}：{evidence.get('claim')}。该信息作为{location}层级证据用于比较，不等同于阅读全文后的结论。",[f"literature_evidence:{evidence['id']}"])
        elif section_type=="possible_explanations":
            if package.get("research_context"):
                add(f"结合用户提供的研究背景，一个可能的解释是：{package['research_context']}。这一解释属于候选机制，尚未由当前分析直接验证。",[f"hypothesis_evaluation:{item['id']}" for item in evals],"possible_explanation")
            else:
                add("一个可能的解释是，变量之间的关联可能受到研究设计、测量方式或未观测情境因素共同作用。该解释属于候选机制，不能据此确认因果关系。",[f"hypothesis_evaluation:{item['id']}" for item in evals],"possible_explanation")
        elif section_type=="theoretical_implications":
            if evals:
                labels="、".join(self._decision_label(item["decision"]) for item in evals)
                add(f"在当前研究范围内，这些假设评价结果对相关理论解释提供一定支持或修正线索（评价结果：{labels}）。该表述限于当前数据与证据范围，不构成对理论正确性的证明。",[f"hypothesis_evaluation:{item['id']}" for item in evals])
            else: add("当前证据不足以生成可靠的理论意义内容。",[])
        elif section_type=="practical_implications":
            if package.get("practical_context"):
                add(f"结合用户提供的实践背景，结果提示可以进一步关注：{package['practical_context']}。该建议用于后续关注，不代表确定的干预或政策结论。",[f"hypothesis_evaluation:{item['id']}" for item in evals])
            else: add("当前没有用户提供的实践背景；结果仅提示可以在后续研究或实践中进一步关注相关变量，不能据此提出具体政策或组织结论。",[f"hypothesis_evaluation:{item['id']}" for item in evals])
        elif section_type=="limitations":
            warnings=[]
            for result in package["analysis_results"]: warnings.extend(result.get("warnings") or []); warnings.extend(result.get("cautions") or [])
            for explanation in package["explanations"]: warnings.extend(explanation.get("limitations") or []); warnings.extend(explanation.get("cautions") or [])
            seen=[]
            for warning in warnings:
                warning=_clean(warning,600)
                if warning and warning not in seen: seen.append(warning)
            if seen:
                for warning in seen[:(2 if length=="short" else 5)]: add(f"本研究的一个限制是：{warning}",[f"analysis_result:{item['id']}" for item in package["analysis_results"]])
            else: add("当前证据不足以生成可靠的局限性内容。",[])
        return output or [{"text":"当前证据不足以生成可靠内容。","evidence_refs":[],"kind":"insufficient_evidence"}]

    def _validate_refs(self, paragraphs: list[dict[str, Any]], package: dict[str, Any]) -> None:
        allowed={f"analysis_result:{item['id']}" for item in package["analysis_results"]}|{f"hypothesis_evaluation:{item['id']}" for item in package["evaluations"]}|{f"finding:{item['id']}" for item in package["findings"]}|{f"literature_evidence:{item['evidence']['id']}" for item in package["literature_evidence"]}
        for paragraph in paragraphs:
            if not isinstance(paragraph,dict) or not isinstance(paragraph.get("text"),str): raise ValueError("Discussion 输出段落结构无效")
            refs=paragraph.get("evidence_refs") or []
            if not isinstance(refs,list) or any(item not in allowed for item in refs): raise ValueError("Discussion 引用了未选择或不存在的证据")

    def _validate_model(self, paragraphs: Any, package: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(paragraphs,list) or not paragraphs: raise ValueError("模型未返回段落列表")
        safe=[]
        for item in paragraphs:
            if not isinstance(item,dict) or set(item)-{"text","evidence_refs"}: raise ValueError("模型输出包含非法字段")
            text=_clean(item.get("text"),1800)
            if not text or NUMBER.search(text) or CAUSAL.search(text) or MODEL_DECISION.search(text): raise ValueError("模型输出包含未经后端评价的数字、决策或因果措辞")
            safe.append({"text":text,"evidence_refs":item.get("evidence_refs") or [],"kind":"model_commentary"})
        self._validate_refs(safe,package); return safe

    def _model_commentary(self, *, section_type: str, package: dict[str, Any], model_id: str | None) -> tuple[list[dict[str, Any]], str]:
        runtime=resolve_model(model_id)
        if not runtime: return [],"rule_based_fallback"
        refs=[]
        for key in ("analysis_results","evaluations","findings"):
            refs.extend(f"{ {'analysis_results':'analysis_result','evaluations':'hypothesis_evaluation','findings':'finding'}[key] }:{item['id']}" for item in package.get(key,[]))
        refs.extend(f"literature_evidence:{item['evidence']['id']}" for item in package.get("literature_evidence",[]))
        prompt={"section_type":section_type,"allowed_evidence_refs":refs,"hypotheses":[{"statement":item["statement"],"direction":item["direction"]} for item in package["hypotheses"]],"evaluation_decisions":[item["decision"] for item in package["evaluations"]],"literature_evidence":[{"source_location":item["evidence"]["source_location"],"claim":item["evidence"]["claim"]} for item in package["literature_evidence"]],"instructions":"输出 JSON 对象 {paragraphs:[{text,evidence_refs}]}。text 只能写谨慎的学术解释；禁止阿拉伯数字、统计数字、p/r/F/R²、作者年份、DOI、因果词、确定性因果结论，禁止新增文献或证据。evidence_refs 只能来自 allowed_evidence_refs。"}
        try:
            text=deepseek.chat_with(runtime.base_url,runtime.api_key,runtime.model,[{"role":"system","content":"你是受约束的论文 Discussion 语言助手。仅组织给定事实，不判断假设，不添加数字或新文献。"},{"role":"user","content":json.dumps(prompt,ensure_ascii=False)}],temperature=.15,max_tokens=min(runtime.max_tokens,1300),timeout=min(self.settings.deepseek_timeout,90))
            parsed=json.loads(text.strip().removeprefix("```json").removesuffix("```").strip()); return self._validate_model(parsed.get("paragraphs"),package),"configured_model"
        except Exception: return [],"rule_based_fallback"

    def generate(self, *, task_id: str, framework_id: str, section_type: str, hypothesis_ids: list[str] | None = None, finding_ids: list[str] | None = None, literature_evidence_ids: list[str] | None = None, style: dict[str, Any] | None = None, research_context: str = "", practical_context: str = "", model_id: str | None = None) -> dict[str, Any]:
        if section_type not in SECTION_TYPES: raise ValueError("不支持的 Discussion 章节")
        style=style or {}; length=str(style.get("length") or "standard"); package=self.build_fact_package(task_id=task_id,framework_id=framework_id,hypothesis_ids=hypothesis_ids,finding_ids=finding_ids,literature_evidence_ids=literature_evidence_ids,research_context=research_context,practical_context=practical_context)
        paragraphs=self._rule_paragraphs(section_type,package,length); model_paragraphs,provider=self._model_commentary(section_type=section_type,package=package,model_id=model_id)
        # The rule renderer always carries protected fact wording.  Model prose is
        # only appended after schema/ref/number/causality validation.
        if model_paragraphs and length!="short": paragraphs.extend(model_paragraphs[:1])
        self._validate_refs(paragraphs,package)
        draft={"id":f"dd_{uuid.uuid4().hex[:16]}","task_id":package["task_id"],"framework_id":framework_id,"hypothesis_ids":[item["id"] for item in package["hypotheses"]],"finding_ids":[item["id"] for item in package["findings"]],"literature_evidence_ids":[item["evidence"]["id"] for item in package["literature_evidence"]],"sections":{section_type:{"type":section_type,"paragraphs":paragraphs}},"style":{"paper_style":style.get("paper_style") or "undergraduate","tone":style.get("tone") or "formal","length":length},"status":"ready","provider":provider,"model_id":model_id,"source_snapshot":package["source_snapshot"],"fact_package":package,"created_at":_now(),"updated_at":_now()}
        self._write(draft)
        self.objects.sync(draft["task_id"])
        self.graph.rebuild_task(draft["task_id"])
        return self._with_status(draft)

    def _with_status(self, draft: dict[str, Any]) -> dict[str, Any]:
        result=dict(draft); snapshot=draft.get("source_snapshot") or {}; stale=False
        for result_id in snapshot.get("analysis_result_ids") or []:
            match=None
            for analysis in self.analyses.list(task_id=draft["task_id"]):
                try:
                    candidate=self.analyses.get_result(analysis["id"],str(result_id))
                    match=candidate; break
                except ValueError: continue
            if not match: stale=True; continue
            try:
                latest=int(self.datasets.get_dataset(str(match["dataset_id"])).get("latest_version") or match["dataset_version"])
                if latest>int(match["dataset_version"]): stale=True
            except ValueError: stale=True
        for evidence_id in snapshot.get("literature_evidence_ids") or []:
            try:
                evidence,literature=self._literature_evidence(str(evidence_id))
                if literature.get("status")=="deleted" or not evidence: stale=True
            except ValueError: stale=True
        if stale: result["status"]="stale"
        return result
    def get(self, draft_id: str) -> dict[str, Any]: return self._with_status(self._raw(draft_id))
    def list(self, task_id: str, framework_id: str | None = None) -> list[dict[str, Any]]:
        return [self._with_status(item) for item in self._all(_safe_task(task_id)) if not framework_id or item.get("framework_id")==framework_id]

    def insert(self, *, draft_id: str, section_id: str) -> list[dict[str, Any]]:
        draft=self.get(draft_id); service=DraftService(draft["task_id"],self.settings.output_dir/draft["task_id"]); inserted=[]
        with service.lock:
            document=service.load(); section=service._find_section(document,section_id)
            for section_payload in draft.get("sections",{}).values():
                text="\n\n".join(str(item.get("text") or "") for item in section_payload.get("paragraphs") or [])
                # Citations are created only upon explicit user confirmation. Their
                # labels remain dynamic from Literature ID in the shared service.
                content=[{"type":"text","text":text}]
                literature_ids=[]
                for evidence_id in draft.get("literature_evidence_ids") or []:
                    evidence,literature=self._literature_evidence(evidence_id)
                    if literature.get("status")!="deleted":
                        citation=self.literature.create_citation(task_id=draft["task_id"],literature_id=literature["id"],source_block_id="")
                        content.extend([{"type":"text","text":" "},{"type":"literature_citation","citation_id":citation["id"]}]); literature_ids.append(literature["id"])
                block={"id":service._next_paragraph_id(section),"type":"discussion","text":text,"content":content,"title":f"DiscussionDraft {draft['id']}","discussion":{"discussion_draft_id":draft["id"],"framework_id":draft["framework_id"],"hypothesis_ids":draft["hypothesis_ids"],"finding_ids":draft["finding_ids"],"literature_evidence_ids":draft["literature_evidence_ids"],"literature_ids":literature_ids,"dataset_version_ids":draft["source_snapshot"].get("dataset_version_ids",[]),"source_snapshot":draft["source_snapshot"],"evidence_refs":[ref for paragraph in section_payload.get("paragraphs") or [] for ref in paragraph.get("evidence_refs") or []]},"generated_at":_now()}
                section.setdefault("paragraphs",[]).append(block); inserted.append(block)
            service.save(document)
        raw=self._raw(draft_id); raw.update(inserted_block_ids=[item["id"] for item in inserted],inserted_at=_now(),updated_at=_now()); self._write(raw); self.objects.sync(raw["task_id"]); self.graph.rebuild_task(raw["task_id"]); return inserted
