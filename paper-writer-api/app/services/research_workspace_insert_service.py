"""Explicit, preview-first insertion from Research Workspace into a paper draft."""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from app.config import Settings
from app.draft.analysis_blocks import insert_analysis_result
from app.draft.chart_runtime import walk_sections
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.discussion_writer_service import DiscussionWriterService
from app.services.hypothesis_service import HypothesisService
from app.services.research_finding_service import ResearchFindingService
from app.services.research_object_service import ResearchObjectService


INSERT_TYPES = {"analysis_result", "table", "figure", "finding", "discussion_draft", "hypothesis_evaluation"}


def _safe_task(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id or ""):
        raise ValueError("任务 ID 无效")
    return task_id


def _compact(value: object, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


class ResearchWorkspaceInsertService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.analyses = AnalysisService(settings)
        self.hypotheses = HypothesisService(settings)
        self.findings = ResearchFindingService(settings)
        self.discussion = DiscussionWriterService(settings)
        self.objects = ResearchObjectService(settings)
        self.graph = DependencyGraphService(settings)

    def _draft(self, task_id: str) -> DraftService:
        service = DraftService(task_id, self.settings.output_dir / task_id)
        if not service.load():
            raise ValueError("当前项目尚未生成论文，暂不能加入论文")
        return service

    def _section(self, draft: dict[str, Any], section_id: str) -> dict[str, Any]:
        for section in walk_sections(draft.get("sections") or []):
            if section.get("id") == section_id:
                return section
        raise ValueError("未找到论文目标章节")

    def _find_block(self, draft: dict[str, Any], source_id: str, expected: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                matches = block.get("id") == source_id and ((expected == "table" and block.get("type") == "table") or (expected == "figure" and block.get("type") in {"chart", "figure"}))
                if matches:
                    return section, block
        raise ValueError("未找到可加入论文的研究对象")

    def _result(self, task_id: str, analysis_id: str, result_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        analysis = self.analyses.get(analysis_id)
        if analysis.get("task_id") != task_id:
            raise ValueError("Analysis 不属于当前项目")
        result = self.analyses.get_result(analysis_id, result_id)
        if result.get("status") != "ready":
            raise ValueError("仅可加入已成功完成的分析结果")
        return analysis, result

    def _evaluation(self, task_id: str, evaluation_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for hypothesis in self.hypotheses.list(task_id):
            for evaluation in self.hypotheses.evaluations(hypothesis["id"]):
                if evaluation.get("id") == evaluation_id:
                    return hypothesis, evaluation
        raise ValueError("未找到当前项目的假设评价")

    def _describe(self, *, task_id: str, source_type: str, source_id: str, section_id: str, analysis_id: str = "", artifact: str = "table") -> dict[str, Any]:
        if source_type not in INSERT_TYPES:
            raise ValueError("不支持的研究对象类型")
        service = self._draft(task_id)
        draft = service.load()
        section = self._section(draft, section_id)
        description: dict[str, Any] = {"source_type": source_type, "source_id": source_id, "section_id": section_id, "section_title": _compact(section.get("title")) or "未命名章节", "artifact": artifact}
        if source_type == "analysis_result":
            analysis, result = self._result(task_id, analysis_id, source_id)
            if artifact not in {"table", "chart", "actual_predicted", "residual", "coefficient"}:
                raise ValueError("不支持的分析结果呈现形式")
            description.update(title=_compact(analysis.get("name")) or "统计分析结果", source_summary=f"{_compact((result.get('result') or {}).get('method')) or '统计'}分析结果", will_insert="统计结果表" if artifact == "table" else "图表")
        elif source_type == "finding":
            finding = self.findings.get(source_id)
            if finding.get("task_id") != task_id:
                raise ValueError("ResearchFinding 不属于当前项目")
            description.update(title=_compact(finding.get("title")) or "研究结果", source_summary="已有研究结果写作稿", will_insert="研究结果")
        elif source_type == "discussion_draft":
            discussion = self.discussion.get(source_id)
            if discussion.get("task_id") != task_id:
                raise ValueError("DiscussionDraft 不属于当前项目")
            if discussion.get("status") == "stale":
                raise ValueError("讨论草稿来源已更新，请先检查后再加入论文")
            description.update(title="讨论草稿", source_summary="受保护的讨论写作版本", will_insert="讨论")
        elif source_type == "hypothesis_evaluation":
            hypothesis, evaluation = self._evaluation(task_id, source_id)
            description.update(title=_compact(hypothesis.get("title")) or "假设评价", source_summary="已完成的假设评价", will_insert="假设评价摘要", decision=evaluation.get("decision"))
        else:
            _, block = self._find_block(draft, source_id, source_type)
            description.update(title=_compact(block.get("title")) or ("统计结果表" if source_type == "table" else "图表"), source_summary="当前论文中的研究对象", will_insert="统计结果表副本" if source_type == "table" else "图表副本")
        return description

    def preview(self, *, task_id: str, source_type: str, source_id: str, section_id: str, analysis_id: str = "", artifact: str = "table") -> dict[str, Any]:
        task_id = _safe_task(task_id)
        description = self._describe(task_id=task_id, source_type=source_type, source_id=source_id, section_id=section_id, analysis_id=analysis_id, artifact=artifact)
        return {"requires_confirmation": True, "preview": description}

    def insert(self, *, task_id: str, source_type: str, source_id: str, section_id: str, analysis_id: str = "", artifact: str = "table") -> dict[str, Any]:
        task_id = _safe_task(task_id)
        description = self._describe(task_id=task_id, source_type=source_type, source_id=source_id, section_id=section_id, analysis_id=analysis_id, artifact=artifact)
        if source_type == "analysis_result":
            analysis, result = self._result(task_id, analysis_id, source_id)
            inserted = insert_analysis_result(task_id=task_id, analysis=analysis, result=result, section_id=section_id, artifact=artifact, storage_settings=self.settings)
            return {"preview": description, "inserted": inserted}
        if source_type == "finding":
            block = self.findings.insert(finding_id=source_id, section_id=section_id)
            return {"preview": description, "inserted": {"block": block}}
        if source_type == "discussion_draft":
            blocks = self.discussion.insert(draft_id=source_id, section_id=section_id)
            return {"preview": description, "inserted": {"blocks": blocks}}
        service = self._draft(task_id)
        with service.lock:
            draft = service.load()
            section = self._section(draft, section_id)
            if source_type == "hypothesis_evaluation":
                hypothesis, evaluation = self._evaluation(task_id, source_id)
                decision_labels = {"supported": "获得统计支持", "not_supported": "未获得统计支持", "insufficient_evidence": "证据不足", "inconclusive": "结果不确定"}
                block = {
                    "id": f"{section_id}-evaluation-{uuid.uuid4().hex[:8]}", "type": "p",
                    "title": "假设评价", "text": f"{_compact(hypothesis.get('title')) or '该假设'}的当前评价为“{decision_labels.get(str(evaluation.get('decision')), '结果不确定')}”。",
                    "hypothesis_evaluation": {"hypothesis_id": hypothesis["id"], "evaluation_id": evaluation["id"], "analysis_id": evaluation.get("analysis_id"), "analysis_result_id": evaluation.get("analysis_result_id"), "dataset_version_id": evaluation.get("dataset_version_id")},
                }
            else:
                _, source_block = self._find_block(draft, source_id, source_type)
                block = copy.deepcopy(source_block)
                block["id"] = f"{section_id}-{source_type}-{uuid.uuid4().hex[:8]}"
                block["workspace_source_id"] = source_id
                block["title"] = _compact(source_block.get("title")) or description["title"]
                block["updated_at"] = None
            section.setdefault("paragraphs", []).append(block)
            self.objects.renumber_document_references(task_id, draft)
            service.save(draft)
        self.graph.rebuild_task(task_id)
        return {"preview": description, "inserted": {"block": block}}
