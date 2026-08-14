"""格式处理编排：把 paper_content（markdown/json）转换为 docx 及交付物。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.config import settings
from app.formatter import docx_builder, reference as reference_mod, style as style_mod
from app.services.content_generator import inject_charts_into_sections
from app.services import revise_service

logger = logging.getLogger(__name__)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


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
                 charts: list[dict] | None = None,
                 template_path: Path | None = None,
                 template_id: str | None = None,
                 build_docx: bool = True) -> list[str]:
    """格式化：注入图表 → 同步 content.json → （可选）docx → 参考文献 → 检查报告 → 格式意见。

    - ``template_id``：指定 v2 排版模板（如 basic-general-thesis）。非 None 时
      走「spec 转换 → TemplateRenderer」新链路；None 保持旧 docx_builder 行为。
      新链路异常时回退旧构建器，保证不破坏现有生成流程。
    - ``build_docx``：False 时跳过 docx 渲染（论文生成阶段不产出最终 Word，
      由导出接口按所选模板渲染），其余产物（spec / content / 参考文献 / 格式意见）保留。
    """
    if charts:
        spec["sections"] = inject_charts_into_sections(spec["sections"], charts)

    (task_dir / "paper_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    revise_service.save_content(task_dir, revise_service.spec_to_content(spec))

    # 学校模板报告（可选，旧模板路径）
    template_report = None
    if template_path is not None and template_path.exists():
        profile = style_mod.parse_template_profile(template_path)
        template_report = task_dir / "TemplateReport.md"
        template_report.write_text(
            style_mod.render_template_report(profile), encoding="utf-8")

    ref_style = paper_info.get("reference_style", "gb7714")

    # ---- docx：优先新 TemplateRenderer 链路（build_docx=False 时跳过，导出时再渲染）----
    if build_docx:
        rendered = False
        if template_id is not None:
            from app.formatter.template import render_service
            try:
                # 先格式化参考文献（供渲染使用），再渲染
                reference_mod.write_reference_deliverables(task_dir, spec, ref_style)
                render_service.render_with_template(
                    template_id, task_dir, spec, paper_info=paper_info)
                rendered = True
            except Exception as exc:  # noqa: BLE001 - 新链路失败不阻塞生成
                logger.warning("TemplateRenderer 渲染失败，回退旧构建器: %s", exc)
        if not rendered:
            docx_builder.build_docx(task_dir, spec, spec.get("meta", {}),
                                    template_path=template_path)
            reference_mod.write_reference_deliverables(task_dir, spec, ref_style)

    # 格式意见整理
    (task_dir / "格式意见整理.md").write_text(
        _format_review(task_id, task_dir, paper_info, spec, template_report),
        encoding="utf-8")
    return sorted(str(p.relative_to(task_dir)).replace("\\", "/")
                  for p in task_dir.rglob("*")
                  if p.is_file() and p.name not in ("task.json", "request.json"))


def _format_review(task_id: str, task_dir: Path, paper_info: dict, spec: dict,
                   template_report: Path | None) -> str:
    hanzi = sum(len(CJK_RE.findall(s.get("text", "")))
                for s in spec.get("sections", [])
                if s.get("type") in ("p", "h1", "h2", "h3"))
    chart_note = ""
    req = paper_info
    if req.get("chart_config") is not None:
        chart_note = f"已生成 {req['chart_config'].get('count', 0)} 张示例图表" \
            if req["chart_config"].get("enabled") else "未生成"
    elif req.get("chart_enabled"):
        chart_note = "已生成示例图表"
    else:
        chart_note = "未生成"
    lines = [
        "# 格式意见整理",
        "",
        f"- 任务：{task_id}",
        f"- 题目：{req.get('title', '')}",
        f"- 目标字数：{req.get('word_count', 0)} 字；实际汉字数：{hanzi} 字",
        "",
        "## 检查结果",
        "",
        "| 分类 | 要求 | 现状 | 处理建议 | 优先级 |",
        "| --- | --- | --- | --- | --- |",
        "| 整体版面 | A4、合理页边距、行距 | 默认/模板排版已应用 | 无需处理 | 低 |",
        "| 标题层级 | 标题层级清晰 | 已按结构生成 | 无需处理 | 低 |",
        "| 摘要与关键词 | 摘要 200–500 字、关键词 3–5 个 | 已生成 | 人工审阅 | 中 |",
        "| 正文 | 规范学术中文、内容完整 | 已生成 | 人工审阅 | 中 |",
        f"| 图表 | 图表编号、题注、正文引用 | {chart_note} | "
        f"{'替换为真实数据并核对引用' if chart_note != '未生成' else '如需图表请在图表设置中开启'} | 中 |",
        f"| 参考文献 | 格式 {req.get('reference_style', 'gb7714')}、正文引用对应 | 已生成 | 人工核验 | 中 |",
        "| 字数 | 达到目标字数 | 见上方统计 | 不足可扩写 | 中 |",
        "",
        "## 说明",
        "",
        "本文内容由 AI 分段生成；示例数据与示例文献需人工替换。",
    ]
    if template_report is not None:
        lines += ["", "学校模板解析报告见 `TemplateReport.md`（请按兼容度缺失项核对）。"]
    check_file = task_dir / "paper_check_result.json"
    if check_file.exists():
        try:
            check = json.loads(check_file.read_text(encoding="utf-8"))
            lines += ["", "## 全文检查（AI）", ""]
            for p in check.get("problems", []):
                lines.append(f"- ⚠ {p}")
            for s in check.get("suggestions", []):
                lines.append(f"- 建议：{s}")
        except json.JSONDecodeError:
            pass
    return "\n".join(lines) + "\n"
