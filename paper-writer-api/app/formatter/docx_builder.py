"""docx 构建：markdown/json → docx（字体、目录、页码、模板；逻辑不变）。"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.config import settings
from app.formatter.style import engine


def build_docx(task_dir: Path, spec: dict, meta: dict,
               out_name: str = "论文.docx",
               template_path: Path | None = None,
               toc_update: bool = True) -> str:
    """按默认格式或学校模板生成 docx。"""
    build_docx, parse_template, _ = engine()
    out_path = task_dir / out_name
    if template_path is not None and template_path.exists():
        profile = parse_template.parse_document(str(template_path))
        doc = Document(str(template_path))
        build_docx.build_with_template(doc, profile, spec, meta, task_dir)
    else:
        doc = build_docx.setup_document(meta)
        build_docx.build_default(doc, spec, meta, task_dir)
    if toc_update:
        from app.formatter.toc import mark_toc_update
        mark_toc_update(doc)
    doc.save(out_path)
    return out_name
