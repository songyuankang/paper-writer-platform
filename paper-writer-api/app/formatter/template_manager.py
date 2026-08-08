"""学校模板库：上传/解析/存储，位于 formatter/templates/<id>/。

每个模板目录包含：
  style.docx          上传的 Word 模板
  template.json       元数据（名称/学校/专业/论文类型/更新时间）
  rules.json          格式规则（目录/页码/标题编号/参考文献/图表）
  template_config.json 自动解析结果（页边距/字体/标题样式/行距/页眉页脚/目录规则）
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.db import get_conn
from app.formatter.style import engine

TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"

DEFAULT_RULES = {
    "toc": {"auto": True, "page_numbers": True, "title_numbering": True},
    "page": {"margins": {"top_cm": 3.0, "bottom_cm": 2.5,
                         "left_cm": 3.0, "right_cm": 2.5}},
    "reference": {"style": "gb7714", "auto_sort": True, "auto_number": True},
    "chart": {"numbering": "chapter", "position": "auto",
              "title_format": "图{chapter}-{index} {title}"},
    "fonts": {"east_asia": "宋体", "latin": "Times New Roman"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_default_template() -> None:
    """确保 formatter/templates/default/ 存在。"""
    default_dir = TEMPLATES_ROOT / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "template.json").write_text(
        json.dumps({
            "name": "默认模板",
            "school_name": "",
            "major": "",
            "paper_type": "",
            "updated_at": _now(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (default_dir / "rules.json").exists():
        (default_dir / "rules.json").write_text(
            json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2),
            encoding="utf-8")


def _extract_config(docx_path: Path) -> dict:
    """解析学校 Word 模板：页边距/字体/标题样式/行距/页眉页脚/目录规则。"""
    _, parse_template, _ = engine()
    profile = parse_template.parse_document(str(docx_path))
    return {
        "page": profile.get("page", {}),
        "fonts": profile.get("fonts", {}),
        "styles": profile.get("styles", {}),
        "cover": profile.get("cover", {}),
        "toc": profile.get("toc", {}),
        "compatibility": profile.get("compatibility", {}),
    }


def create_template(meta: dict, docx_bytes: bytes) -> dict:
    template_id = uuid.uuid4().hex
    template_dir = TEMPLATES_ROOT / template_id
    template_dir.mkdir(parents=True, exist_ok=True)
    style_path = template_dir / "style.docx"
    style_path.write_bytes(docx_bytes)
    now = _now()
    (template_dir / "template.json").write_text(
        json.dumps({
            "id": template_id,
            "name": meta.get("name", "未命名模板"),
            "school_name": meta.get("school_name", ""),
            "major": meta.get("major", ""),
            "paper_type": meta.get("paper_type", ""),
            "updated_at": now,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    (template_dir / "rules.json").write_text(
        json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
    config = _extract_config(style_path)
    (template_dir / "template_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO format_templates
                (id, name, school_name, major, paper_type, dir,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (template_id, meta.get("name", ""), meta.get("school_name", ""),
             meta.get("major", ""), meta.get("paper_type", ""),
             str(template_dir), now, now),
        )
    return get_template(template_id)


def get_template(template_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM format_templates WHERE id = ?", (template_id,)).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["config"] = _read_json(Path(record["dir"]) / "template_config.json")
    record["rules"] = _read_json(Path(record["dir"]) / "rules.json")
    return record


def list_templates() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM format_templates ORDER BY created_at ASC").fetchall()
    return [dict(row) for row in rows]


def delete_template(template_id: str) -> bool:
    record = get_template(template_id)
    if record is None:
        return False
    with get_conn() as conn:
        conn.execute("DELETE FROM format_templates WHERE id = ?", (template_id,))
    shutil.rmtree(Path(record["dir"]), ignore_errors=True)
    return True


def style_path(template_id: str | None) -> Path | None:
    if not template_id or template_id in ("default", "default_template"):
        return None
    record = get_template(template_id)
    if record is None:
        return None
    path = Path(record["dir"]) / "style.docx"
    return path if path.exists() else None


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def default_rules() -> dict:
    return dict(DEFAULT_RULES)
