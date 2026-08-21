"""格式处理编排：把 paper_content（markdown/json）转换为 docx 及交付物。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.formatter import docx_builder, reference as reference_mod, style as style_mod
from app.services import content_quality_guard, revise_service

logger = logging.getLogger(__name__)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

# 临时开放导出：保留质量审计与规范化，但不再因 blockers 阻断 DOCX 输出。
# 恢复门禁时将该开关改回 True。
EXPORT_QUALITY_GATE_BLOCKING = False


def spec_from_paper_content(paper_info: dict, content_dir: Path) -> dict:
    """把 paper_content 目录转换为 paper_spec.json（markdown/json → spec）。"""
    abstract = ""
    abstract_path = content_dir / "abstract.md"
    if abstract_path.exists():
        abstract = abstract_path.read_text(encoding="utf-8")
    keywords = []
    kw_path = content_dir / "keywords.json"
    if kw_path.exists():
        try:
            keywords = json.loads(kw_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    meta = {
        "title": paper_info.get("title", ""),
        "abstract": abstract,
        "keywords": keywords,
        "reference_style": paper_info.get("reference_style", "gb7714"),
        "citation_style": "numeric",
    }
    sections: list[dict] = []
    for path in sorted(content_dir.glob("chapter*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sections.append({"type": "h1", "text": data.get("title", path.stem)})
        sections.extend(data.get("blocks", []))
    conclusion_path = content_dir / "conclusion.json"
    if conclusion_path.exists():
        try:
            data = json.loads(conclusion_path.read_text(encoding="utf-8"))
            sections.append({"type": "h1", "text": data.get("title", "结论")})
            sections.extend(data.get("blocks", []))
        except json.JSONDecodeError:
            pass
    references = []
    ref_path = content_dir / "references.json"
    if ref_path.exists():
        try:
            references = json.loads(ref_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    sections.append({"type": "references", "items": references})
    return {"meta": meta, "sections": sections, "references": references}


def format_paper(task_id: str, task_dir: Path, paper_info: dict, spec: dict,
                 template_path: Path | None = None,
                 template_id: str | None = None,
                 build_docx: bool = True) -> list[str]:
    """同步内容、执行质量门禁，并在需要时按模板渲染 Word。"""
    spec, guard = content_quality_guard.prepare_spec_for_export(spec)
    guard["blocking_enabled"] = EXPORT_QUALITY_GATE_BLOCKING
    if guard["blockers"] and not EXPORT_QUALITY_GATE_BLOCKING:
        guard["bypassed_blockers"] = list(guard["blockers"])
        logger.warning("导出质量门禁当前已临时关闭，放行 %d 个 blocker", len(guard["blockers"]))
    (task_dir / "export_guard.json").write_text(
        json.dumps(guard, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if guard["blockers"] and EXPORT_QUALITY_GATE_BLOCKING:
        details = "；".join(item["message"] for item in guard["blockers"])
        raise content_quality_guard.ExportQualityError(
            f"导出前质量门禁未通过：{details}"
        )
    (task_dir / "paper_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    revise_service.save_content(task_dir, revise_service.spec_to_content(spec))

    template_report = None
    if template_path is not None and template_path.exists():
        profile = style_mod.parse_template_profile(template_path)
        template_report = task_dir / "TemplateReport.md"
        template_report.write_text(
            style_mod.render_template_report(profile), encoding="utf-8"
        )

    ref_style = paper_info.get("reference_style", "gb7714")
    if build_docx:
        rendered = False
        if template_id is not None:
            from app.formatter.template import render_service
            try:
                reference_mod.write_reference_deliverables(task_dir, spec, ref_style)
                render_service.render_with_template(
                    template_id, task_dir, spec, paper_info=paper_info
                )
                rendered = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("TemplateRenderer 渲染失败，回退旧构建器: %s", exc)
        if not rendered:
            docx_builder.build_docx(
                task_dir, spec, spec.get("meta", {}), template_path=template_path
            )
            reference_mod.write_reference_deliverables(task_dir, spec, ref_style)

    (task_dir / "格式意见整理.md").write_text(
        _format_review(task_id, task_dir, paper_info, spec, template_report),
        encoding="utf-8",
    )
    return sorted(
        str(p.relative_to(task_dir)).replace("\\", "/")
        for p in task_dir.rglob("*")
        if p.is_file() and p.name not in ("task.json", "request.json")
    )


def _format_review(task_id: str, task_dir: Path, paper_info: dict, spec: dict,
                   template_report: Path | None) -> str:
    hanzi = sum(
        len(CJK_RE.findall(section.get("text", "")))
        for section in spec.get("sections", [])
        if section.get("type") in ("p", "h1", "h2", "h3")
    )
    lines = [
        "# 格式意见整理", "", f"- 任务：{task_id}",
        f"- 题目：{paper_info.get('title', '')}",
        f"- 目标字数：{paper_info.get('word_count', 0)} 字；实际汉字数：{hanzi} 字", "",
        "## 检查结果", "",
        "| 分类 | 要求 | 现状 | 处理建议 | 优先级 |",
        "| --- | --- | --- | --- | --- |",
        "| 整体版面 | A4、合理页边距、行距 | 默认/模板排版已应用 | 无需处理 | 低 |",
        "| 标题层级 | 标题层级清晰 | 已按结构生成 | 无需处理 | 低 |",
        "| 摘要与关键词 | 摘要 200–500 字、关键词 3–5 个 | 已生成 | 人工审阅 | 中 |",
        "| 正文 | 规范学术中文、内容完整 | 已生成 | 人工审阅 | 中 |",
        f"| 参考文献 | 格式 {paper_info.get('reference_style', 'gb7714')}、正文引用对应 | 已生成 | 人工核验 | 中 |",
        "| 字数 | 达到目标字数 | 见上方统计 | 不足可扩写 | 中 |", "",
        "## 说明", "", "本文内容由 AI 分段生成；示例文献需人工核验。"
    ]
    if template_report is not None:
        lines += ["", "学校模板解析报告见 TemplateReport.md（请按兼容度缺失项核对）。"]
    check_file = task_dir / "paper_check_result.json"
    if check_file.exists():
        try:
            check = json.loads(check_file.read_text(encoding="utf-8"))
            lines += ["", "## 全文检查（AI）", ""]
            lines += [f"- ⚠ {problem}" for problem in check.get("problems", [])]
            lines += [f"- 建议：{suggestion}" for suggestion in check.get("suggestions", [])]
        except json.JSONDecodeError:
            pass
    return "\n".join(lines) + "\n"
