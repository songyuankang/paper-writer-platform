"""Deterministic, explainable diagnostics for editable draft outlines."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.draft.outline_entities import entity_coverage_details


TECHNICAL_TERMS = (
    "算法", "模型", "深度学习", "机器学习", "神经网络", "检测", "识别",
    "剪枝", "量化", "嵌入式", "部署", "系统", "控制", "优化", "推理",
)
EMPIRICAL_TERMS = (
    "实证", "问卷", "回归", "影响", "机制", "样本", "面板", "假设", "变量",
    "调节效应", "中介效应", "共同富裕", "收入差距", "基尼", "泰尔", "分配",
)
REVIEW_TERMS = ("综述", "进展", "述评", "研究现状")

REQUIRED_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "technical": {
        "method": ("方法", "算法", "模型", "方案", "设计", "策略", "框架"),
        "experiment": ("实验", "验证", "测试", "评估", "结果", "性能"),
        "comparison": ("对比", "消融", "分析", "讨论", "部署", "实现"),
    },
    "empirical": {
        "theory": ("理论", "机制", "假设", "文献"),
        "data": ("数据", "样本", "变量", "模型", "设计"),
        "analysis": ("实证", "结果", "回归", "稳健", "分析"),
    },
    "review": {
        "scope": ("概念", "范畴", "研究现状", "主题"),
        "synthesis": ("比较", "演进", "述评", "争议"),
        "outlook": ("不足", "展望", "方向", "结论"),
    },
    "general": {
        "background": ("背景", "绪论", "引言", "问题"),
        "analysis": ("分析", "方法", "研究", "讨论"),
        "conclusion": ("结论", "总结", "展望"),
    },
}

GENERIC_TITLES = {
    "绪论", "引言", "研究设计", "结果与分析", "结论与展望", "结论",
    "文献综述", "文献综述与理论基础", "理论基础", "主要内容概述", "重点问题分析",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def classify_research(paper_info: dict[str, Any]) -> str:
    text = _norm(" ".join([
        str(paper_info.get("title") or ""),
        str(paper_info.get("abstract") or ""),
        " ".join(str(item) for item in (paper_info.get("keywords") or [])),
        str(paper_info.get("special_requirements") or ""),
    ]))
    # 明确的实证研究信号优先于“系统/模型”等泛化技术词，避免经济学、管理学
    # 题目因摘要中的系统性表述而被错误分类为技术论文。
    if any(term in text for term in EMPIRICAL_TERMS):
        return "empirical"
    if any(term in text for term in TECHNICAL_TERMS):
        return "technical"
    if any(term in text for term in REVIEW_TERMS):
        return "review"
    return "general"


def required_elements(research_type: str) -> list[str]:
    labels = {
        "technical": ["方法/算法或系统设计", "实验或性能验证", "对比、消融、部署或结果分析"],
        "empirical": ["理论机制或研究假设", "数据、变量或研究设计", "实证结果或稳健性分析"],
        "review": ["研究主题范围", "比较、演进或研究述评", "研究不足与未来方向"],
        "general": ["研究背景或问题", "核心分析或研究方法", "结论、总结或展望"],
    }
    return labels.get(research_type, labels["general"])


def _structure_validity(sections: list[dict[str, Any]]) -> int:
    if not sections:
        return 0
    levels = [int(item.get("level") or 0) for item in sections]
    roots = [item for item in sections if int(item.get("level") or 0) == 1]
    if any(level < 1 or level > 3 for level in levels) or not roots:
        return 10
    if len(roots) >= 3 and all((item.get("title") or "").strip() for item in sections):
        return 30
    return 22


def _logic_score(top_sections: list[dict[str, Any]]) -> int:
    titles = [_norm(str(item.get("title") or "")) for item in top_sections]
    duplicate = len(titles) != len(set(titles))
    if 4 <= len(top_sections) <= 7 and not duplicate:
        return 6
    if len(top_sections) >= 3 and not duplicate:
        return 3
    return 0


def _first_chapter_role_conflicts(sections: list[dict[str, Any]], research_type: str) -> list[dict[str, str]]:
    """找出被错误塞进绪论的主体章节职责。

    对实证论文，第一章可包含背景、现状、意义与研究内容，但不能提前放入
    完整假设、研究设计、数据变量、回归/实证、异质性或结论建议。技术论文
    仍允许第一章存在研究内容概述，不套用这一严格规则。
    """
    if research_type != "empirical":
        return []
    forbidden = ("研究假设", "理论模型", "研究设计", "变量", "数据来源", "计量模型", "回归", "实证", "稳健", "异质", "结果分析", "主要研究结论", "结论与", "政策建议")
    conflicts: list[dict[str, str]] = []
    for section in sections:
        sid = str(section.get("id") or "")
        if not sid.startswith("1-"):
            continue
        title = str(section.get("title") or "")
        gist = str(section.get("gist") or "")
        matched = next((term for term in forbidden if term in title or term in gist), "")
        if matched:
            conflicts.append({
                "section_id": sid,
                "number": str(section.get("number") or ""),
                "title": title,
                "matched_role": matched,
            })
    return conflicts


def evaluate_outline(
    paper_info: dict[str, Any],
    sections: list[dict[str, Any]],
    *, source: str,
    fallback_reason: str | None = None,
    fallback_kind: str | None = None,
    version: int = 1,
) -> dict[str, Any]:
    research_type = classify_research(paper_info)
    titles = [str(item.get("title") or "") for item in sections]
    joined = _norm(" ".join(titles))
    groups = REQUIRED_GROUPS[research_type]
    coverage: dict[str, bool] = {
        key: any(_norm(term) in joined for term in terms)
        for key, terms in groups.items()
    }
    entity_matches = entity_coverage_details(str(paper_info.get("title") or ""), sections)
    entity_total = len(entity_matches)
    entity_hits = sum(1 for item in entity_matches if item["matched_terms"])
    entity_coverage = round(entity_hits / entity_total, 2) if entity_total else 0.0
    top_sections = [item for item in sections if int(item.get("level") or 1) == 1]
    generic_count = sum(1 for item in top_sections if str(item.get("title") or "").strip() in GENERIC_TITLES)
    generic_ratio = round(generic_count / max(len(top_sections), 1), 2)
    chapter_role_conflicts = _first_chapter_role_conflicts(sections, research_type)

    structure_score = _structure_validity(sections)
    entity_score = int(round(entity_coverage * 25))
    research_type_score = int(round((sum(coverage.values()) / max(len(coverage), 1)) * 15))
    group_keys = list(groups)
    method_score = 12 if coverage.get(group_keys[0], False) else 0
    experiment_score = 12 if coverage.get(group_keys[1], False) else 0
    logic_score = _logic_score(top_sections)
    score = structure_score + entity_score + research_type_score + method_score + experiment_score + logic_score
    # Zero topic evidence is never a high-quality customized outline, regardless of source.
    if entity_total and entity_coverage == 0:
        score = min(score, 55)
    elif entity_total and entity_coverage < 0.3:
        score = min(score, 65)
    if chapter_role_conflicts:
        score = min(score, 45)
    score = max(0, min(score, 100))
    score_breakdown = {
        "structure": structure_score,
        "entity": entity_score,
        "research_type": research_type_score,
        "method": method_score,
        "experiment": experiment_score,
        "logic": logic_score,
    }

    issues: list[str] = []
    missing = [required_elements(research_type)[index] for index, ok in enumerate(coverage.values()) if not ok]
    if source == "fallback":
        if fallback_kind == "topic":
            issues.append("当前目录来自题目化保底模板，建议在模型可用后重新生成并核对章节主旨。")
        else:
            issues.append("当前目录来自通用回退模板，不代表模型已按题目定制。")
    if missing:
        issues.append("缺少关键结构：" + "、".join(missing) + "。")
    unmatched = [item["entity"] for item in entity_matches if not item["matched_terms"]]
    if unmatched:
        issues.append("未覆盖题目实体：" + "、".join(unmatched) + "。")
    if generic_ratio >= 0.6:
        issues.append("目录中的通用章节比例较高，题目实体覆盖不足。")
    if chapter_role_conflicts:
        labels = "、".join(f"{item['number']} {item['title']}".strip() for item in chapter_role_conflicts)
        issues.append("第一章职责越界，已提前包含研究设计、实证或结论主体：" + labels + "。")
    if not paper_info.get("references"):
        issues.append("未传入已确认参考文献，大纲的文献综述与研究边界较弱。")

    recommendations: list[str] = []
    if source == "fallback":
        recommendations.append("建议重新生成定制大纲，或手动编辑后再确认。")
    if research_type == "technical":
        recommendations.append("技术论文应明确方法设计、实验设置、性能对比/消融与部署验证。")
    elif research_type == "empirical":
        recommendations.append("实证研究应明确理论机制、数据变量、模型设定与结果检验。")
        if chapter_role_conflicts:
            recommendations.append("第一章仅保留研究背景、研究现状、意义和研究思路；将假设、数据设计、实证、异质性与结论拆入后续章节。")
    elif research_type == "review":
        recommendations.append("综述论文应按主题、演进或争议组织，而非套用实证研究结构。")
    if not paper_info.get("references"):
        recommendations.append("返回参考文献步骤至少选择一条文献，再重新生成大纲。")

    return {
        "version": version,
        "source": source,
        "fallback_reason": fallback_reason,
        "fallback_kind": fallback_kind,
        "research_type": research_type,
        "required_elements": required_elements(research_type),
        "coverage": coverage,
        "entity_coverage": entity_coverage,
        "entity_matches": entity_matches,
        "score_breakdown": score_breakdown,
        "chapter_role_conflicts": chapter_role_conflicts,
        "template_risk": "high" if source == "fallback" or generic_ratio >= 0.6 or entity_coverage < 0.3 or chapter_role_conflicts else "low",
        "score": score,
        "issues": issues,
        "recommendations": recommendations,
        "confirmation_required": True,
        "confirmed": False,
        "confirmed_at": None,
        "created_at": _now(),
    }
