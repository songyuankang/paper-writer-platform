"""参考文献格式化与一致性检查（委托 paper-writer 引擎，逻辑不变）。"""

from __future__ import annotations

import json
from pathlib import Path

from app.formatter.style import engine


def write_reference_deliverables(task_dir: Path, spec: dict,
                                 style_name: str) -> dict | None:
    """写 references.json；结构化条目走格式化+检查，字符串文献直接使用。"""
    _, _, references = engine()
    refs = spec.get("references", [])
    (task_dir / "references.json").write_text(
        json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = None
    if refs and isinstance(refs[0], dict):
        formatted = references.format_references(refs, style_name, "numeric")
        for item in spec["sections"]:
            if item.get("type") == "references":
                item["items"] = formatted
        stats = references.check_references(spec, refs, style_name, "numeric")
        (task_dir / "ReferenceCheck.md").write_text(
            references.render_check(stats, style_name, "numeric"),
            encoding="utf-8")
    else:
        for item in spec["sections"]:
            if item.get("type") == "references":
                item["items"] = refs
    return stats
