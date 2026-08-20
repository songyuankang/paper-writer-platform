"""ResearchObject registry and document-reference numbering.

ResearchObject is deliberately an index of stable references, not a second copy of
research data.  Dataset rows, AnalysisResult payloads and chart assets remain in
their established stores; this service materialises small, task-scoped descriptors
that can be used by future reference features without coupling callers to storage.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.draft.chart_runtime import walk_sections
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

SUPPORTED_TYPES = {"dataset", "analysis", "table", "figure", "finding", "literature", "discussion"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


def _object_id(task_id: str, object_type: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{task_id}:{object_type}:{source_id}".encode("utf-8")).hexdigest()[:24]
    return f"ro_{object_type}_{digest}"


def _number_label(object_type: str, value: object) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return f"图{number}" if object_type == "figure" else f"表{number}"


class ResearchObjectService:
    """Build and persist lightweight, task-scoped ResearchObject descriptors."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.db_path.parent / "research_objects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.datasets = DatasetService(settings)
        self.analyses = AnalysisService(settings)

    def _task_dir(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", task_id)
        if not safe or safe != task_id:
            raise ValueError("任务 ID 无效")
        return self.root / safe

    def _path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "objects.json"

    def _draft_path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", task_id)
        if not safe or safe != task_id:
            raise ValueError("任务 ID 无效")
        return self.settings.output_dir / safe / "draft.json"

    def _read_registry(self, task_id: str) -> list[dict[str, Any]]:
        path = self._path(task_id)
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            objects = payload.get("objects", []) if isinstance(payload, dict) else payload
            return objects if isinstance(objects, list) else []
        except json.JSONDecodeError:
            return []

    def _write_registry(self, task_id: str, objects: list[dict[str, Any]]) -> None:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"task_id": task_id, "objects": objects, "updated_at": _now()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _draft_objects(task_id: str, draft: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                kind = str(block.get("type") or "")
                if kind == "table":
                    source_id = _clean(block.get("id"), 120)
                    if not source_id:
                        continue
                    records.append({
                        "type": "table", "source_id": source_id,
                        "title": _clean(block.get("title")) or "数据表",
                        "number": block.get("table_number"),
                        "status": _clean(block.get("status")) or "ready",
                        "created_at": block.get("created_at") or block.get("generated_at"),
                        "updated_at": block.get("updated_at"),
                    })
                elif kind in {"chart", "figure"}:
                    source_id = _clean(block.get("id"), 120)
                    if not source_id:
                        continue
                    records.append({
                        "type": "figure", "source_id": source_id,
                        "title": _clean(block.get("title")) or "图表",
                        "number": block.get("figure_number"),
                        "status": _clean(block.get("status")) or "ready",
                        "created_at": block.get("created_at") or block.get("generated_at"),
                        "updated_at": block.get("updated_at"),
                    })
        return records

    def _external_objects(self, task_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for dataset in self.datasets.list_datasets(task_id):
            source_id = _clean(dataset.get("id"), 120)
            if source_id:
                records.append({
                    "type": "dataset", "source_id": source_id,
                    "title": _clean(dataset.get("name")) or "研究数据集",
                    "number": None, "status": "ready",
                    "created_at": dataset.get("created_at"), "updated_at": dataset.get("updated_at"),
                })
        for analysis in self.analyses.list(task_id=task_id):
            source_id = _clean(analysis.get("id"), 120)
            if source_id:
                records.append({
                    "type": "analysis", "source_id": source_id,
                    "title": _clean(analysis.get("name")) or "统计分析",
                    "number": None, "status": analysis.get("status") or "ready",
                    "created_at": analysis.get("created_at"), "updated_at": analysis.get("updated_at"),
                })
        findings_root = self.settings.db_path.parent / "findings"
        for path in findings_root.glob("rf_*.json") if findings_root.exists() else []:
            try:
                finding = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if finding.get("task_id") != task_id:
                continue
            source_id = _clean(finding.get("id"), 120)
            if source_id:
                records.append({
                    "type": "finding", "source_id": source_id,
                    "title": _clean(finding.get("title")) or "研究结果",
                    "number": None, "status": finding.get("status") or "draft",
                    "created_at": finding.get("created_at"), "updated_at": finding.get("updated_at") or finding.get("created_at"),
                })
        literature_root = self.settings.db_path.parent / "literature" / "items"
        for path in literature_root.glob("lit_*.json") if literature_root.exists() else []:
            try:
                literature = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if literature.get("task_id") != task_id or literature.get("status") == "deleted":
                continue
            source_id = _clean(literature.get("id"), 120)
            if source_id:
                records.append({
                    "type": "literature", "source_id": source_id,
                    "title": _clean(literature.get("title")) or "学术文献",
                    "number": None, "status": "metadata_updated" if literature.get("metadata_updated") else "ready",
                    "created_at": literature.get("created_at"), "updated_at": literature.get("updated_at"),
                })
        discussion_root = self.settings.db_path.parent / "discussion_drafts"
        for path in discussion_root.glob("dd_*.json") if discussion_root.exists() else []:
            try:
                discussion = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if discussion.get("task_id") != task_id:
                continue
            source_id = _clean(discussion.get("id"), 120)
            if source_id:
                records.append({
                    "type": "discussion", "source_id": source_id,
                    "title": _clean(next(iter((discussion.get("sections") or {}).keys()), "DiscussionDraft")) or "DiscussionDraft",
                    "number": None, "status": discussion.get("status") or "ready",
                    "created_at": discussion.get("created_at"), "updated_at": discussion.get("updated_at") or discussion.get("created_at"),
                })
        return records

    def sync(self, task_id: str, draft: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Synchronise descriptors from canonical stores without duplicating them."""
        if draft is None:
            path = self._draft_path(task_id)
            if not path.is_file():
                draft = {}
            else:
                try:
                    draft = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    draft = {}
        previous = {item.get("id"): item for item in self._read_registry(task_id)}
        source_records = [*self._external_objects(task_id), *self._draft_objects(task_id, draft)]
        objects: list[dict[str, Any]] = []
        for record in source_records:
            object_type = record["type"]
            source_id = record["source_id"]
            object_id = _object_id(task_id, object_type, source_id)
            old = previous.get(object_id, {})
            number = record.get("number")
            object_record = {
                "id": object_id,
                "type": object_type,
                "task_id": task_id,
                "title": record["title"],
                "source_id": source_id,
                "number": int(number) if str(number).isdigit() and int(number) > 0 else None,
                "number_label": _number_label(object_type, number) if object_type in {"table", "figure"} else None,
                "status": record.get("status") or "ready",
                "created_at": old.get("created_at") or record.get("created_at") or _now(),
                # Canonical objects may not expose a mutation timestamp (legacy
                # draft blocks).  Preserve the registry timestamp in that case
                # instead of manufacturing a change on every read/sync.
                "updated_at": record.get("updated_at") or old.get("updated_at") or _now(),
            }
            objects.append(object_record)
        objects.sort(key=lambda item: (item["type"], item["created_at"], item["id"]))
        self._write_registry(task_id, objects)
        return objects

    def renumber_document_references(self, task_id: str, draft: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist global Figure/Table numbers in document order.

        The procedure never derives numbers from a browser index.  Repeating it
        against unchanged blocks yields byte-for-byte equivalent numbering values.
        ``chapter`` is deliberately only a stored configuration for this phase.
        """
        write_draft = draft is None
        if draft is None:
            path = self._draft_path(task_id)
            if not path.is_file():
                raise ValueError("未找到论文草稿")
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("论文草稿格式无效") from exc
        numbering = draft.setdefault("numbering", {})
        mode = str(numbering.get("numbering_mode") or numbering.get("mode") or "global")
        if mode not in {"global", "chapter"}:
            mode = "global"
        # Chapter mode is intentionally not calculated in Phase 6A, but preserving
        # the setting now makes the serialized schema forward-compatible.
        numbering["numbering_mode"] = mode
        config = numbering.get("numbering_config") if isinstance(numbering.get("numbering_config"), dict) else {}
        config["mode"] = mode
        numbering["numbering_config"] = config

        figure_count = 0
        table_count = 0
        figures: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                kind = str(block.get("type") or "")
                if kind == "table":
                    table_count += 1
                    block["table_number"] = table_count
                    block["title"] = _clean(block.get("title")) or "数据表"
                    # Semantic slots are optional and non-destructive for old drafts.
                    block.setdefault("source", "")
                    block.setdefault("note", "")
                    tables.append({"id": block.get("id"), "table_number": table_count, "title": block["title"]})
                elif kind in {"chart", "figure"}:
                    figure_count += 1
                    block["figure_number"] = figure_count
                    block["title"] = _clean(block.get("title")) or "图表"
                    block.setdefault("caption", "")
                    block.setdefault("source", "")
                    block.setdefault("note", "")
                    figures.append({"id": block.get("id"), "figure_number": figure_count, "title": block["title"]})
        # Do not mutate an unchanged draft merely because renumber was invoked:
        # callers can safely retry this operation and receive identical numbering.
        objects = self.sync(task_id, draft)
        if write_draft:
            path = self._draft_path(task_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "task_id": task_id,
            "numbering_mode": mode,
            "numbering_config": config,
            "figures": figures,
            "tables": tables,
            "objects": objects,
        }

    def list(self, task_id: str | None = None) -> list[dict[str, Any]]:
        if task_id:
            return self.sync(task_id)
        # A global API call must discover existing papers as well as tasks which
        # have already been numbered.  The registry is only a cache/index, not a
        # prerequisite for an object to exist.
        candidates = {directory.name for directory in self.root.iterdir() if directory.is_dir()} if self.root.exists() else set()
        candidates.update(
            directory.name for directory in self.settings.output_dir.iterdir()
            if directory.is_dir() and (directory / "draft.json").is_file()
        ) if self.settings.output_dir.exists() else None
        result: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                result.extend(self.sync(candidate))
            except ValueError:
                continue
        return sorted(result, key=lambda item: (item.get("updated_at") or "", item["id"]), reverse=True)

    def get(self, object_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"ro_(?:dataset|analysis|table|figure|finding|literature|discussion)_[a-f0-9]{24}", object_id):
            raise ValueError("ResearchObject ID 无效")
        for directory in self.root.iterdir() if self.root.exists() else []:
            if not directory.is_dir():
                continue
            for item in self.sync(directory.name):
                if item["id"] == object_id:
                    return item
        raise ValueError("未找到 ResearchObject")


def renumber_document_references(task_id: str, settings: Settings, draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convenience entry point used by exports and API handlers."""
    return ResearchObjectService(settings).renumber_document_references(task_id, draft)
