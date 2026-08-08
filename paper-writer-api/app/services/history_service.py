"""论文生成记录：创建/更新/查询/删除（含删除生成文件）。"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_record(task_id: str, request: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO generation_records
                (id, task_id, title, major, paper_type, word_count,
                 generation_mode, status, created_at, preview_path, params,
                 special_requirements, current_stage, progress,
                 current_chapter, chapter_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                task_id,
                request.get("title", ""),
                request.get("major", ""),
                request.get("paper_type", ""),
                request.get("word_count", 0),
                request.get("generation_mode", "auto"),
                "pending",
                _now(),
                f"/api/preview/{task_id}",
                json.dumps(request, ensure_ascii=False),
                request.get("special_requirements"),
                "pending", 0, None, 0,
            ),
        )


def update_record(task_id: str, *, status: str | None = None,
                  error: str | None = None,
                  completed: bool = False) -> None:
    sets: list[str] = []
    values: list = []
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if error is not None:
        sets.append("error_message = ?")
        values.append(error)
    if completed:
        sets.append("completed_at = ?")
        values.append(_now())
        sets.append("file_path = ?")
        values.append(f"/api/download/{task_id}?file=论文.docx")
    if not sets:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE generation_records SET {', '.join(sets)} WHERE task_id = ?",
            values + [task_id],
        )


def update_record_progress(task_id: str, *, current_stage: str | None = None,
                           progress: int | None = None,
                           current_chapter: str | None = None,
                           chapter_count: int | None = None) -> None:
    """分段生成过程中同步更新记录的分阶段字段。"""
    sets: list[str] = []
    values: list = []
    if current_stage is not None:
        sets.append("current_stage = ?")
        values.append(current_stage)
    if progress is not None:
        sets.append("progress = ?")
        values.append(progress)
    if current_chapter is not None:
        sets.append("current_chapter = ?")
        values.append(current_chapter)
    if chapter_count is not None:
        sets.append("chapter_count = ?")
        values.append(chapter_count)
    if not sets:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE generation_records SET {', '.join(sets)} "
            "WHERE task_id = ?",
            values + [task_id],
        )


def list_records() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generation_records ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_record(task_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM generation_records WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    if record.get("params"):
        try:
            record["params"] = json.loads(record["params"])
        except json.JSONDecodeError:
            record["params"] = {}
    return record


def delete_record(task_id: str) -> bool:
    """删除数据记录 + 生成文件（outputs/） + 上传模板（uploads/）。"""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM generation_records WHERE task_id = ?", (task_id,))
        conn.execute(
            "DELETE FROM revision_versions WHERE task_id = ?", (task_id,))
        deleted = cur.rowcount
    output_dir = settings.output_dir / task_id
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    upload = settings.upload_dir / f"{task_id}.docx"
    if upload.exists():
        upload.unlink(missing_ok=True)
    return deleted > 0
