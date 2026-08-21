"""全文生成使用的任务级可视化计划与去重服务。

本模块只负责规划、生命周期和唯一性控制；真正的表格、图表、证据、
FigureBlock、ChartVersion 与 DOCX 渲染均继续复用既有服务。计划文件独立
保存于任务输出目录，避免被某个章节循环覆盖。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.dataset_service import DatasetService


PLAN_STATUSES = {"planned", "generated", "inserted", "skipped", "stale", "broken"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normal(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _clean(value).lower())


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _walk_sections(sections: list[dict[str, Any]]):
    for section in sections:
        yield section
        yield from _walk_sections(section.get("children") or [])


class VisualizationPlanService:
    """Persist and execute-safe task-level visualization planning metadata."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.datasets = DatasetService(settings)

    def _path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", str(task_id))
        if not safe or safe != task_id:
            raise ValueError("任务 ID 无效")
        return self.settings.output_dir / task_id / "visualization_plan.json"

    def _write(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = _now()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def get(self, task_id: str) -> dict[str, Any] | None:
        path = self._path(task_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("全文可视化计划文件格式无效") from exc
        if payload.get("task_id") != task_id:
            raise ValueError("全文可视化计划任务不匹配")
        return payload

    @staticmethod
    def _section_text(section: dict[str, Any]) -> str:
        return _clean(f"{section.get('number', '')} {section.get('title', '')} {section.get('gist', '')}", 1000)

    @classmethod
    def _first_matching(cls, sections: list[dict[str, Any]], terms: tuple[str, ...]) -> dict[str, Any] | None:
        for section in sections:
            text = cls._section_text(section).lower()
            if any(term.lower() in text for term in terms):
                return section
        return None

    def _experiment_dataset(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Return only a task-owned DatasetVersion with two numeric fields."""
        for summary in self.datasets.list_datasets(task_id):
            try:
                version = self.datasets.get_version(str(summary["id"]), int(summary.get("latest_version") or 0), include_rows=False)
            except (ValueError, TypeError):
                continue
            numeric = [column.get("name") for column in version.get("schema") or [] if column.get("type") == "numeric"]
            if len(numeric) >= 2 and int(version.get("row_count") or 0) >= 2:
                return summary, version
        return None

    @staticmethod
    def _item(*, section: dict[str, Any], purpose: str, asset_kind: str, chart_kind: str = "", table_type: str = "", dataset: dict[str, Any] | None = None) -> dict[str, Any]:
        item_id = f"vpi_{uuid.uuid4().hex[:16]}"
        dataset_ids = [str(dataset.get("dataset_id"))] if dataset and dataset.get("dataset_id") else []
        dataset_versions = [int(dataset.get("version"))] if dataset and dataset.get("version") is not None else []
        identity = {
            "purpose": purpose,
            "asset_kind": asset_kind,
            "chart_kind": chart_kind,
            "table_type": table_type,
            "dataset_ids": dataset_ids,
            "dataset_versions": dataset_versions,
        }
        return {
            "id": item_id,
            "status": "planned",
            "target_section_id": str(section["id"]),
            "target_section_label": VisualizationPlanService._section_text(section),
            "purpose": purpose,
            "asset_kind": asset_kind,
            "chart_kind": chart_kind or None,
            "table_type": table_type or None,
            "insertion_anchor": "section_end_after_generated_body",
            "evidence_ids": [],
            "dataset_ids": dataset_ids,
            "dataset_versions": dataset_versions,
            "candidate_id": None,
            "inserted_block_id": None,
            "source_signature": None,
            "dedupe_key": _hash(identity),
            "created_at": _now(),
            "updated_at": _now(),
            "events": [{"at": _now(), "status": "planned", "reason": "已依据章节目的建立全文级唯一可视化计划。"}],
        }

    def build(self, task_id: str, draft: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
        """Create one deterministic plan for the whole paper, or reuse it on resume."""
        existing = self.get(task_id)
        if existing and not replace:
            return existing
        all_sections = [section for section in _walk_sections(draft.get("sections") or []) if section.get("id")]
        section_ids = {str(section["id"]) for section in all_sections}
        sections = [
            section for section in all_sections
            if not any(other_id.startswith(f"{section['id']}-") for other_id in section_ids)
        ]
        literature = self._first_matching(sections, ("文献综述", "研究现状", "相关研究", "国内外", "综述"))
        experiment = self._first_matching(sections, ("实验结果", "实验", "实证", "测试结果", "结果分析"))
        technical = self._first_matching(sections, ("技术比较", "技术分析", "方案比较", "方法比较", "技术路线", "性能比较"))
        items: list[dict[str, Any]] = []
        if literature:
            items.append(self._item(section=literature, purpose="literature_review_table", asset_kind="table", table_type="literature_review"))
            items.append(self._item(section=literature, purpose="literature_year_distribution", asset_kind="chart", chart_kind="bar"))
        if technical:
            items.append(self._item(section=technical, purpose="technology_comparison", asset_kind="table", table_type="technology_comparison"))
        dataset = self._experiment_dataset(task_id) if experiment else None
        if experiment and dataset:
            _, version = dataset
            items.append(self._item(section=experiment, purpose="experimental_result", asset_kind="chart", chart_kind="scatter", dataset=version))
        plan = {
            "schema_version": 1,
            "id": f"vplan_{uuid.uuid4().hex[:16]}",
            "task_id": task_id,
            "status": "planned",
            "created_at": _now(),
            "updated_at": _now(),
            "source": "full_paper_generation",
            "items": items,
            "summary": {
                "total_items": len(items),
                "literature_section_id": literature.get("id") if literature else None,
                "technical_section_id": technical.get("id") if technical else None,
                "experiment_section_id": experiment.get("id") if experiment else None,
                "notes": "未识别明确章节目的或缺少真实数据时，不建立可视化计划项。",
            },
        }
        return self._write(task_id, plan)

    def _save_item(self, task_id: str, item_id: str, *, status: str | None = None, reason: str = "", **changes: Any) -> dict[str, Any]:
        plan = self.get(task_id)
        if not plan:
            raise ValueError("全文可视化计划不存在")
        item = next((value for value in plan.get("items") or [] if value.get("id") == item_id), None)
        if not item:
            raise ValueError("未找到可视化计划项")
        if status:
            if status not in PLAN_STATUSES:
                raise ValueError("可视化计划状态无效")
            item["status"] = status
        item.update(changes)
        item["updated_at"] = _now()
        if reason:
            item.setdefault("events", []).append({"at": _now(), "status": item.get("status"), "reason": reason})
        plan["status"] = "completed" if all(value.get("status") in {"inserted", "skipped", "broken", "stale"} for value in plan.get("items") or []) else "running"
        return self._write(task_id, plan)

    @staticmethod
    def _candidate_signature(candidate: dict[str, Any]) -> str:
        chart = candidate.get("chart") or {}
        source = candidate.get("source_snapshot") or []
        source_ids = sorted(
            f"{entry.get('source_type')}:{entry.get('source_id')}:{entry.get('dataset_version') or ''}"
            for entry in source
            if entry.get("source_id")
        )
        return _hash({
            "asset_kind": candidate.get("kind"),
            "table_type": candidate.get("table_type"),
            "chart_kind": candidate.get("chart_kind") or ((chart.get("block_snapshot") or {}).get("chart_spec") or {}).get("kind"),
            "evidence_ids": sorted(str(value) for value in candidate.get("evidence_ids") or []),
            "dataset_id": candidate.get("dataset_id") or chart.get("dataset_id"),
            "dataset_version": candidate.get("dataset_version") or chart.get("dataset_version"),
            "sources": source_ids,
            "title": _normal(candidate.get("title")),
        })

    @staticmethod
    def _block_matches_candidate(block: dict[str, Any], candidate: dict[str, Any], source_signature: str) -> bool:
        provenance = block.get("research_visualization") or {}
        if provenance.get("candidate_id") and provenance.get("candidate_id") == candidate.get("id"):
            return True
        if provenance.get("source_signature") == source_signature:
            return True
        if block.get("type") != candidate.get("kind"):
            return False
        candidate_evidence = {str(value) for value in candidate.get("evidence_ids") or []}
        block_evidence = {str(value) for value in provenance.get("evidence_ids") or []}
        if candidate_evidence and candidate_evidence == block_evidence:
            return True
        chart = candidate.get("chart") or {}
        candidate_dataset = str(candidate.get("dataset_id") or chart.get("dataset_id") or "")
        if candidate_dataset and candidate_dataset == str(provenance.get("dataset_id") or ""):
            expected_kind = candidate.get("chart_kind") or ((chart.get("block_snapshot") or {}).get("chart_spec") or {}).get("kind")
            actual_kind = ((block.get("chart_spec") or {}).get("kind"))
            return not expected_kind or expected_kind == actual_kind
        return bool(candidate.get("title")) and _normal(candidate.get("title")) == _normal(block.get("title"))

    @staticmethod
    def _all_blocks(draft: dict[str, Any]):
        for section in _walk_sections(draft.get("sections") or []):
            yield from section.get("paragraphs") or []

    def accept_candidate(self, task_id: str, item_id: str, candidate: dict[str, Any], draft: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Attach one candidate to a plan item unless its exact source-backed visual already exists."""
        plan = self.get(task_id)
        if not plan:
            raise ValueError("全文可视化计划不存在")
        item = next((value for value in plan.get("items") or [] if value.get("id") == item_id), None)
        if not item:
            raise ValueError("未找到可视化计划项")
        if item.get("status") == "inserted":
            return False, plan
        if candidate.get("kind") != item.get("asset_kind"):
            return False, self._save_item(task_id, item_id, status="skipped", reason="候选类型与全文可视化计划不一致。")
        source_signature = self._candidate_signature(candidate)
        for other in plan.get("items") or []:
            if other.get("id") != item_id and other.get("source_signature") == source_signature and other.get("status") in {"generated", "inserted"}:
                return False, self._save_item(task_id, item_id, status="skipped", reason="同一组证据或数据已被其他全文计划项使用，已去重。", source_signature=source_signature)
        for block in self._all_blocks(draft):
            if self._block_matches_candidate(block, candidate, source_signature):
                return False, self._save_item(task_id, item_id, status="skipped", reason="正文中已存在等价的 FigureBlock 或 TableBlock，未重复插入。", source_signature=source_signature, inserted_block_id=block.get("id"))
        chart = candidate.get("chart") or {}
        return True, self._save_item(
            task_id,
            item_id,
            status="generated",
            reason="已生成与该章节论点唯一绑定的来源可追溯候选。",
            candidate_id=candidate.get("id"),
            evidence_ids=list(candidate.get("evidence_ids") or []),
            dataset_ids=list(dict.fromkeys([str(value) for value in [candidate.get("dataset_id"), chart.get("dataset_id")] if value])),
            dataset_versions=list(dict.fromkeys([value for value in [candidate.get("dataset_version"), chart.get("dataset_version")] if value is not None])),
            source_signature=source_signature,
        )

    def mark_inserted(self, task_id: str, item_id: str, block_id: str) -> dict[str, Any]:
        return self._save_item(task_id, item_id, status="inserted", reason="已在唯一目标章节锚点插入正式论文对象。", inserted_block_id=block_id)

    def mark_skipped(self, task_id: str, item_id: str, reason: str) -> dict[str, Any]:
        return self._save_item(task_id, item_id, status="skipped", reason=reason)

    def mark_broken(self, task_id: str, item_id: str, reason: str) -> dict[str, Any]:
        return self._save_item(task_id, item_id, status="broken", reason=reason)

    def reset_section(self, task_id: str, section_id: str) -> dict[str, Any] | None:
        plan = self.get(task_id)
        if not plan:
            return None
        for item in plan.get("items") or []:
            if item.get("target_section_id") != section_id:
                continue
            item.update({"status": "planned", "candidate_id": None, "inserted_block_id": None, "source_signature": None, "evidence_ids": []})
            item.setdefault("events", []).append({"at": _now(), "status": "planned", "reason": "章节重新生成，计划项已恢复为待生成状态。"})
        plan["status"] = "running"
        return self._write(task_id, plan)

    def sync_candidate_statuses(self, task_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        plan = self.get(task_id)
        if not plan:
            return None
        by_id = {str(candidate.get("id")): candidate for candidate in candidates}
        changed = False
        for item in plan.get("items") or []:
            candidate = by_id.get(str(item.get("candidate_id") or ""))
            if not candidate:
                continue
            candidate_status = candidate.get("status")
            if candidate_status in {"stale", "broken"} and item.get("status") != candidate_status:
                item["status"] = candidate_status
                item["updated_at"] = _now()
                item.setdefault("events", []).append({"at": _now(), "status": candidate_status, "reason": "关联候选的来源状态发生变化。"})
                changed = True
        return self._write(task_id, plan) if changed else plan

    def items_for_section(self, task_id: str, section_id: str) -> list[dict[str, Any]]:
        plan = self.get(task_id)
        if not plan:
            return []
        return [dict(item) for item in plan.get("items") or [] if item.get("target_section_id") == section_id and item.get("status") == "planned"]

    def summary(self, task_id: str) -> dict[str, Any] | None:
        plan = self.get(task_id)
        if not plan:
            return None
        return {
            "id": plan.get("id"),
            "status": plan.get("status"),
            "total_items": len(plan.get("items") or []),
            "items": [{key: item.get(key) for key in ("id", "status", "target_section_id", "purpose", "asset_kind", "chart_kind", "table_type", "insertion_anchor", "candidate_id", "inserted_block_id")} for item in plan.get("items") or []],
        }
