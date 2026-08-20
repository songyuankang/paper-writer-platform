"""Read-only research dependency graph built from existing persisted artifacts.

The graph is an index, not a second business-object store.  It can always be
rebuilt from DatasetVersion, Analysis/AnalysisResult, draft blocks, Explanation,
ResearchFinding and CrossReference records created by earlier phases.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings
from app.draft.chart_runtime import walk_sections
from app.services.analysis_service import AnalysisService
from app.services.cross_reference_service import CrossReferenceService
from app.services.dataset_service import DatasetService
from app.services.research_object_service import ResearchObjectService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_task(task_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", task_id)
    if not cleaned or cleaned != task_id:
        raise ValueError("任务 ID 无效")
    return cleaned


def _version_node(dataset_id: str, version: int | str | None) -> str:
    return f"{dataset_id}:v{int(version or 0)}"


class DependencyGraphService:
    """Lazy dependency index and traversal service with explicit cycle guards."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.datasets = DatasetService(settings)
        self.analyses = AnalysisService(settings)
        self.objects = ResearchObjectService(settings)
        self.references = CrossReferenceService(settings)
        self.root = settings.db_path.parent / "dependencies"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self.root / _safe_task(task_id) / "links.json"

    def _draft_path(self, task_id: str) -> Path:
        return self.settings.output_dir / _safe_task(task_id) / "draft.json"

    def _load_draft(self, task_id: str) -> dict[str, Any]:
        path = self._draft_path(task_id)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _link(task_id: str, source_type: str, source_id: str, target_type: str, target_id: str, relation: str, source_version: int | None = None) -> dict[str, Any]:
        key = "|".join([task_id, source_type, str(source_id), str(source_version or ""), target_type, str(target_id), relation])
        return {
            "id": f"dl_{hashlib.sha1(key.encode()).hexdigest()[:18]}", "task_id": task_id,
            "source_type": source_type, "source_id": str(source_id), "source_version": source_version,
            "target_type": target_type, "target_id": str(target_id), "relation": relation,
            "created_at": _now(),
        }

    def _write(self, task_id: str, links: list[dict[str, Any]]) -> None:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": task_id, "rebuilt_at": _now(), "links": links}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_result_records(self, analysis_id: str) -> list[dict[str, Any]]:
        directory = self.analyses._dir(analysis_id) / "results"
        records: list[dict[str, Any]] = []
        for path in directory.glob("*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("id") and item.get("analysis_id") == analysis_id:
                    records.append(item)
            except json.JSONDecodeError:
                continue
        return records

    def _read_explanations(self, analysis_id: str) -> list[dict[str, Any]]:
        directory = self.settings.db_path.parent / "explanations" / analysis_id
        records: list[dict[str, Any]] = []
        for path in directory.glob("*.json") if directory.exists() else []:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return records

    def _read_findings(self, task_id: str) -> list[dict[str, Any]]:
        directory = self.settings.db_path.parent / "findings"
        records: list[dict[str, Any]] = []
        for path in directory.glob("rf_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    records.append(item)
            except json.JSONDecodeError:
                continue
        return records

    def _read_hypotheses(self, task_id: str) -> list[dict[str, Any]]:
        directory = self.settings.db_path.parent / "hypotheses" / "items"
        records: list[dict[str, Any]] = []
        for path in directory.glob("hp_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    records.append(item)
            except json.JSONDecodeError:
                continue
        return records

    def _read_evaluations(self, hypothesis_ids: set[str]) -> list[dict[str, Any]]:
        directory = self.settings.db_path.parent / "hypotheses" / "evaluations"
        records: list[dict[str, Any]] = []
        for path in directory.glob("hp_*/he_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("hypothesis_id") in hypothesis_ids:
                    records.append(item)
            except json.JSONDecodeError:
                continue
        return records

    def _read_frameworks(self, task_id: str) -> list[dict[str, Any]]:
        directory = self.settings.db_path.parent / "discussion_frameworks"
        records: list[dict[str, Any]] = []
        for path in directory.glob("df_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    records.append(item)
            except json.JSONDecodeError:
                continue
        return records

    @staticmethod
    def _block_type(block: dict[str, Any]) -> str | None:
        if block.get("type") == "table":
            return "table"
        if block.get("type") in {"chart", "figure"}:
            return "figure"
        return None

    def rebuild_task(self, task_id: str) -> list[dict[str, Any]]:
        """Rebuild a task-local index from authoritative stored records.

        This is intentionally safe for legacy data: absent metadata produces no
        speculative link and never rewrites the underlying research artifact.
        """
        task_id = _safe_task(task_id)
        # A task may start with Dataset/Analysis/Hypothesis before a paper draft
        # exists.  Graph rebuild remains useful in that state and simply omits
        # draft-owned Table/Figure/CrossReference nodes.
        try:
            self.objects.renumber_document_references(task_id)
            self.objects.sync(task_id)
        except ValueError:
            pass
        links: list[dict[str, Any]] = []
        analyses = [self.analyses.get(item["id"]) for item in self.analyses.list(task_id=task_id)]
        results: dict[str, dict[str, Any]] = {}
        for analysis in analyses:
            dataset_id, version = str(analysis.get("dataset_id") or ""), analysis.get("dataset_version")
            if dataset_id and version:
                links.append(self._link(task_id, "dataset_version", _version_node(dataset_id, version), "analysis", analysis["id"], "derived_from", int(version)))
            for result in self._read_result_records(analysis["id"]):
                results[str(result["id"])] = result
                links.append(self._link(task_id, "analysis", analysis["id"], "analysis_result", result["id"], "derived_from", result.get("dataset_version")))
                if result.get("dataset_id") and result.get("dataset_version"):
                    links.append(self._link(task_id, "dataset_version", _version_node(str(result["dataset_id"]), result["dataset_version"]), "analysis_result", result["id"], "derived_from", int(result["dataset_version"])))
            for explanation in self._read_explanations(analysis["id"]):
                result_id = str(explanation.get("analysis_result_id") or "")
                if result_id:
                    links.append(self._link(task_id, "analysis_result", result_id, "explanation", explanation.get("id", ""), "explains", explanation.get("dataset_version")))

        draft = self._load_draft(task_id)
        block_by_object: dict[str, dict[str, Any]] = {}
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                artifact_type = self._block_type(block)
                reference = block.get("analysis") or {}
                result_id = str(reference.get("analysis_result_id") or "")
                if artifact_type and result_id and block.get("id"):
                    links.append(self._link(task_id, "analysis_result", result_id, artifact_type, str(block["id"]), "renders", reference.get("dataset_version")))
                if artifact_type and block.get("id"):
                    block_by_object[str(block["id"])] = {"block": block, "type": artifact_type, "section": section}

        findings = self._read_findings(task_id)
        for finding in findings:
            result_id = str(finding.get("analysis_result_id") or "")
            if result_id:
                links.append(self._link(task_id, "analysis_result", result_id, "finding", finding["id"], "derived_from", finding.get("dataset_version")))
            explanation_id = str(finding.get("explanation_id") or "")
            if explanation_id:
                links.append(self._link(task_id, "explanation", explanation_id, "finding", finding["id"], "explains", finding.get("dataset_version")))

        try:
            object_index = {item["id"]: item for item in self.objects.list(task_id)}
            references = self.references.list(task_id)
        except ValueError:
            object_index, references = {}, []
        for reference in references:
            target = object_index.get(str(reference.get("target_object_id") or ""))
            if target and target.get("source_id") in block_by_object:
                source = block_by_object[target["source_id"]]
                links.append(self._link(task_id, source["type"], target["source_id"], "cross_reference", reference["id"], "references"))
            for finding in findings:
                if str(reference.get("target_object_id") or "") in {str(value) for value in finding.get("research_object_ids") or []}:
                    links.append(self._link(task_id, "finding", finding["id"], "cross_reference", reference["id"], "references"))

        # Phase 7A nodes intentionally reuse this graph.  They retain only IDs
        # and provenance links; their factual evidence remains in AnalysisResult.
        hypotheses = self._read_hypotheses(task_id)
        evaluations = self._read_evaluations({str(item.get("id")) for item in hypotheses})
        for hypothesis in hypotheses:
            for analysis_id in hypothesis.get("analysis_ids") or []:
                links.append(self._link(task_id, "analysis", str(analysis_id), "hypothesis", hypothesis["id"], "references"))
        for evaluation in evaluations:
            links.append(self._link(task_id, "hypothesis", evaluation["hypothesis_id"], "hypothesis_evaluation", evaluation["id"], "derived_from", evaluation.get("dataset_version")))
            links.append(self._link(task_id, "analysis_result", evaluation["analysis_result_id"], "hypothesis_evaluation", evaluation["id"], "derived_from", evaluation.get("dataset_version")))
        for framework in self._read_frameworks(task_id):
            for evaluation_id in framework.get("evaluation_ids") or []:
                links.append(self._link(task_id, "hypothesis_evaluation", str(evaluation_id), "discussion_framework", framework["id"], "explains"))
            for finding_id in framework.get("finding_ids") or []:
                links.append(self._link(task_id, "finding", str(finding_id), "discussion_framework", framework["id"], "explains"))

        # Deterministic de-duplication makes repeated lazy rebuilds idempotent.
        unique = {item["id"]: item for item in links}
        ordered = sorted(unique.values(), key=lambda item: (item["source_type"], item["source_id"], item["target_type"], item["target_id"], item["relation"]))
        self._write(task_id, ordered)
        return ordered

    def _latest_version(self, dataset_id: str) -> int | None:
        try:
            return int(self.datasets.get_dataset(dataset_id).get("latest_version") or 0)
        except ValueError:
            return None

    def _node(self, task_id: str, node_type: str, node_id: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        source = source or {}
        title = str(source.get("title") or source.get("name") or node_id)
        version = source.get("dataset_version") or source.get("version") or source.get("source_version")
        fingerprint = source.get("data_fingerprint") or source.get("fingerprint")
        status = str(source.get("status") or "current")
        dataset_id = str(source.get("dataset_id") or "")
        if dataset_id and version is not None:
            latest = self._latest_version(dataset_id)
            if latest is None:
                status = "missing"
            elif int(version) < latest and node_type != "cross_reference":
                status = "stale" if node_type == "analysis" else "stale_source"
        return {"id": node_id, "type": node_type, "title": title, "status": status, "version": version, "fingerprint": fingerprint}

    def _records(self, task_id: str) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        analyses = {item["id"]: self.analyses.get(item["id"]) for item in self.analyses.list(task_id=task_id)}
        results = {item["id"]: item for analysis_id in analyses for item in self._read_result_records(analysis_id)}
        explanations = {item["id"]: item for analysis_id in analyses for item in self._read_explanations(analysis_id)}
        findings = {item["id"]: item for item in self._read_findings(task_id)}
        hypotheses = {item["id"]: item for item in self._read_hypotheses(task_id)}
        evaluations = {item["id"]: item for item in self._read_evaluations(set(hypotheses))}
        frameworks = {item["id"]: item for item in self._read_frameworks(task_id)}
        records: dict[tuple[str, str], dict[str, Any]] = {}
        for dataset in self.datasets.list_datasets(task_id):
            try:
                metadata = self.datasets.get_dataset(str(dataset["id"]))
                for version in metadata.get("versions") or []:
                    record = dict(version); record["title"] = f"{metadata.get('name') or dataset['id']} v{version.get('version')}"; record["dataset_id"] = dataset["id"]
                    records[("dataset_version", _version_node(str(dataset["id"]), version.get("version")))] = record
            except ValueError:
                continue
        for item in analyses.values(): records[("analysis", item["id"])] = item
        for item in results.values(): records[("analysis_result", item["id"])] = item
        for item in explanations.values(): records[("explanation", item["id"])] = item
        for item in findings.values(): records[("finding", item["id"])] = item
        for item in hypotheses.values(): records[("hypothesis", item["id"])] = item
        for item in evaluations.values(): records[("hypothesis_evaluation", item["id"])] = item
        for item in frameworks.values():
            record = dict(item)
            if any(evaluations.get(str(evaluation_id), {}).get("dataset_version") and self._latest_version(str(evaluations[str(evaluation_id)].get("dataset_id"))) and int(evaluations[str(evaluation_id)].get("dataset_version")) < int(self._latest_version(str(evaluations[str(evaluation_id)].get("dataset_id"))) or 0) for evaluation_id in item.get("evaluation_ids") or []):
                record["status"] = "stale_source"
            records[("discussion_framework", item["id"])] = record
        draft = self._load_draft(task_id)
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                kind = self._block_type(block)
                if kind and block.get("id"):
                    record = dict(block); record["dataset_id"] = (block.get("analysis") or {}).get("dataset_id"); record["dataset_version"] = (block.get("analysis") or {}).get("dataset_version"); record["data_fingerprint"] = (block.get("analysis") or {}).get("data_fingerprint")
                    records[(kind, str(block["id"]))] = record
        try:
            references = self.references.list(task_id)
        except ValueError:
            references = []
        for item in references:
            records[("cross_reference", item["id"])] = item
        return records, results, explanations, findings

    def _traverse(self, links: list[dict[str, Any]], source_type: str, source_id: str, direction: str) -> list[dict[str, Any]]:
        mapping: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for link in links:
            key = (link["source_type"], link["source_id"]) if direction == "downstream" else (link["target_type"], link["target_id"])
            mapping.setdefault(key, []).append(link)
        start = (source_type, source_id)
        seen = {start}; queue: deque[tuple[str, str]] = deque([start]); output: list[dict[str, Any]] = []
        while queue:
            current = queue.popleft()
            for link in mapping.get(current, []):
                nxt = (link["target_type"], link["target_id"]) if direction == "downstream" else (link["source_type"], link["source_id"])
                if nxt in seen:
                    continue
                seen.add(nxt); queue.append(nxt); output.append(link)
        return output

    def get_downstream(self, task_id: str, source_type: str, source_id: str) -> list[dict[str, Any]]:
        return self._traverse(self.rebuild_task(task_id), source_type, source_id, "downstream")

    def get_upstream(self, task_id: str, target_type: str, target_id: str) -> list[dict[str, Any]]:
        return self._traverse(self.rebuild_task(task_id), target_type, target_id, "upstream")

    def get_impact(self, *, task_id: str, dataset_id: str, version: int) -> dict[str, Any]:
        links = self.rebuild_task(task_id)
        records, _, _, _ = self._records(task_id)
        source_id = _version_node(dataset_id, version)
        descendants = self._traverse(links, "dataset_version", source_id, "downstream")
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in ("analyses", "results", "tables", "figures", "explanations", "findings", "references")}
        key_for_type = {"analysis": "analyses", "analysis_result": "results", "table": "tables", "figure": "figures", "explanation": "explanations", "finding": "findings", "cross_reference": "references"}
        seen: set[tuple[str, str]] = set()
        for link in descendants:
            node_type, node_id = link["target_type"], link["target_id"]
            marker = (node_type, node_id)
            if marker in seen or node_type not in key_for_type:
                continue
            seen.add(marker)
            grouped[key_for_type[node_type]].append(self._node(task_id, node_type, node_id, records.get(marker)))
        try:
            version_info = self.datasets.get_version(dataset_id, version, include_rows=False)
            source = self._node(task_id, "dataset_version", source_id, {"title": f"{self.datasets.get_dataset(dataset_id).get('name') or dataset_id} v{version}", "version": version, "fingerprint": version_info.get("fingerprint"), "dataset_id": dataset_id})
        except ValueError:
            source = {"id": source_id, "type": "dataset_version", "title": source_id, "status": "missing", "version": version, "fingerprint": None}
        return {"source": source, **grouped, "links": descendants}

    def evidence(self, finding_id: str) -> dict[str, Any]:
        finding_path = self.settings.db_path.parent / "findings" / f"{finding_id}.json"
        if not finding_path.is_file():
            raise ValueError("未找到 ResearchFinding")
        finding = json.loads(finding_path.read_text(encoding="utf-8")); task_id = str(finding.get("task_id") or "")
        self.rebuild_task(task_id)
        records, results, explanations, _ = self._records(task_id)
        analysis = self.analyses.get(str(finding["analysis_id"]))
        result = results.get(str(finding["analysis_result_id"]))
        explanation = explanations.get(str(finding["explanation_id"]))
        object_ids = {str(item) for item in finding.get("research_object_ids") or []}
        object_index = {item["id"]: item for item in self.objects.list(task_id)}
        block_ids = {item.get("source_id") for key, item in object_index.items() if key in object_ids}
        tables = [self._node(task_id, "table", block_id, records.get(("table", str(block_id)))) for block_id in block_ids if ("table", str(block_id)) in records]
        figures = [self._node(task_id, "figure", block_id, records.get(("figure", str(block_id)))) for block_id in block_ids if ("figure", str(block_id)) in records]
        references = [self._node(task_id, "cross_reference", item["id"], item) for item in self.references.list(task_id) if str(item.get("target_object_id") or "") in object_ids]
        dataset = None
        try: dataset = self.datasets.get_version(str(finding["dataset_id"]), int(finding["dataset_version"]), include_rows=False)
        except ValueError: dataset = {"id": finding.get("dataset_version_id"), "status": "missing"}
        return {"finding": self._node(task_id, "finding", finding_id, finding), "dataset": dataset, "analysis": self._node(task_id, "analysis", analysis["id"], analysis), "result": self._node(task_id, "analysis_result", str(finding["analysis_result_id"]), result), "explanation": self._node(task_id, "explanation", str(finding["explanation_id"]), explanation), "tables": tables, "figures": figures, "cross_references": references}

    def results_center(self, task_id: str, kind: str | None = None) -> dict[str, Any]:
        self.rebuild_task(task_id)
        records, _, _, _ = self._records(task_id)
        items = [self._node(task_id, node_type, node_id, record) for (node_type, node_id), record in records.items()]
        if kind:
            aliases = {"dataset": "dataset_version", "result": "analysis_result", "reference": "cross_reference"}
            expected = aliases.get(kind, kind)
            items = [item for item in items if item["type"] == expected]
        return {"items": sorted(items, key=lambda item: (item["type"], item["title"], item["id"])), "links": self.rebuild_task(task_id)}

    def export_warnings(self, task_id: str) -> list[str]:
        impact_warnings: list[str] = []
        _, _, _, findings = self._records(task_id)
        for finding in findings.values():
            latest = self._latest_version(str(finding.get("dataset_id") or ""))
            if latest and int(finding.get("dataset_version") or latest) < latest:
                impact_warnings.append(f"ResearchFinding「{finding.get('title') or finding.get('id')}」基于旧 DatasetVersion v{finding.get('dataset_version')}，当前最新为 v{latest}。")
        draft = self._load_draft(task_id)
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                ref = block.get("analysis") or block.get("research_finding") or {}
                dataset_id, version = str(ref.get("dataset_id") or ""), ref.get("dataset_version")
                latest = self._latest_version(dataset_id) if dataset_id and version is not None else None
                if latest and int(version) < latest and block.get("type") in {"table", "chart", "figure", "finding"}:
                    impact_warnings.append(f"{block.get('type')}「{block.get('title') or block.get('id')}」基于旧 DatasetVersion v{version}，当前最新为 v{latest}。")
        return sorted(set(impact_warnings))
