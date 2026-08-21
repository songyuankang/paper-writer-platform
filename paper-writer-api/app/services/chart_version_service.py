"""Immutable, task-scoped history for structured FigureBlock ChartSpecs.

ChartVersion records are intentionally stored next to the authoritative draft and
ChartAssets.  They are not a second chart model: a version is an audit snapshot
of the same ChartSpec that the existing renderer and DOCX exporter consume.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings
from app.draft.chart_runtime import now

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class ChartVersionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _path(self, task_id: str, figure_id: str) -> Path:
        if not _SAFE_ID.fullmatch(task_id) or not _SAFE_ID.fullmatch(figure_id):
            raise ValueError("ChartVersion 标识无效")
        return self.settings.output_dir / task_id / "chart_versions" / f"{figure_id}.json"

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def list(self, task_id: str, figure_id: str) -> list[dict[str, Any]]:
        path = self._path(task_id, figure_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("ChartVersion 历史文件损坏") from exc
        versions = payload.get("versions") if isinstance(payload, dict) else None
        if not isinstance(versions, list):
            raise ValueError("ChartVersion 历史格式无效")
        return self._clone(versions)

    def write(self, task_id: str, figure_id: str, versions: list[dict[str, Any]]) -> None:
        path = self._path(task_id, figure_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "task_id": task_id, "figure_id": figure_id, "versions": self._clone(versions)}
        fd, temporary = tempfile.mkstemp(prefix=f".{figure_id}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def source_snapshot(block: dict[str, Any]) -> list[dict[str, Any]]:
        research = block.get("research_visualization") or {}
        snapshot = research.get("source_snapshot") or block.get("source_snapshot") or []
        if isinstance(snapshot, list) and snapshot:
            return copy.deepcopy(snapshot)
        binding = (block.get("chart_spec") or {}).get("binding") or {}
        if binding.get("dataset_id"):
            return [{
                "source_type": "dataset",
                "source_id": binding.get("dataset_id"),
                "dataset_version": binding.get("dataset_version"),
                "data_fingerprint": binding.get("data_fingerprint"),
            }]
        if binding.get("source_table_id"):
            return [{
                "source_type": "table_block",
                "source_id": binding.get("source_table_id"),
                "data_fingerprint": binding.get("data_fingerprint"),
            }]
        return []

    def snapshot(
        self,
        *,
        task_id: str,
        block: dict[str, Any],
        editor: dict[str, str],
        reason: str,
        parent_version_id: str | None,
    ) -> dict[str, Any]:
        figure_id = str(block.get("id") or "")
        if not figure_id:
            raise ValueError("图表缺少稳定 ID")
        asset = block.get("asset") or {}
        return {
            "id": "cv_" + uuid.uuid4().hex[:16],
            "figure_id": figure_id,
            "task_id": task_id,
            "chart_spec": self._clone(block.get("chart_spec") or {}),
            "asset_snapshot": {
                "id": asset.get("id"),
                "png": asset.get("png_path"),
                "svg": asset.get("svg_path"),
            },
            "editor": {"type": editor.get("type") or "system", "name": editor.get("name") or "系统"},
            "reason": reason,
            "parent_version_id": parent_version_id,
            "source_snapshot": self.source_snapshot(block),
            "research_visualization": self._clone(block.get("research_visualization") or {}),
            "created_at": now(),
        }

    def ensure_initial(self, task_id: str, block: dict[str, Any], versions: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], str]:
        """Create a lazy v1 snapshot for pre-Phase-C figures without mutating history."""
        current = list(versions if versions is not None else self.list(task_id, str(block.get("id") or "")))
        current_id = str(block.get("current_chart_version_id") or "")
        if current_id and any(item.get("id") == current_id for item in current):
            return current, current_id
        if current:
            latest = str(current[-1].get("id") or "")
            if latest:
                return current, latest
        initial = self.snapshot(
            task_id=task_id,
            block=block,
            editor={"type": "system", "name": "系统初始生成"},
            reason="initial",
            parent_version_id=None,
        )
        current.append(initial)
        return current, str(initial["id"])

    def get(self, task_id: str, figure_id: str, version_id: str) -> dict[str, Any]:
        version = next((item for item in self.list(task_id, figure_id) if item.get("id") == version_id), None)
        if version is None:
            raise ValueError("未找到图表版本")
        return version
