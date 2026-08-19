"""Deterministic outline diagnostics for the editable draft workflow.

The module deliberately uses rules instead of another model call so the outline
review is explainable, fast and free of additional API charges.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


TECHNICAL_TERMS = (
    "算法", "模型", "深度学习", "机器学习", "神经网络", "检测", "识别",
    "剪枝", "量化", "嵌入式", "部署", "系统", "控制", "优化", "推理",
)
EMPIRICAL_TERMS = (
    "实证", "问卷", "回归", "影响", "机制", "样本", "面板", "假设", "变量",
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
    if any(term in text for term in TECHNICAL_TERMS):
        return "technical"
    if any(term in text for term in EMPIRICAL_TERMS):
        return "empirical"
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


def evaluate_outline(
    paper_info: dict[str, Any],
    sections: list[dict[str, Any]],
    *, source: str,
    fallback_reason: str | None = None,
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

    title_terms = [term for term in re.split(r"[^\w\u4e00-\u9fff]+", str(paper_info.get("title") or "")) if len(term) >= 2]
    title_hits = sum(1 for term in title_terms if _norm(term) in joined)
    entity_coverage = round(title_hits / len(title_terms), 2) if title_terms else 0.0
    generic_count = sum(1 for title in titles if title.strip() in GENERIC_TITLES)
    top_sections = [item for item in sections if int(item.get("level") or 1) == 1]
    generic_ratio = round(generic_count / max(len(top_sections), 1), 2)
    score = int(round((sum(coverage.values()) / max(len(coverage), 1)) * 70 + min(entity_coverage, 1) * 20 + (10 if source == "ai" else 0)))
    issues: list[str] = []
    missing = [required_elements(research_type)[index] for index, ok in enumerate(coverage.values()) if not ok]
    if source == "fallback":
        issues.append("当前目录来自通用回退模板，不代表模型已按题目定制。")
    if missing:
        issues.append("缺少关键结构：" + "、".join(missing) + "。")
    if generic_ratio >= 0.6:
        issues.append("目录中的通用章节比例较高，题目实体覆盖不足。")
    if not paper_info.get("references"):
        issues.append("未传入已确认参考文献，大纲的文献综述与研究边界较弱。")

    recommendations: list[str] = []
    if source == "fallback":
        recommendations.append("建议重新生成定制大纲，或手动编辑后再确认。")
    if research_type == "technical":
        recommendations.append("技术论文应明确方法设计、实验设置、性能对比/消融与部署验证。")
    elif research_type == "empirical":
        recommendations.append("实证研究应明确理论机制、数据变量、模型设定与结果检验。")
    elif research_type == "review":
        recommendations.append("综述论文应按主题、演进或争议组织，而非套用实证研究结构。")
    if not paper_info.get("references"):
        recommendations.append("返回参考文献步骤至少选择一条文献，再重新生成大纲。")

    return {
        "version": version,
        "source": source,
        "fallback_reason": fallback_reason,
        "research_type": research_type,
        "required_elements": required_elements(research_type),
        "coverage": coverage,
        "entity_coverage": entity_coverage,
        "template_risk": "high" if source == "fallback" or generic_ratio >= 0.6 else "low",
        "score": score,
        "issues": issues,
        "recommendations": recommendations,
        "confirmation_required": True,
        "confirmed": False,
        "confirmed_at": None,
        "created_at": _now(),
    }
