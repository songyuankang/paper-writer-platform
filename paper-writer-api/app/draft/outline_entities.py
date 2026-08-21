"""Deterministic title-entity extraction and outline coverage helpers."""
from __future__ import annotations

import re
from typing import Any


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


# Canonical terms are intentionally concise.  Each set includes only deterministic
# terminology variants that are safe for outline-quality diagnostics.
ENTITY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "边缘计算": ("边缘计算", "边缘端", "端侧", "边缘部署", "边缘设备"),
    "云计算": ("云计算", "云端", "云平台"),
    "轻量化": ("轻量化", "轻量模型", "模型压缩", "剪枝", "量化", "蒸馏"),
    "目标检测": ("目标检测", "检测模型", "检测算法", "视觉检测"),
    "异常检测": ("异常检测", "异常识别", "入侵检测", "异常分析"),
    "网络安全": ("网络安全", "网络防护", "安全检测", "安全态势"),
    "深度学习": ("深度学习", "深度神经网络", "深度模型"),
    "人工智能": ("人工智能", "AI", "智能算法"),
    "教育": ("教育", "教学", "学习场景"),
    "机器学习": ("机器学习", "学习模型", "智能模型"),
    "物联网": ("物联网", "iot", "感知网络"),
    "计算机视觉": ("计算机视觉", "视觉感知", "视觉模型"),
    "算法": ("算法", "方法", "模型", "网络", "方案"),
    "系统": ("系统", "平台", "架构", "工程"),
    "优化": ("优化", "改进", "加速", "性能优化", "压缩"),
    "设计": ("设计", "方案设计", "架构设计", "方法设计"),
    "实现": ("实现", "系统实现", "工程实现", "部署", "落地"),
    "校园": ("校园", "教育场景", "校内"),
    "数字金融": ("数字金融", "金融科技", "普惠金融"),
    "绿色创新": ("绿色创新", "绿色技术创新", "绿色技术"),
    "碳排放": ("碳排放", "碳减排", "低碳"),
    "经济增长": ("经济增长", "经济发展", "增长效应"),
    "农业": ("农业", "农田", "农业场景"),
    "工业": ("工业", "工业场景", "制造场景"),
}


def normalize_entity(entity: str) -> tuple[str, ...]:
    """Return known synonymous terms for a canonical entity, including itself."""
    terms = ENTITY_SYNONYMS.get(entity, (entity,))
    return tuple(dict.fromkeys(term for term in terms if term))


def extract_title_entities(title: str) -> list[str]:
    """Extract ordered, deterministic, meaningful title entities without an AI call."""
    normalized = _norm(title)
    entities: list[str] = []
    for canonical, terms in ENTITY_SYNONYMS.items():
        if any(_norm(term) in normalized for term in terms):
            entities.append(canonical)
    return entities


def entity_coverage_details(title: str, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explain which title entities are covered by outline section titles or gists."""
    details: list[dict[str, Any]] = []
    for entity in extract_title_entities(title):
        matched_terms: list[str] = []
        matched_sections: list[str] = []
        for section in sections:
            text = _norm(f"{section.get('title') or ''} {section.get('gist') or ''}")
            terms = [term for term in normalize_entity(entity) if _norm(term) in text]
            if not terms:
                continue
            for term in terms:
                if term not in matched_terms:
                    matched_terms.append(term)
            label = f"{section.get('number') or section.get('id') or ''} {section.get('title') or ''}".strip()
            if label and label not in matched_sections:
                matched_sections.append(label)
        details.append({
            "entity": entity,
            "matched_terms": matched_terms,
            "matched_sections": matched_sections,
        })
    return details


def topic_fallback_titles(title: str, research_type: str) -> list[str] | None:
    """Produce a title-aware minimum fallback, or ``None`` when no entity is known."""
    entities = extract_title_entities(title)
    if not entities:
        return None
    names = set(entities)
    if {"边缘计算", "轻量化", "目标检测"}.issubset(names):
        return [
            "绪论",
            "边缘计算与目标检测相关理论",
            "轻量化目标检测算法设计与优化",
            "系统实现与边缘端部署",
            "实验设计与性能验证",
            "基线对比与消融分析",
            "总结与展望",
        ]
    subject_parts = [entity for entity in entities if entity not in {"算法", "优化", "设计", "实现", "系统"}]
    subject = "与".join(subject_parts) or "与".join(entities[:2])
    if research_type == "empirical":
        return [
            "绪论",
            f"{subject}相关理论与研究假设",
            f"{subject}研究设计与数据说明",
            f"{subject}实证模型与结果分析",
            "稳健性检验与讨论",
            "总结与展望",
        ]
    if research_type == "review":
        return [
            "绪论",
            f"{subject}研究范围与概念界定",
            f"{subject}研究进展与主题比较",
            f"{subject}研究不足与未来方向",
            "总结与展望",
        ]
    return [
        "绪论",
        f"{subject}相关理论与关键技术",
        f"{subject}方法设计与优化",
        "系统实现与部署",
        "实验设计与性能验证",
        "基线对比与结果分析",
        "总结与展望",
    ]
