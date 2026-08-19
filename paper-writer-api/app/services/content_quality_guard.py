"""Pre-export content integrity checks for generated papers.

The guard runs after charts are injected into the paper spec and before any Word
file is created. It prevents system errors and untraceable citation structures
from being published as a paper.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExportQualityError(ValueError):
    """Raised when generated content is unsafe to export as a Word paper."""


_BLOCKED_TOKENS = (
    "生成结果为空",
    "请检查模型配置",
    "模型调用失败",
    "模型生成失败",
    "生成失败，请",
    "内容生成失败",
)
_MARKDOWN_ONLY = re.compile(r"^\s*(?:#{1,6}|```+|TODO|TBD)\s*$", re.IGNORECASE)
_CITATION = re.compile(r"\[(\d+)\]")
_REFERENCE_NUMBER = re.compile(r"^\s*\[(\d+)\]\s*")
_TABLE_REFERENCE = re.compile(r"表(\d+-\d+)")
_FIGURE_REFERENCE = re.compile(r"图(\d+-\d+)")
_CAPTION_NUMBER = re.compile(r"^[图表](\d+-\d+)")


def _section_text(section: dict[str, Any]) -> str:
    kind = str(section.get("type") or "")
    if kind == "table":
        return " ".join(
            [str(section.get("title") or ""), *map(str, section.get("headers") or [])]
            + [str(value) for row in section.get("rows") or [] for value in row]
        )
    return str(section.get("text") or section.get("title") or "")


def number_references(items: list[Any]) -> list[str]:
    """Return numeric references without double-numbering existing entries."""
    normalized: list[str] = []
    for index, item in enumerate(items, start=1):
        text = str(item).strip()
        if not text:
            continue
        if _REFERENCE_NUMBER.match(text):
            normalized.append(text)
        else:
            normalized.append(f"[{index}] {text}")
    return normalized


def _strip_unresolved_visual_references(
    text: str, table_numbers: set[str], figure_numbers: set[str]
) -> tuple[str, list[str]]:
    """删除模型虚构、但草稿中不存在实体块的表图交叉引用。

    草稿编辑器当前不自动创建图表，旧任务中这类编号只能是模型占位文本。
    保留其余论述，并由导出报告记录警告，而非让用户无法导出整篇论文。
    """
    cleaned = text
    removed: list[str] = []
    for number in sorted(table_numbers):
        token = f"表{number}"
        pattern = re.compile(
            rf"(?:如|见|参见|详见)?\s*{re.escape(token)}\s*(?:所示|可知|显示|中)?"
        )
        if pattern.search(cleaned):
            cleaned = pattern.sub("", cleaned)
            removed.append(token)
    for number in sorted(figure_numbers):
        token = f"图{number}"
        pattern = re.compile(
            rf"(?:如|见|参见|详见)?\s*{re.escape(token)}\s*(?:所示|可知|显示|中)?"
        )
        if pattern.search(cleaned):
            cleaned = pattern.sub("", cleaned)
            removed.append(token)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"^[，、；;。]+", "", cleaned).strip()
    return cleaned, removed


def prepare_spec_for_export(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize safe chart prose and return a report; do not silently hide failures."""
    sections = list(spec.get("sections") or [])
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for index, section in enumerate(sections, start=1):
        text = _section_text(section)
        if not text:
            continue
        for token in _BLOCKED_TOKENS:
            if token in text:
                blockers.append({
                    "code": "generation_failure_marker",
                    "section_index": index,
                    "message": f"第 {index} 个内容块含生成失败标记“{token}”。",
                })
        if _MARKDOWN_ONLY.match(text):
            blockers.append({
                "code": "markdown_leak",
                "section_index": index,
                "message": f"第 {index} 个内容块残留 Markdown/调试标记“{text}”。",
            })
        if section.get("type") == "p":
            section["text"] = (
                text.replace("（示例数据，需替换为真实数据）。", "。")
                .replace("（示例数据，需替换为真实数据）", "")
                .replace("数据来源：数据来源：", "数据来源：")
            )

    # A numerical cross-reference is valid only when a matching table/figure block
    # exists in the same export spec. This prevents prose-only experiment claims.
    table_numbers = {
        match.group(1) for section in sections if section.get("type") == "table"
        if (match := _CAPTION_NUMBER.match(str(section.get("title") or "")))
    }
    figure_numbers = {
        match.group(1) for section in sections if section.get("type") == "figure"
        if (match := _CAPTION_NUMBER.match(str(section.get("title") or "")))
    }
    referenced_tables = {number for text in (_section_text(s) for s in sections)
                       for number in _TABLE_REFERENCE.findall(text)}
    referenced_figures = {number for text in (_section_text(s) for s in sections)
                         for number in _FIGURE_REFERENCE.findall(text)}
    missing_tables = sorted(referenced_tables - table_numbers)
    missing_figures = sorted(referenced_figures - figure_numbers)
    unresolved_tables = set(missing_tables)
    unresolved_figures = set(missing_figures)
    removed_visual_references: list[str] = []
    if unresolved_tables or unresolved_figures:
        for section in sections:
            if section.get("type") != "p":
                continue
            cleaned, removed = _strip_unresolved_visual_references(
                str(section.get("text") or ""),
                unresolved_tables,
                unresolved_figures,
            )
            if removed:
                section["text"] = cleaned
                removed_visual_references.extend(removed)
    if removed_visual_references:
        warnings.append({
            "code": "unresolved_visual_reference_removed",
            "message": "已移除模型生成但无实体内容的表图引用：" + ", ".join(sorted(set(removed_visual_references))),
        })
    removed_tables = {number.removeprefix("表") for number in removed_visual_references if number.startswith("表")}
    removed_figures = {number.removeprefix("图") for number in removed_visual_references if number.startswith("图")}
    remaining_tables = sorted(unresolved_tables - removed_tables)
    remaining_figures = sorted(unresolved_figures - removed_figures)
    if remaining_tables:
        blockers.append({
            "code": "table_reference_not_resolved",
            "message": "正文引用但未生成的表格：" + ", ".join(f"表{n}" for n in remaining_tables),
        })
    if remaining_figures:
        blockers.append({
            "code": "figure_reference_not_resolved",
            "message": "正文引用但未生成的图表：" + ", ".join(f"图{n}" for n in remaining_figures),
        })

    raw_refs = list(spec.get("references") or [])
    normalized_refs = number_references(raw_refs)
    citations = sorted({int(number) for text in (_section_text(s) for s in sections)
                        for number in _CITATION.findall(text)})
    reference_numbers = {
        int(match.group(1)) for ref in normalized_refs
        if (match := _REFERENCE_NUMBER.match(ref))
    }
    missing_refs = [number for number in citations if number not in reference_numbers]
    if missing_refs:
        blockers.append({
            "code": "citation_not_closed",
            "message": "文内引文缺少对应参考文献：" + ", ".join(f"[{n}]" for n in missing_refs),
        })
    unused_refs = sorted(reference_numbers - set(citations))
    if unused_refs:
        warnings.append({
            "code": "unused_reference",
            "message": "以下参考文献未在正文中引用：" + ", ".join(f"[{n}]" for n in unused_refs),
        })

    normalized_sections: list[dict[str, Any]] = []
    for section in sections:
        if section.get("type") == "references":
            normalized_sections.append({**section, "items": normalized_refs})
        else:
            normalized_sections.append(section)
    spec = {**spec, "sections": normalized_sections, "references": normalized_refs}
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "ready_with_warnings" if warnings else "ready",
        "blockers": blockers,
        "warnings": warnings,
        "citation_numbers": citations,
        "reference_numbers": sorted(reference_numbers),
        "reference_count": len(normalized_refs),
        "table_numbers": sorted(table_numbers),
        "figure_numbers": sorted(figure_numbers),
    }
    return spec, report


def assert_exportable(spec: dict[str, Any], task_dir: Path) -> dict[str, Any]:
    """Write an audit record and stop Word export when blockers are present."""
    _, report = prepare_spec_for_export(spec)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "export_guard.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if report["blockers"]:
        message = "；".join(item["message"] for item in report["blockers"])
        raise ExportQualityError(f"导出前质量门禁未通过：{message}")
    return report
