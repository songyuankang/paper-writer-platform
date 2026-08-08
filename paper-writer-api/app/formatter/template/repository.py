"""模板存储层（TemplateRepository）—— 纯存储，不含业务规则。

职责（单一职责：读取 / 保存 / 删除 / 查询）：
- 内置模板：通过 :class:`TemplateLoader` 扫描 basic/school 目录并读取模板文件
- 我的模板：SQLite ``format_templates`` 表 CRUD（``content`` 存完整模板 JSON）
- 状态：收藏 / 默认（存储层面的唯一性约束）
- 返回统一模型（Template / TemplateMeta），不返回裸 dict

明确不做（属于 TemplateService 业务层）：
- 默认模板回退、legacy 兼容判断、resolve 兜底等业务规则
- 模板复制命名、"副本"语义等业务逻辑

扩展机制：新增学校模板 = 新建 ``templates/school/<slug>/template.json``
（可选 ``cover.docx``），本类自动扫描注册，无需改代码。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import get_conn
from app.formatter.template.loader import (
    TemplateLoader,
    TemplateLoadError,
)
from app.formatter.template.models import (
    CURRENT_SCHEMA_VERSION,
    Template,
    TemplateMeta,
    TemplateType,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemplateRepository:
    """模板统一存储入口：内置（文件）+ 我的（DB）。"""

    def __init__(self, loader: TemplateLoader):
        self.loader = loader
        self.root = loader.root

    # ------------------------------------------------------------------
    # 内置模板：扫描（文件路径）
    # ------------------------------------------------------------------
    def builtin_files(self) -> dict[str, Path]:
        """全部内置模板 id → 模板 JSON 路径（basic + school 合并）。"""
        idx: dict[str, Path] = {}
        for p in self.loader.basic_files():
            idx[self.loader.basic_id(p.stem)] = p
        for d in self.loader.school_dirs():
            idx[self.loader.school_id(d.name)] = d / "template.json"
        return idx

    def builtin_path(self, template_id: str) -> Path | None:
        return self.builtin_files().get(template_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_meta(self, type: str | None = None, keyword: str | None = None,
                  category: str | None = None) -> list[TemplateMeta]:
        """列出模板元数据（不含完整样式）。

        内置模板：文件 meta 为准（文件可能已更新），合并 DB 收藏/默认状态；
        我的模板：DB 行。返回统一 TemplateMeta 对象。
        """
        self._ensure_builtin_rows()
        sql = ("SELECT id, name, school_name, major, paper_type, type, category, "
               "description, version, schema_version, source, parent_id, "
               "is_favorite, is_default, sort_order, legacy, created_at, updated_at "
               "FROM format_templates")
        conds: list[str] = []
        params: list = []
        if type:
            conds.append("type = ?")
            params.append(type)
        if keyword:
            conds.append("(name LIKE ? OR school_name LIKE ? OR category LIKE ?)")
            kw = f"%{keyword}%"
            params += [kw, kw, kw]
        if category:
            conds.append("category = ?")
            params.append(category)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY " + self._default_order()

        with get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        result: list[TemplateMeta] = []
        for row in rows:
            builtin_path = self.builtin_path(row["id"])
            if builtin_path is not None:
                # 内置模板：文件 meta 为准，仅合并状态
                try:
                    meta = self.loader.load_meta(
                        builtin_path, template_id=row["id"])
                except TemplateLoadError:
                    continue  # 文件损坏时跳过内置，不阻塞列表
                meta.is_favorite = bool(row["is_favorite"])
                meta.is_default = bool(row["is_default"])
                meta.legacy = False
                result.append(meta)
            else:
                result.append(self._row_to_meta(row))
        return result

    def get(self, template_id: str) -> Template | None:
        """读取完整模板（统一模型）。找不到或不可加载返回 None。

        - 内置模板：Loader 从文件加载（文件缺失/非法 → None）
        - 我的模板：从 DB content 反序列化（content 缺失/非法 → None）
        """
        if not template_id:
            return None
        builtin_path = self.builtin_path(template_id)
        if builtin_path is not None:
            try:
                tpl = self.loader.load_template(builtin_path)
            except TemplateLoadError:
                return None
            # 合并状态
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT is_favorite, is_default FROM format_templates "
                    "WHERE id = ?", (template_id,)).fetchone()
            if row is not None:
                tpl.meta.is_favorite = bool(row["is_favorite"])
                tpl.meta.is_default = bool(row["is_default"])
            tpl.meta.builtin = True
            tpl.meta.has_cover = self.loader.has_cover(builtin_path.parent)
            return tpl
        # 我的模板 / 旧记录：DB
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM format_templates WHERE id = ?",
                (template_id,)).fetchone()
        if row is None:
            return None
        content = row["content"]
        if not content:
            return None  # 旧版模板无新格式 content → 存储层无法提供（Service 处理）
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
        tpl = Template.from_dict(data, template_id=template_id)
        meta = self._row_to_meta(row)
        # DB 权威字段覆盖 JSON meta（存储状态）
        tpl.meta = meta
        return tpl

    def get_meta(self, template_id: str) -> TemplateMeta | None:
        """读取模板元数据（不含完整样式）。"""
        if not template_id:
            return None
        builtin_path = self.builtin_path(template_id)
        if builtin_path is not None:
            try:
                meta = self.loader.load_meta(
                    builtin_path, template_id=template_id)
            except TemplateLoadError:
                return None
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT is_favorite, is_default FROM format_templates "
                    "WHERE id = ?", (template_id,)).fetchone()
            if row is not None:
                meta.is_favorite = bool(row["is_favorite"])
                meta.is_default = bool(row["is_default"])
            return meta
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, school_name, major, paper_type, type, category, "
                "description, version, schema_version, source, parent_id, "
                "is_favorite, is_default, sort_order, legacy, created_at, updated_at "
                "FROM format_templates WHERE id = ?", (template_id,)).fetchone()
        return self._row_to_meta(row) if row is not None else None

    def template_dir(self, template_id: str) -> Path | None:
        """模板所在目录（供 Loader 定位 cover.docx 等资源）。"""
        builtin_path = self.builtin_path(template_id)
        if builtin_path is not None:
            return builtin_path.parent
        with get_conn() as conn:
            row = conn.execute(
                "SELECT dir FROM format_templates WHERE id = ?",
                (template_id,)).fetchone()
        if row is None or not row["dir"]:
            return None
        d = Path(row["dir"])
        return d if d.is_dir() else None

    def default_id(self) -> str | None:
        """存储查询：当前 is_default=1 的模板 id；无则 None。"""
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM format_templates WHERE is_default = 1 "
                "ORDER BY updated_at DESC LIMIT 1").fetchone()
        return row["id"] if row is not None else None

    # ------------------------------------------------------------------
    # 我的模板：保存 / 更新 / 删除
    # ------------------------------------------------------------------
    def create(self, content: Template) -> Template:
        """保存一个新的我的模板（写入 DB + 建立模板目录）。"""
        if not content.meta.name or not content.meta.name.strip():
            raise ValueError("模板名称不能为空")
        template_id = uuid.uuid4().hex
        content.meta.id = template_id
        content.meta.type = TemplateType.MINE
        content.meta.builtin = False
        content.meta.legacy = False
        content.schema_version = content.schema_version or CURRENT_SCHEMA_VERSION
        mine_dir = self.root / "mine" / template_id
        mine_dir.mkdir(parents=True, exist_ok=True)
        now = _now()
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO format_templates
                    (id, name, school_name, major, paper_type, type, category,
                     description, version, schema_version, source, content,
                     parent_id, is_favorite, is_default, sort_order, dir,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'mine', ?, ?, ?, ?, 'db', ?, ?,
                        0, 0, 0, ?, ?, ?)
                """,
                (
                    template_id, content.meta.name,
                    content.meta.school_name, content.meta.major,
                    content.meta.paper_type,
                    content.meta.category, content.meta.description,
                    content.meta.version or 1, content.schema_version,
                    json.dumps(content.to_dict(), ensure_ascii=False),
                    content.meta.parent_id,
                    str(mine_dir), now, now,
                ),
            )
        return self.get(template_id)

    def update(self, template_id: str, content: Template) -> Template:
        """更新我的模板（version +1）。内置模板拒绝（存储约束）。"""
        # 内置模板保护不依赖 DB 注册状态（文件存在即只读）
        if self.builtin_path(template_id) is not None:
            raise PermissionError("内置模板只读，请先复制为我的模板再编辑")
        with get_conn() as conn:
            row = conn.execute(
                "SELECT type, name, version FROM format_templates "
                "WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            raise KeyError(f"模板不存在: {template_id}")
        if row["type"] != "mine":
            raise PermissionError("内置模板只读，请先复制为我的模板再编辑")
        meta = content.meta
        meta.id = template_id
        meta.type = TemplateType.MINE
        meta.builtin = False
        meta.legacy = False
        meta.version = (row["version"] or 1) + 1
        content.schema_version = content.schema_version or CURRENT_SCHEMA_VERSION
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE format_templates
                SET name = ?, school_name = ?, major = ?, paper_type = ?,
                    category = ?, description = ?, version = ?,
                    schema_version = ?, content = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    meta.name or row["name"] or "未命名模板",
                    meta.school_name, meta.major, meta.paper_type,
                    meta.category, meta.description,
                    meta.version, content.schema_version,
                    json.dumps(content.to_dict(), ensure_ascii=False),
                    _now(), template_id,
                ),
            )
        return self.get(template_id)

    def delete(self, template_id: str) -> bool:
        """删除我的模板。内置模板不可删除（返回 False）。"""
        # 内置保护不依赖 DB 注册状态
        if self.builtin_path(template_id) is not None:
            return False
        with get_conn() as conn:
            row = conn.execute(
                "SELECT type FROM format_templates WHERE id = ?",
                (template_id,)).fetchone()
        if row is None or row["type"] != "mine":
            return False
        mine_dir = self._safe_mine_dir(template_id)
        with get_conn() as conn:
            conn.execute("DELETE FROM format_templates WHERE id = ?",
                         (template_id,))
        if mine_dir is not None:
            shutil.rmtree(mine_dir, ignore_errors=True)
        return True

    # ------------------------------------------------------------------
    # 状态：收藏 / 默认（存储操作）
    # ------------------------------------------------------------------
    def set_favorite(self, template_id: str, favorite: bool) -> bool:
        """设置收藏状态。返回是否生效。"""
        self._ensure_builtin_rows()  # 确保内置模板已注册（状态存储一致）
        with get_conn() as conn:
            cur = conn.execute(
                "UPDATE format_templates SET is_favorite = ?, updated_at = ? "
                "WHERE id = ?", (1 if favorite else 0, _now(), template_id))
            return cur.rowcount > 0

    def set_default(self, template_id: str) -> bool:
        """设为默认模板（全局唯一约束）。返回是否生效。"""
        self._ensure_builtin_rows()  # 确保内置模板已注册（状态存储一致）
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM format_templates WHERE id = ?",
                (template_id,)).fetchone()
            if row is None:
                return False
            conn.execute("UPDATE format_templates SET is_default = 0")
            conn.execute(
                "UPDATE format_templates SET is_default = 1, updated_at = ? "
                "WHERE id = ?", (_now(), template_id))
        return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _ensure_builtin_rows(self) -> None:
        """把内置模板注册进 DB 状态行（content 留空），供收藏/默认统一管理。"""
        with get_conn() as conn:
            for template_id, path in self.builtin_files().items():
                try:
                    meta = self.loader.load_meta(path, template_id=template_id)
                except TemplateLoadError:
                    continue
                conn.execute(
                    """
                    INSERT INTO format_templates
                        (id, name, school_name, major, paper_type, type,
                         category, description, version, schema_version,
                         source, content, parent_id, is_favorite, is_default,
                         sort_order, dir, created_at, updated_at)
                    VALUES (?, ?, ?, '', '', ?, ?, ?, ?, ?, ?, NULL, NULL,
                            0, 0, 0, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        school_name = excluded.school_name,
                        type = excluded.type,
                        category = excluded.category,
                        description = excluded.description,
                        version = excluded.version,
                        schema_version = excluded.schema_version,
                        source = excluded.source,
                        dir = excluded.dir,
                        updated_at = excluded.updated_at
                    """,
                    (
                        template_id, meta.name, meta.school_name,
                        meta.type.value, meta.category, meta.description,
                        meta.version, meta.schema_version, meta.source,
                        str(path.parent), _now(), _now(),
                    ),
                )

    def _safe_mine_dir(self, template_id: str) -> Path | None:
        """返回属于 mine 根目录的模板目录；路径异常时返回 None。"""
        with get_conn() as conn:
            row = conn.execute(
                "SELECT dir FROM format_templates WHERE id = ?",
                (template_id,)).fetchone()
        if row is None or not row["dir"]:
            return None
        d = Path(row["dir"]).resolve()
        mine_root = (self.root / "mine").resolve()
        if d == mine_root or not d.is_relative_to(mine_root):
            return None
        return d

    def _default_order(self) -> str:
        return ("CASE WHEN type='basic' THEN 0 "
                "WHEN type='school' THEN 1 ELSE 2 END, sort_order, created_at")

    @staticmethod
    def _row_to_meta(row: sqlite3.Row) -> TemplateMeta:
        """DB 行 → TemplateMeta（字段映射，缺失兜底）。"""
        try:
            ttype = TemplateType(row["type"])
        except ValueError:
            ttype = TemplateType.MINE
        return TemplateMeta(
            id=row["id"],
            name=row["name"] or "",
            type=ttype,
            school_name=row["school_name"] or "",
            school=row["school_name"] or "",
            major=row["major"] or "",
            paper_type=row["paper_type"] or "",
            category=row["category"] or "",
            description=row["description"] or "",
            version=row["version"] or 1,
            schema_version=row["schema_version"]
            or CURRENT_SCHEMA_VERSION,
            builtin=False,
            source=row["source"] or "db",
            parent_id=row["parent_id"],
            is_favorite=bool(row["is_favorite"]),
            is_default=bool(row["is_default"]),
            sort_order=row["sort_order"] or 0,
            legacy=bool(row["legacy"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
