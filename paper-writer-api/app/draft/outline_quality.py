"""Deterministic quality gate for the editable draft outline workflow.

The gate is deliberately local and explainable.  It distinguishes a displayable
fallback preview from an AI outline that is fit to start full-body generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

TECHNICAL_TERMS = (
    "算法", "模型", "深度学习", "机器学习", "神经网络", "检测", "识别",
    "剪枝", "量化", "嵌入式", "部署", "系统", "控制", "优化", "推理",
)
EMPIRICAL_ECONOMICS_TERMS = (
    "共同富裕", "第三次分配", "居民收入", "收入差距", "收入分配", "调节效应",
    "基尼", "泰尔", "慈善", "公益", "区域异质性", "政策效应",
)
EMPIRICAL_TERMS = (
    "实证", "问卷", "回归", "影响", "机制", "样本", "面板", "假设", "变量",
    "异质性", "稳健性", "中介效应", "调节效应",
)
REVIEW_TERMS = ("综述", "进展", "述评", "研究现状")

# The lexicon is intentionally small, deterministic and overlapping.  It fixes
# whitespace-tokenization failures for continuous Chinese paper titles without
# inventing entities from model output.
CHINESE_ENTITY_LEXICON = tuple(sorted(set(
    EMPIRICAL_ECONOMICS_TERMS
    + TECHNICAL_TERMS
    + (
        "目标检测", "轻量化", "边缘计算", "模型剪枝", "目标检测算法", "性能验证",
        "因果识别", "中介机制", "收入不平等", "社会保障", "绿色金融", "数字经济",
    )
), key=len, reverse=True))

REQUIRED_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "technical": {
        "method": ("方法", "算法", "模型", "方案", "设计", "策略", "框架"),
        "experiment": ("实验", "验证", "测试", "评估", "结果", "性能"),
        "comparison": ("对比", "消融", "分析", "讨论", "部署", "实现"),
    },
    "empirical_economics": {
        "theory": ("理论", "机制", "假设", "文献"),
        "design": ("数据", "样本", "变量", "模型", "研究设计"),
        "empirical": ("实证", "回归", "稳健", "异质", "结果", "检验"),
        "conclusion": ("结论", "政策", "建议", "展望"),
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


def extract_title_entities(title: str) -> list[str]:
    """Extract stable, overlapping title entities from Chinese and Latin titles."""
    compact = _norm(title)
    entities: list[str] = []
    for term in CHINESE_ENTITY_LEXICON:
        if term in compact and term not in entities:
            entities.append(term)

    # Preserve meaningful Latin/number words for bilingual or technical titles.
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+._-]{1,}|\d+(?:\.\d+)?", title or ""):
        normalized = token.lower()
        if normalized not in entities:
            entities.append(normalized)

    # A conservative connector split offers usable fallback entities for domain
    # titles not yet present in the small lexicon.  Segments must be 2-12 CJK
    # chars, preventing an entire continuous Chinese title from becoming one token.
    for part in re.split(r"(?:基于|关于|下|对|的|与|及|和|研究|分析|实现|优化|影响|机制|效应)", compact):
        if re.fullmatch(r"[\u4e00-\u9fff]{2,12}", part or "") and part not in entities:
            entities.append(part)
    return entities


def classify_research(paper_info: dict[str, Any]) -> str:
    text = _norm(" ".join([
        str(paper_info.get("title") or ""),
        str(paper_info.get("abstract") or ""),
        " ".join(str(item) for item in (paper_info.get("keywords") or [])),
        str(paper_info.get("special_requirements") or ""),
    ]))
    # Economics needs precedence: titles may contain “优化” yet are still causal
    # or distributional empirical studies rather than technical papers.
    if any(term in text for term in EMPIRICAL_ECONOMICS_TERMS) and any(
        term in text for term in ("影响", "机制", "效应", "回归", "实证", "差距", "分配")
    ):
        return "empirical_economics"
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
        "empirical_economics": ["理论机制或研究假设", "数据、变量与模型设定", "实证结果、稳健性或异质性检验", "结论、政策建议或研究局限"],
        "empirical": ["理论机制或研究假设", "数据、变量或研究设计", "实证结果或稳健性分析"],
        "review": ["研究主题范围", "比较、演进或研究述评", "研究不足与未来方向"],
        "general": ["研究背景或问题", "核心分析或研究方法", "结论、总结或展望"],
    }
    return labels.get(research_type, labels["general"])


def _section_text(section: dict[str, Any]) -> str:
    return " ".join([
        str(section.get("title") or ""),
        str(section.get("gist") or ""),
        str(section.get("purpose") or ""),
    ])


def _first_chapter_role_conflict(sections: list[dict[str, Any]], research_type: str) -> list[str]:
    """Detect empirical chapter-one scope creep before body generation begins."""
    if research_type not in {"empirical", "empirical_economics"}:
        return []
    first_chapter = [item for item in sections if str(item.get("id") or "") == "1" or str(item.get("id") or "").startswith("1-")]
    text = _norm(" ".join(_section_text(item) for item in first_chapter))
    role_keywords = {
        "benchmark_regression": ("基准回归", "回归结果", "实证结果"),
        "robustness": ("稳健性", "稳健检验"),
        "heterogeneity": ("异质性", "分组回归"),
        "conclusion": ("研究结论", "政策建议", "结论与展望"),
    }
    hits = [label for label, terms in role_keywords.items() if any(_norm(term) in text for term in terms)]
    return hits if len(hits) >= 2 else []


def _score(structure_score: float, entity_coverage: float, paradigm_score: float,
           role_score: float, specificity_score: float, source: str) -> int:
    if source != "ai":
        return 0
    return int(round(
        structure_score * 0.25
        + entity_coverage * 100 * 0.35
        + paradigm_score * 0.20
        + role_score * 0.10
        + specificity_score * 0.10
    ))


def evaluate_outline(
    paper_info: dict[str, Any],
    sections: list[dict[str, Any]],
    *, source: str,
    fallback_reason: str | None = None,
    version: int = 1,
) -> dict[str, Any]:
    """Return explainable diagnostics plus a hard ``is_generation_ready`` decision."""
    research_type = classify_research(paper_info)
    titles = [str(item.get("title") or "") for item in sections]
    joined = _norm(" ".join(_section_text(item) for item in sections))
    top_sections = [item for item in sections if int(item.get("level") or 1) == 1]
    groups = REQUIRED_GROUPS[research_type]
    coverage: dict[str, bool] = {
        key: any(_norm(term) in joined for term in terms)
        for key, terms in groups.items()
    }

    title_entities = extract_title_entities(str(paper_info.get("title") or ""))
    matched_entities = [entity for entity in title_entities if _norm(entity) in joined]
    entity_coverage = round(len(matched_entities) / len(title_entities), 2) if title_entities else 0.0
    generic_count = sum(1 for title in titles if title.strip() in GENERIC_TITLES)
    generic_ratio = round(generic_count / max(len(top_sections), 1), 2)
    role_conflicts = _first_chapter_role_conflict(sections, research_type)
    role_coverage = sum(coverage.values()) / max(len(coverage), 1)

    # A quality score supports review, but the hard gate below is authoritative.
    structure_score = 100.0 if len(top_sections) >= 3 else round(len(top_sections) / 3 * 100, 2)
    paradigm_score = 100.0 if research_type != "general" or not title_entities else 30.0
    role_score = role_coverage * 100
    specificity_score = max(0.0, (1 - generic_ratio) * 100)
    score = _score(structure_score, entity_coverage, paradigm_score, role_score, specificity_score, source)

    issues: list[str] = []
    block_reasons: list[str] = []
    missing = [required_elements(research_type)[index] for index, ok in enumerate(coverage.values()) if not ok]
    if source != "ai":
        issues.append("当前目录来自通用回退模板，仅用于预览，不代表模型已按题目定制。")
        block_reasons.append("AI 大纲生成失败，当前仅显示通用模板预览。")
    if len(top_sections) < 3:
        issues.append("一级章节数量不足 3 个。")
        block_reasons.append("大纲结构不完整，至少需要 3 个一级章节。")
    if not title_entities:
        issues.append("未能从题目识别可核验的研究实体。")
        block_reasons.append("题目实体无法识别，请检查论文标题。")
    elif entity_coverage < 0.30:
        issues.append(f"题目实体覆盖仅为 {round(entity_coverage * 100)}%，低于 30% 门槛。")
        block_reasons.append("题目实体覆盖不足，不能启动全文生成。")
    if research_type == "general" and title_entities:
        issues.append("题目包含可识别专业实体，但研究范式仍为 general。")
        block_reasons.append("研究范式未能匹配题目领域，不能启动全文生成。")
    if missing:
        issues.append("缺少关键结构：" + "、".join(missing) + "。")
        block_reasons.append("大纲未覆盖必要的研究结构。")
    if generic_ratio >= 0.6:
        issues.append("目录中的通用章节比例较高，缺少题目定制性。")
        block_reasons.append("通用章节比例过高，不能启动全文生成。")
    if role_conflicts:
        issues.append("第一章混入完整的 " + "、".join(role_conflicts) + " 职责。")
        block_reasons.append("第一章与实证分析/结论章节职责冲突。")
    if not paper_info.get("references"):
        issues.append("未传入已确认参考文献，大纲的文献综述与研究边界较弱。")

    recommendations: list[str] = []
    if source != "ai":
        recommendations.append("请重新生成定制 AI 大纲；通用模板不能进入全文生成。")
    if research_type == "technical":
        recommendations.append("技术论文应明确方法设计、实验设置、性能对比/消融与部署验证。")
    elif research_type == "empirical_economics":
        recommendations.append("实证经济学论文应依次呈现理论机制、数据与模型、实证检验及结论政策建议。")
    elif research_type == "empirical":
        recommendations.append("实证研究应明确理论机制、数据变量、模型设定与结果检验。")
    elif research_type == "review":
        recommendations.append("综述论文应按主题、演进或争议组织，而非套用实证研究结构。")
    if not paper_info.get("references"):
        recommendations.append("返回参考文献步骤至少选择一条文献，再重新生成大纲。")

    is_generation_ready = not block_reasons
    outline_quality = "pass" if is_generation_ready else "blocked"
    return {
        "version": version,
        "source": source,
        "fallback_reason": fallback_reason,
        "research_type": research_type,  # compatibility for existing clients
        "research_paradigm": research_type,
        "required_elements": required_elements(research_type),
        "coverage": coverage,
        "title_entities": title_entities,
        "matched_entities": matched_entities,
        "entity_coverage": entity_coverage,
        "template_risk": "high" if source != "ai" or generic_ratio >= 0.6 else "low",
        "generic_ratio": generic_ratio,
        "role_conflicts": role_conflicts,
        "score_components": {
            "structure_score": structure_score,
            "entity_coverage_score": round(entity_coverage * 100, 2),
            "paradigm_match_score": paradigm_score,
            "section_role_score": round(role_score, 2),
            "specificity_score": round(specificity_score, 2),
        },
        "score": score,
        "issues": issues,
        "block_reasons": block_reasons,
        "recommendations": recommendations,
        "outline_quality": outline_quality,
        "generation_status": "ready" if is_generation_ready else ("outline_generation_failed" if source != "ai" else "outline_quality_blocked"),
        "is_generation_ready": is_generation_ready,
        "confirmation_required": True,
        "confirmed": False,
        "confirmed_at": None,
        "created_at": _now(),
    }
