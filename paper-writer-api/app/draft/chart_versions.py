"""Transactional helpers for immutable FigureBlock ChartVersion history."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from app.services.chart_version_service import ChartVersionService
from app.services.dependency_graph_service import DependencyGraphService


def _restore_history(store: ChartVersionService, task_id: str, figure_id: str, existing: list[dict[str, Any]], existed: bool) -> None:
    path = store._path(task_id, figure_id)  # Task-local path is owned by ChartVersionService.
    if existed:
        store.write(task_id, figure_id, existing)
    elif path.exists():
        path.unlink()


def bootstrap_chart_version(service, draft: dict[str, Any], block: dict[str, Any], before_draft: dict[str, Any]) -> dict[str, Any]:
    """Persist an initial snapshot for a FigureBlock without changing its content."""
    store = ChartVersionService(service._storage_settings())
    figure_id = str(block.get("id") or "")
    existing = store.list(service.task_id, figure_id)
    path_existed = store._path(service.task_id, figure_id).exists()
    versions, current_id = store.ensure_initial(service.task_id, block, existing)
    block["current_chart_version_id"] = current_id
    try:
        service.save(draft)
        store.write(service.task_id, figure_id, versions)
        DependencyGraphService(service._storage_settings()).rebuild_task(service.task_id)
    except Exception as exc:
        service.save(before_draft)
        _restore_history(store, service.task_id, figure_id, existing, path_existed)
        try:
            DependencyGraphService(service._storage_settings()).rebuild_task(service.task_id)
        except Exception:
            pass
        raise ValueError("图表初始版本保存失败，已保留旧状态") from exc
    return next(item for item in versions if item["id"] == current_id)


def commit_chart_version(
    service,
    draft: dict[str, Any],
    before_draft: dict[str, Any],
    block: dict[str, Any],
    previous_block: dict[str, Any],
    *,
    editor: dict[str, str],
    reason: str,
    parent_version_id: str | None = None,
) -> dict[str, Any]:
    """Commit a changed FigureBlock with an immutable new ChartVersion.

    Rendering occurs before this helper is called.  If draft persistence, version
    history writing, or graph rebuilding fails, the persisted draft/history is
    restored to the pre-edit state; any newly rendered files remain unreferenced
    and cannot replace the prior exported asset.
    """
    store = ChartVersionService(service._storage_settings())
    figure_id = str(block.get("id") or "")
    existing = store.list(service.task_id, figure_id)
    path_existed = store._path(service.task_id, figure_id).exists()
    versions, current_id = store.ensure_initial(service.task_id, previous_block, existing)
    version = store.snapshot(
        task_id=service.task_id,
        block=block,
        editor=editor,
        reason=reason,
        parent_version_id=parent_version_id or current_id,
    )
    versions.append(version)
    block["current_chart_version_id"] = version["id"]
    try:
        service.save(draft)
        store.write(service.task_id, figure_id, versions)
        DependencyGraphService(service._storage_settings()).rebuild_task(service.task_id)
    except Exception as exc:
        service.save(before_draft)
        _restore_history(store, service.task_id, figure_id, existing, path_existed)
        try:
            DependencyGraphService(service._storage_settings()).rebuild_task(service.task_id)
        except Exception:
            pass
        raise ValueError("图表版本保存失败，已保留上一可用版本") from exc
    return version


def restore_chart_version(service, block_id: str, version_id: str) -> dict[str, Any]:
    """Restore an old snapshot by creating a new audit version, never by rewinding history."""
    with service.lock:
        draft = service.load()
        before_draft = copy.deepcopy(draft)
        from app.draft.chart_runtime import locate_block, render_chart_assets

        _, block = locate_block(draft, block_id)
        if block.get("type") != "chart":
            raise ValueError("目标内容块不是图表")
        store = ChartVersionService(service._storage_settings())
        target = store.get(service.task_id, str(block.get("id") or ""), version_id)
        spec = copy.deepcopy(target.get("chart_spec") or {})
        if not spec:
            raise ValueError("目标版本缺少 ChartSpec")
        previous = copy.deepcopy(block)
        render_version = int(block.get("version") or 0) + 1
        asset = render_chart_assets(service.task_dir, str(block["id"]), render_version, spec)
        block.update({
            "status": "ready",
            "version": render_version,
            "title": spec.get("title") or block.get("title") or "图表",
            "caption": spec.get("caption") or "",
            "chart_spec": spec,
            "chart": {"schema_version": 2, "kind": spec.get("kind", "bar"), "title": spec.get("title", ""), "caption": spec.get("caption", ""), **(spec.get("data") or {})},
            "asset": asset,
            "stale_reason": None,
            "updated_at": __import__("app.draft.chart_runtime", fromlist=["now"]).now(),
        })
        commit_chart_version(
            service,
            draft,
            before_draft,
            block,
            previous,
            editor={"type": "user", "name": "用户恢复版本"},
            reason="restore",
            parent_version_id=version_id,
        )
        return block


def export_version_summary(item: dict[str, Any]) -> dict[str, Any]:
    asset = item.get("asset_snapshot") or {}
    return {
        "id": item.get("id"),
        "figure_id": item.get("figure_id"),
        "editor": item.get("editor") or {},
        "reason": item.get("reason"),
        "parent_version_id": item.get("parent_version_id"),
        "created_at": item.get("created_at"),
        "preview_asset": asset.get("svg") or asset.get("png") or "",
        "source_count": len(item.get("source_snapshot") or []),
    }
