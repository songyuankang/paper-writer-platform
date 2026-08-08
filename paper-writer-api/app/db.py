"""数据库访问层。

开发环境使用 SQLite（stdlib sqlite3）；表结构与 SQL 尽量保持标准，
迁移到 PostgreSQL（生产环境）时仅需替换连接方式与占位符。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def _db_file() -> str:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """打开数据库连接（自动提交/回滚/关闭，杜绝连接泄漏）。

    用法与之前一致：``with get_conn() as conn:``。
    """
    conn = sqlite3.connect(_db_file())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """创建生成记录表（幂等）。"""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_records (
                id              TEXT PRIMARY KEY,
                task_id         TEXT UNIQUE NOT NULL,
                title           TEXT NOT NULL DEFAULT '',
                major           TEXT NOT NULL DEFAULT '',
                paper_type      TEXT NOT NULL DEFAULT '',
                word_count      INTEGER NOT NULL DEFAULT 0,
                generation_mode TEXT NOT NULL DEFAULT 'auto',
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                completed_at    TEXT,
                file_path       TEXT,
                preview_path    TEXT,
                error_message   TEXT,
                params          TEXT
            )
            """
        )
        # 兼容已有数据库：补充 special_requirements 列
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(generation_records)").fetchall()
        }
        if "special_requirements" not in columns:
            conn.execute(
                "ALTER TABLE generation_records "
                "ADD COLUMN special_requirements TEXT")
        for col, decl in (
            ("current_stage", "TEXT"),
            ("progress", "INTEGER NOT NULL DEFAULT 0"),
            ("current_chapter", "TEXT"),
            ("chapter_count", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in columns:
                conn.execute(
                    f"ALTER TABLE generation_records ADD COLUMN {col} {decl}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revision_versions (
                id               TEXT PRIMARY KEY,
                task_id          TEXT NOT NULL,
                version_number   INTEGER NOT NULL,
                change_type      TEXT NOT NULL DEFAULT '',
                description      TEXT,
                created_at       TEXT NOT NULL,
                content_snapshot TEXT NOT NULL,
                UNIQUE(task_id, version_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_configs (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                provider   TEXT NOT NULL DEFAULT 'OpenAI Compatible',
                base_url   TEXT NOT NULL,
                api_key    TEXT NOT NULL,
                model      TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                enabled    INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS format_templates (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                school_name    TEXT NOT NULL DEFAULT '',
                major          TEXT NOT NULL DEFAULT '',
                paper_type     TEXT NOT NULL DEFAULT '',
                type           TEXT NOT NULL DEFAULT 'mine',
                category       TEXT NOT NULL DEFAULT '',
                description    TEXT NOT NULL DEFAULT '',
                version        INTEGER NOT NULL DEFAULT 1,
                schema_version INTEGER NOT NULL DEFAULT 2,
                source         TEXT NOT NULL DEFAULT 'db',
                content        TEXT,
                parent_id      TEXT,
                is_favorite    INTEGER NOT NULL DEFAULT 0,
                is_default     INTEGER NOT NULL DEFAULT 0,
                sort_order     INTEGER NOT NULL DEFAULT 0,
                dir            TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )
        # 兼容旧库：补充模板系统新增列（幂等）
        _ft_cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(format_templates)").fetchall()
        }
        for _col, _decl in (
            ("type", "TEXT NOT NULL DEFAULT 'mine'"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("version", "INTEGER NOT NULL DEFAULT 1"),
            ("schema_version", "INTEGER NOT NULL DEFAULT 2"),
            ("source", "TEXT NOT NULL DEFAULT 'db'"),
            ("content", "TEXT"),
            ("parent_id", "TEXT"),
            ("is_favorite", "INTEGER NOT NULL DEFAULT 0"),
            ("is_default", "INTEGER NOT NULL DEFAULT 0"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if _col not in _ft_cols:
                conn.execute(
                    f"ALTER TABLE format_templates ADD COLUMN {_col} {_decl}")
        # 兼容：旧上传模板（有 dir、无 content）标记为 legacy，保留原数据
        if "legacy" not in _ft_cols:
            conn.execute(
                "ALTER TABLE format_templates ADD COLUMN legacy "
                "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "UPDATE format_templates SET legacy = 1 "
                "WHERE content IS NULL AND source = 'db'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS format_tasks (
                id           TEXT PRIMARY KEY,
                task_id      TEXT NOT NULL,
                template_id  TEXT,
                status       TEXT NOT NULL DEFAULT 'waiting',
                progress     INTEGER NOT NULL DEFAULT 0,
                message      TEXT,
                settings     TEXT,
                files        TEXT,
                created_at   TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
