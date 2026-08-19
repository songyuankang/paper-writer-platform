"""Task quality reporting for citation and delivery review."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.generate import GenerateRequest


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def build_quality_report(task_dir: Path, request: "GenerateRequest") -> dict:
    """Build a conservative quality report for a completed or in-progress task."""
    content_refs = _read_json(task_dir / "paper_content" / "references.json", [])
    generated_refs = len(content_refs) if isinstance(content_refs, list) else 0
    supplied_refs = len([ref for ref in request.references if str(ref).strip()])
    warnings: list[dict] = []
    if generated_refs == 0 and supplied_refs == 0:
        warnings.append({"code": "no_references_registered", "message": "未发现用户提供或已生成的参考文献，正文论断需要人工核验。"})
    else:
        warnings.append({"code": "citations_pending_review", "message": "参考文献元数据已记录，但正文论断与来源片段尚未完成逐句核验。", "provided_reference_count": supplied_refs, "generated_reference_count": generated_refs})
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_title": request.title,
        "status": "review_required",
        "formal_export_ready": True,
        "export_level": "review_required",
        "citations": {"provided_reference_count": supplied_refs, "generated_reference_count": generated_refs, "verification_status": "pending_manual_review"},
        "blockers": [],
        "warnings": warnings,
        "next_actions": ["核验正文关键论断与参考文献的支持关系。", "将本报告与正文和参考文献一并审阅后再导出正式版本。"],
    }


def write_quality_report(task_dir: Path, request: "GenerateRequest") -> dict:
    report = build_quality_report(task_dir, request)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 论文生成质量报告", "", f"- 任务标题：{report['task_title']}",
        f"- 生成时间：{report['generated_at']}", f"- 交付级别：{report['export_level']}",
        "", "## 引用状态", "",
        f"- 用户提供参考文献：{report['citations']['provided_reference_count']}",
        f"- 已生成参考文献：{report['citations']['generated_reference_count']}",
        "- 逐句论断—来源核验：待人工复核", "", "## 阻断项", "", "- 无阻断项。", "", "## 下一步", "",
    ]
    lines.extend([f"- {item}" for item in report["next_actions"]])
    (task_dir / "QualityReport.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
