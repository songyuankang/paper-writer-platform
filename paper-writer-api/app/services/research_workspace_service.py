"""Product-facing, summary-only Research Workspace aggregation.

The workspace intentionally composes authoritative services instead of creating a
second research index.  Dataset rows, AnalysisResult payloads and LiteratureEvidence
body text remain behind their existing detail APIs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.discussion_writer_service import DiscussionWriterService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.research_finding_service import ResearchFindingService
from app.services.research_object_service import ResearchObjectService


WORKFLOW_TEMPLATES = [
    {
        "id": "survey",
        "name": "问卷调查",
        "description": "从问卷数据质量检查开始，按需完成描述统计、相关、组间比较与回归。",
        "steps": ["data", "descriptive", "correlation", "group_comparison", "regression", "hypothesis", "results", "discussion", "paper"],
    },
    {
        "id": "experiment",
        "name": "实验研究",
        "description": "适合围绕实验条件与结果变量进行分组比较、假设与讨论的研究。",
        "steps": ["data", "descriptive", "group_comparison", "hypothesis", "results", "literature", "discussion", "paper"],
    },
    {
        "id": "empirical",
        "name": "实证研究",
        "description": "适合使用真实数据进行描述、关联、预测与证据链写作的研究。",
        "steps": ["data", "descriptive", "correlation", "regression", "hypothesis", "results", "literature", "discussion", "paper"],
    },
    {
        "id": "custom",
        "name": "自定义研究",
        "description": "从任意研究能力开始，自由跳过不适用步骤。",
        "steps": ["data", "analysis", "results", "literature", "discussion", "paper"],
    },
]


def _safe_task(task_id: str) -> str:
    if not task_id or len(task_id) > 128:
        raise ValueError("任务 ID 无效")
    return task_id


def _compact(value: str | None, limit: int = 160) -> str:
    return " ".join(str(value or "").split())[:limit]


def _updated(values: list[dict[str, Any]]) -> str | None:
    timestamps = [str(item.get("updated_at") or item.get("created_at") or "") for item in values]
    return max(timestamps) if timestamps else None


class ResearchWorkspaceService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.datasets = DatasetService(settings)
        self.analyses = AnalysisService(settings)
        self.objects = ResearchObjectService(settings)
        self.graph = DependencyGraphService(settings)
        self.hypotheses = HypothesisService(settings)
        self.findings = ResearchFindingService(settings)
        self.literature = LiteratureService(settings)
        self.discussion = DiscussionWriterService(settings)

    @staticmethod
    def templates() -> list[dict[str, Any]]:
        return [dict(item) for item in WORKFLOW_TEMPLATES]

    def _project(self, task_id: str) -> dict[str, Any]:
        draft = DraftService(task_id, self.settings.output_dir / task_id).load()
        meta = draft.get("meta") or {}
        sections = [
            {"id": str(section.get("id") or ""), "title": _compact(section.get("title"), 90), "number": _compact(section.get("number"), 24)}
            for section in draft.get("sections") or []
            if section.get("id")
        ]
        return {
            "task_id": task_id,
            "title": _compact(draft.get("title"), 180) or "未命名论文",
            "paper_type": _compact(meta.get("paper_type"), 80),
            "updated_at": draft.get("updated_at") or _updated(draft.get("sections") or []),
            "has_paper": bool(draft),
            "sections": sections,
        }

    def _dataset_summary(self, task_id: str) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for dataset in self.datasets.list_datasets(task_id):
            items.append({
                "id": dataset.get("id"),
                "name": _compact(dataset.get("name")) or "研究数据集",
                "latest_version": dataset.get("latest_version"),
                "row_count": dataset.get("row_count"),
                "column_count": dataset.get("column_count"),
                "updated_at": dataset.get("updated_at") or dataset.get("created_at"),
                "status": "ready",
            })
        return {"count": len(items), "latest_version": max((int(item["latest_version"] or 0) for item in items), default=0) or None, "updated_at": _updated(items), "items": items}

    def _analysis_summary(self, task_id: str) -> dict[str, Any]:
        items = [{
            "id": item.get("id"), "name": _compact(item.get("name")) or "统计分析", "type": item.get("type"),
            "latest_result_id": item.get("last_result_id"), "status": item.get("status") or "ready", "updated_at": item.get("updated_at") or item.get("created_at"),
        } for item in self.analyses.list(task_id=task_id)]
        return {
            "count": len(items),
            "stale_count": sum(item["status"] in {"stale", "stale_source"} for item in items),
            "failed_count": sum(item["status"] == "failed" for item in items),
            "updated_at": _updated(items), "items": items,
        }

    def _object_summary(self, task_id: str, object_type: str, label: str) -> dict[str, Any]:
        records = [item for item in self.objects.sync(task_id) if item.get("type") == object_type]
        draft = DraftService(task_id, self.settings.output_dir / task_id).load()
        source_status: dict[str, str] = {}
        wanted = {"chart", "figure"} if object_type == "figure" else {"table"}
        for section in draft.get("sections") or []:
            for block in section.get("paragraphs") or []:
                if block.get("type") not in wanted:
                    continue
                reference = block.get("analysis") or block.get("research_finding") or {}
                dataset_id, version = str(reference.get("dataset_id") or ""), reference.get("dataset_version")
                if not dataset_id or version is None:
                    continue
                try:
                    latest = int(self.datasets.get_dataset(dataset_id).get("latest_version") or version)
                    if int(version) < latest:
                        source_status[str(block.get("id") or "")] = "stale"
                except (ValueError, TypeError):
                    source_status[str(block.get("id") or "")] = "stale"
        items = [{
            "id": item.get("source_id"), "title": _compact(item.get("title")) or label,
            "number_label": item.get("number_label"), "status": source_status.get(str(item.get("source_id") or ""), item.get("status") or "ready"),
            "updated_at": item.get("updated_at") or item.get("created_at"),
        } for item in records]
        return {
            "count": len(items),
            "stale_count": sum(item["status"] in {"stale", "stale_source"} for item in items),
            "failed_count": sum(item["status"] == "failed" for item in items),
            "updated_at": _updated(items), "items": items,
        }

    def _hypothesis_summary(self, task_id: str) -> dict[str, Any]:
        hypotheses = self.hypotheses.list(task_id)
        evaluations = [evaluation for hypothesis in hypotheses for evaluation in self.hypotheses.evaluations(hypothesis["id"])]
        stale = sum(str(item.get("data_status") or "") in {"stale_source", "missing"} for item in evaluations)
        decisions: dict[str, int] = {}
        for item in evaluations:
            decision = str(item.get("decision") or "pending")
            decisions[decision] = decisions.get(decision, 0) + 1
        return {
            "count": len(hypotheses), "evaluation_count": len(evaluations), "needs_refresh_count": stale,
            "decisions": decisions, "updated_at": _updated([*hypotheses, *evaluations]),
            "items": [{"id": item.get("id"), "title": _compact(item.get("title")) or "研究假设", "latest_evaluation_id": item.get("latest_evaluation_id"), "status": item.get("status") or "pending", "updated_at": item.get("updated_at") or item.get("created_at")} for item in hypotheses],
        }

    def _literature_summary(self, task_id: str) -> dict[str, Any]:
        literature = self.literature.list(task_id)
        citations = self.literature.citations(task_id)
        return {
            "count": len(literature), "citation_count": len(citations),
            "broken_citations": sum(item.get("status") == "broken" for item in citations),
            "updated_at": _updated(literature),
            "items": [{"id": item.get("id"), "title": _compact(item.get("title")) or "学术文献", "year": item.get("year"), "updated_at": item.get("updated_at") or item.get("created_at")} for item in literature],
        }

    def _discussion_summary(self, task_id: str) -> dict[str, Any]:
        records = self.discussion.list(task_id)
        items = [{
            "id": item.get("id"), "sections": sorted((item.get("sections") or {}).keys()),
            "status": item.get("status") or "ready", "updated_at": item.get("updated_at") or item.get("created_at"),
        } for item in records]
        return {"count": len(items), "stale_count": sum(item["status"] == "stale" for item in items), "updated_at": _updated(items), "items": items}

    @staticmethod
    def _issue(code: str, status: str, count: int, message: str, href: str) -> dict[str, Any]:
        return {"code": code, "status": status, "count": count, "message": message, "href": href}

    def get(self, task_id: str) -> dict[str, Any]:
        task_id = _safe_task(task_id)
        project = self._project(task_id)
        datasets = self._dataset_summary(task_id)
        analyses = self._analysis_summary(task_id)
        charts = self._object_summary(task_id, "figure", "图表")
        tables = self._object_summary(task_id, "table", "统计结果表")
        hypotheses = self._hypothesis_summary(task_id)
        findings = self._object_summary(task_id, "finding", "研究结果")
        literature = self._literature_summary(task_id)
        discussion = self._discussion_summary(task_id)
        issues: list[dict[str, Any]] = []
        if analyses["stale_count"]:
            issues.append(self._issue("stale_analyses", "stale", analyses["stale_count"], f"{analyses['stale_count']} 个分析需要重新运行", f"/research/analysis?task_id={task_id}"))
        if analyses["failed_count"]:
            issues.append(self._issue("failed_analyses", "failed", analyses["failed_count"], f"{analyses['failed_count']} 个分析未能完成", f"/research/analysis?task_id={task_id}"))
        if charts["stale_count"]:
            issues.append(self._issue("stale_figures", "stale", charts["stale_count"], f"{charts['stale_count']} 张图表需要更新", f"/lab/{task_id}"))
        if tables["stale_count"]:
            issues.append(self._issue("stale_tables", "stale", tables["stale_count"], f"{tables['stale_count']} 个统计结果表需要更新", f"/research/results?task_id={task_id}"))
        if hypotheses["needs_refresh_count"]:
            issues.append(self._issue("stale_evaluations", "stale", hypotheses["needs_refresh_count"], f"{hypotheses['needs_refresh_count']} 个假设评价需要基于最新数据复核", f"/research/discussion/hypotheses?task_id={task_id}"))
        if discussion["stale_count"]:
            issues.append(self._issue("stale_discussion", "stale", discussion["stale_count"], f"{discussion['stale_count']} 份讨论草稿需要检查来源更新", f"/research/discussion?task_id={task_id}"))
        if literature["broken_citations"]:
            issues.append(self._issue("broken_citations", "broken", literature["broken_citations"], f"{literature['broken_citations']} 个正文引用对象不存在", f"/research/literature?task_id={task_id}"))
        # Rebuild existing graph only for a relationship count.  The workspace does
        # not create or persist its own dependency records.
        links = self.graph.rebuild_task(task_id)
        return {
            "project": project, "datasets": datasets, "analyses": analyses, "charts": charts, "tables": tables,
            "hypotheses": hypotheses, "findings": findings, "literature": literature, "discussion": discussion,
            "issues": issues,
            "impact_summary": {
                "stale_analyses": analyses["stale_count"], "stale_figures": charts["stale_count"],
                "broken_citations": literature["broken_citations"], "relationship_count": len(links),
                "needs_attention": sum(item["count"] for item in issues), "href": f"/research/results?task_id={task_id}",
            },
            "templates": self.templates(), "generated_at": datetime.now(timezone.utc).isoformat(),
        }
