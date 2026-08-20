"""Structured in-document figure/table cross references.

A CrossReference stores only a target ResearchObject ID as its truth source.
Labels are resolved at read/export time from the current object number, so a
renumber operation never has to rewrite references in prose.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.draft.chart_runtime import walk_sections
from app.services.research_object_service import ResearchObjectService


REFERENCE_TYPES = {"figure", "table"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


class CrossReferenceService:
    """Persist references separately while embedding only reference IDs in blocks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.db_path.parent / "cross_references"
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = ResearchObjectService(settings)

    def _task_dir(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", task_id)
        if not safe or safe != task_id:
            raise ValueError("任务 ID 无效")
        return self.root / safe

    def _path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "references.json"

    def _draft_path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", task_id)
        if not safe or safe != task_id:
            raise ValueError("任务 ID 无效")
        return self.settings.output_dir / safe / "draft.json"

    def _read(self, task_id: str) -> list[dict[str, Any]]:
        path = self._path(task_id)
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("references", []) if isinstance(payload, dict) else payload
            return records if isinstance(records, list) else []
        except json.JSONDecodeError:
            return []

    def _write(self, task_id: str, references: list[dict[str, Any]]) -> None:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"task_id": task_id, "references": references, "updated_at": _now()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_draft(self, task_id: str) -> dict[str, Any]:
        path = self._draft_path(task_id)
        if not path.is_file():
            raise ValueError("未找到论文草稿")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("论文草稿格式无效") from exc

    def _save_draft(self, task_id: str, draft: dict[str, Any]) -> None:
        path = self._draft_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _find_block(draft: dict[str, Any], block_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                if block.get("id") == block_id:
                    return section, block
        raise ValueError("未找到引用所在正文块")

    @staticmethod
    def _display_for_object(target: dict[str, Any]) -> str | None:
        if target.get("type") not in REFERENCE_TYPES:
            return None
        try:
            number = int(target.get("number"))
        except (TypeError, ValueError):
            return None
        if number < 1:
            return None
        return f"图{number}" if target["type"] == "figure" else f"表{number}"

    def _object_index(self, task_id: str) -> dict[str, dict[str, Any]]:
        # Numbering first brings old drafts into the same safe compatibility path.
        self.objects.renumber_document_references(task_id)
        return {item["id"]: item for item in self.objects.list(task_id)}

    def _resolved(self, record: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
        result = dict(record)
        target = index.get(str(record.get("target_object_id") or ""))
        label = self._display_for_object(target or {}) if target else None
        if target is None or target.get("type") != record.get("target_type") or not label:
            result.update(status="broken", display_label=record.get("display_label") or "", resolved_label=None, target_title=None)
        else:
            result.update(status="ready", display_label=label, resolved_label=label, target_title=target.get("title") or "")
        return result

    def _list_resolved(self, task_id: str, persist: bool = True) -> list[dict[str, Any]]:
        index = self._object_index(task_id)
        raw = self._read(task_id)
        resolved = [self._resolved(item, index) for item in raw]
        if persist and resolved != raw:
            # display_label is only a cache; target_object_id is intentionally unchanged.
            for item in resolved:
                item["updated_at"] = _now() if item != next((old for old in raw if old.get("id") == item.get("id")), {}) else item.get("updated_at")
            self._write(task_id, resolved)
        return resolved

    def reference_candidates(self, task_id: str) -> list[dict[str, Any]]:
        index = self._object_index(task_id)
        rows = []
        for item in index.values():
            label = self._display_for_object(item)
            if item.get("type") in REFERENCE_TYPES and label:
                rows.append({
                    "id": item["id"], "type": item["type"], "title": item.get("title") or "",
                    "number": item.get("number"), "display_label": label,
                    "status": item.get("status") or "ready", "source_id": item.get("source_id"),
                })
        return sorted(rows, key=lambda item: (0 if item["type"] == "figure" else 1, item.get("number") or 0, item["id"]))

    def create(self, *, task_id: str, source_block_id: str, target_object_id: str) -> dict[str, Any]:
        draft = self._load_draft(task_id)
        self._find_block(draft, source_block_id)
        target = next((item for item in self.reference_candidates(task_id) if item["id"] == target_object_id), None)
        if target is None:
            raise ValueError("目标对象不存在或当前不可引用")
        record = {
            "id": f"cr_{uuid.uuid4().hex[:16]}", "task_id": task_id,
            "source_block_id": source_block_id, "target_object_id": target_object_id,
            "target_type": target["type"], "display_label": target["display_label"],
            "status": "ready", "created_at": _now(), "updated_at": _now(),
        }
        records = self._read(task_id)
        records.append(record)
        self._write(task_id, records)
        return self._resolved(record, self._object_index(task_id))

    def insert(self, *, task_id: str, section_id: str, target_object_id: str, prefix: str = "如", suffix: str = "所示") -> dict[str, Any]:
        """Create a self-contained structured body block: text + reference + text."""
        draft = self._load_draft(task_id)
        section = next((item for item in walk_sections(draft.get("sections") or []) if item.get("id") == section_id), None)
        if section is None:
            raise ValueError("未找到插入目标小节")
        block_id = f"p{len(section.get('paragraphs') or []) + 1}-{uuid.uuid4().hex[:6]}"
        block = {"id": block_id, "type": "cross_reference", "text": "", "content": []}
        section.setdefault("paragraphs", []).append(block)
        self._save_draft(task_id, draft)
        reference = self.create(task_id=task_id, source_block_id=block_id, target_object_id=target_object_id)
        # ``create`` resolves the current ResearchObject registry and may safely
        # migrate old figure/table numbers. Reload before changing the new block
        # so those domain updates are never overwritten by stale in-memory data.
        draft = self._load_draft(task_id)
        _, block = self._find_block(draft, block_id)
        block["content"] = [
            {"type": "text", "text": _clean(prefix, 300)},
            {"type": "cross_reference", "reference_id": reference["id"]},
            {"type": "text", "text": _clean(suffix, 300)},
        ]
        block["text"] = self.render_block_text(task_id, block)
        self._save_draft(task_id, draft)
        return {"reference": reference, "block": block}

    def update(self, *, task_id: str, reference_id: str, target_object_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"cr_[A-Za-z0-9]+", reference_id):
            raise ValueError("CrossReference ID 无效")
        target = next((item for item in self.reference_candidates(task_id) if item["id"] == target_object_id), None)
        if target is None:
            raise ValueError("目标对象不存在或当前不可引用")
        records = self._read(task_id)
        record = next((item for item in records if item.get("id") == reference_id), None)
        if record is None:
            raise ValueError("未找到 CrossReference")
        record.update(target_object_id=target_object_id, target_type=target["type"], display_label=target["display_label"], status="ready", updated_at=_now())
        self._write(task_id, records)
        self.refresh_source_block(task_id, record.get("source_block_id"))
        return self._resolved(record, self._object_index(task_id))

    def delete(self, *, task_id: str, reference_id: str) -> None:
        records = self._read(task_id)
        target = next((item for item in records if item.get("id") == reference_id), None)
        if target is None:
            raise ValueError("未找到 CrossReference")
        records = [item for item in records if item.get("id") != reference_id]
        self._write(task_id, records)
        try:
            draft = self._load_draft(task_id)
            section, block = self._find_block(draft, str(target.get("source_block_id") or ""))
            parts = [part for part in block.get("content") or [] if not (part.get("type") == "cross_reference" and part.get("reference_id") == reference_id)]
            if block.get("type") == "cross_reference":
                section["paragraphs"] = [item for item in section.get("paragraphs") or [] if item.get("id") != block.get("id")]
            else:
                block["content"] = parts
                block["text"] = self.render_block_text(task_id, block)
            self._save_draft(task_id, draft)
        except ValueError:
            # A deleted source block must not prevent deletion of its independent reference record.
            return

    def refresh_source_block(self, task_id: str, source_block_id: str | None) -> None:
        if not source_block_id:
            return
        draft = self._load_draft(task_id)
        _, block = self._find_block(draft, source_block_id)
        block["text"] = self.render_block_text(task_id, block)
        self._save_draft(task_id, draft)

    def list(self, task_id: str) -> list[dict[str, Any]]:
        return self._list_resolved(task_id)

    def render_block_text(self, task_id: str, block: dict[str, Any], references: dict[str, dict[str, Any]] | None = None) -> str:
        """Render structured content; old text-only blocks remain untouched."""
        content = block.get("content")
        if not isinstance(content, list):
            return str(block.get("text") or "")
        index = references if references is not None else {item["id"]: item for item in self._list_resolved(task_id)}
        fragments: list[str] = []
        for item in content:
            if item.get("type") == "text":
                fragments.append(str(item.get("text") or ""))
            elif item.get("type") == "cross_reference":
                reference = index.get(str(item.get("reference_id") or ""))
                fragments.append(str((reference or {}).get("resolved_label") or "[引用对象不存在]"))
        return "".join(fragments)

    def render_draft_text(self, task_id: str, draft: dict[str, Any]) -> dict[str, str]:
        structured = [
            block for section in walk_sections(draft.get("sections") or [])
            for block in section.get("paragraphs") or []
            if isinstance(block.get("content"), list)
        ]
        # Old drafts have no structured references. Avoid touching ResearchObject
        # storage for this path, preserving legacy DraftService callers that use
        # a bare temporary task directory rather than outputs/<task_id>.
        if not structured:
            return {}
        references = {item["id"]: item for item in self._list_resolved(task_id)}
        return {
            str(block.get("id")): self.render_block_text(task_id, block, references)
            for block in structured
        }
