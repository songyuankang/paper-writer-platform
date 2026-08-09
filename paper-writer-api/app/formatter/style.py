"""格式样式与模板解析（委托 paper-writer 引擎，逻辑不变）。"""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def engine():
    import sys
    scripts = settings.paper_writer_scripts_dir
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import build_docx  # noqa: F401
    import parse_template  # noqa: F401
    import references  # noqa: F401
    return build_docx, parse_template, references


def parse_template_profile(template_path: Path) -> dict:
    _, parse_template, _ = engine()
    return parse_template.parse_document(str(template_path))


def render_template_report(profile: dict) -> str:
    _, parse_template, _ = engine()
    return parse_template.render_report(profile)
