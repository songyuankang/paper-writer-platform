"""确定性文献相关性评分，用于 Literature → LiteratureReviewTable。

本模块不调用模型，不以 task-level 文献列表的顺序代替相关性。每条入选文献都保留
可解释的字段命中、来源质量和证据完整性评分，供候选表、前端和审计使用。
"""
from __future__ import annotations

import re
from typing import Any


ECONOMIC_EMPIRICAL_TERMS = (
    "共同富裕", "第三次分配", "居民收入", "收入差距", "收入分配", "慈善", "公益",
    "基尼", "泰尔", "调节效应", "实证", "区域异质性",
)
GENERIC_TOPIC_TERMS = (
    "智能传感", "传感器", "网络安全", "异常检测", "目标检测", "边缘计算", "深度学习",
)
TERM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "共同富裕": ("common prosperity",),
    "第三次分配": ("third distribution",),
    "居民收入": ("household income", "resident income"),
    "收入差距": ("income inequality", "income gap", "income disparity"),
    "收入分配": ("income distribution",),
    "慈善": ("charity", "philanthropy"),
    "公益": ("public welfare", "charity", "philanthropy"),
    "基尼": ("gini",),
    "泰尔": ("theil",),
    "调节效应": ("moderating effect", "moderation effect"),
    "实证": ("empirical",),
    "区域异质性": ("regional heterogeneity",),
    "智能传感": ("sensor", "sensing"),
    "传感器": ("sensor",),
    "网络安全": ("network security", "cybersecurity"),
    "异常检测": ("anomaly detection",),
    "目标检测": ("object detection",),
    "边缘计算": ("edge computing",),
    "深度学习": ("deep learning",),
}
IRRELEVANT_TERMS = ("数字工程", "花岗岩", "多民族文字识别", "休闲农业", "旅游")
TRUSTED_SOURCES = {"crossref", "openalex", "pubmed"}
MINIMUM_RELEVANCE = 25
MINIMUM_SOURCE_QUALITY = 4
MINIMUM_EVIDENCE_COMPLETENESS = 4


def _clean(value: object, limit: int = 12000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _norm(value: object) -> str:
    return _clean(value).lower()


def _matches(text: str, canonical_terms: list[str]) -> list[str]:
    lowered = _norm(text)
    hits: list[str] = []
    for term in canonical_terms:
        variants = (term, *TERM_SYNONYMS.get(term, ()))
        if any(_norm(value) in lowered for value in variants):
            hits.append(term)
    return hits


def _context(draft: dict[str, Any], chapter_purpose: str = "") -> dict[str, Any]:
    meta = draft.get("meta") or {}
    title = _clean(draft.get("title"), 800)
    keywords = [str(value) for value in (draft.get("keywords") or {}).get("zh", [])]
    if not keywords:
        keywords = [str(value) for value in meta.get("keywords") or []]
    research_question = _clean(meta.get("research_question") or meta.get("special_requirements"), 1600)
    scope = " ".join([title, *keywords, research_question, _clean(chapter_purpose, 800)])
    known = [term for term in (*ECONOMIC_EMPIRICAL_TERMS, *GENERIC_TOPIC_TERMS) if _norm(term) in _norm(scope)]
    # 经济学实证题目一旦明确出现共同富裕、第三次分配、收入差距/收入分配中的两个
    # 核心信号，即激活完整概念簇，避免“慈善、基尼、泰尔、区域异质性”等合理相邻概念
    # 因未逐字写入题目而被错误排除。
    economic_seeds = ("共同富裕", "第三次分配", "居民收入", "收入差距", "收入分配")
    if sum(_norm(term) in _norm(scope) for term in economic_seeds) >= 2:
        known.extend(ECONOMIC_EMPIRICAL_TERMS)
    known = list(dict.fromkeys(known))
    # 当题目词典尚未覆盖新的专业术语时，至少保留用户关键词中的有效术语。
    for value in keywords:
        item = _clean(value, 80)
        if len(item) >= 2 and item not in known:
            known.append(item)
    return {
        "task_title": title,
        "task_entities": list(dict.fromkeys(known)),
        "research_question": research_question,
        "chapter_purpose": _clean(chapter_purpose, 800),
    }


def _source_quality(item: dict[str, Any]) -> tuple[int, list[str]]:
    source = str(item.get("source") or "manual").lower()
    reasons: list[str] = []
    score = 0
    if source in TRUSTED_SOURCES:
        score += 8
        reasons.append(f"公开学术元数据来源：{source}")
    elif source == "manual":
        score += 3
        reasons.append("用户维护来源，需保留元数据核验")
    if item.get("doi") or item.get("url") or item.get("external_id"):
        score += 4
        reasons.append("具备可追溯标识")
    if item.get("authors") and item.get("year") and item.get("title"):
        score += 3
        reasons.append("作者、年份和标题齐全")
    return min(score, 15), reasons


def _evidence_completeness(item: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if evidence:
        score += 10
        reasons.append(f"已保存 {len(evidence)} 条可追溯 Evidence")
    abstract = _clean(item.get("abstract"), 12000)
    keywords = item.get("keywords") or []
    if abstract:
        score += 4
        reasons.append("具有摘要证据")
    if keywords:
        score += 2
        reasons.append("具有主题关键词")
    if item.get("user_note"):
        score += 1
        reasons.append("具有用户核验备注")
    return min(score, 15), reasons


def assess_literature(
    item: dict[str, Any],
    *,
    draft: dict[str, Any],
    evidence: list[dict[str, Any]],
    chapter_purpose: str = "",
) -> dict[str, Any]:
    """返回单条文献的评分、命中详情和决定；不会修改文献本身。"""
    context = _context(draft, chapter_purpose)
    terms = context["task_entities"]
    title_hits = _matches(str(item.get("title") or ""), terms)
    abstract_hits = _matches(str(item.get("abstract") or ""), terms)
    keyword_text = " ".join(str(value) for value in item.get("keywords") or [])
    keyword_hits = _matches(keyword_text, terms)
    purpose_hits = _matches(" ".join([context["research_question"], context["chapter_purpose"]]), terms)
    irrelevant_hits = [term for term in IRRELEVANT_TERMS if _norm(term) in _norm(" ".join([item.get("title") or "", item.get("abstract") or "", keyword_text]))]

    relevance = min(35, len(title_hits) * 25) + min(25, len(abstract_hits) * 8) + min(12, len(keyword_hits) * 6)
    # 章节目的/研究问题只在其实体也被文献实际命中时加分，不能凭空抬分。
    common_context_hits = set(purpose_hits).intersection(set(title_hits) | set(abstract_hits) | set(keyword_hits))
    relevance += min(10, len(common_context_hits) * 5)
    source_quality, source_reasons = _source_quality(item)
    evidence_score, evidence_reasons = _evidence_completeness(item, evidence)
    total = min(100, relevance + source_quality + evidence_score)
    all_hits = list(dict.fromkeys([*title_hits, *abstract_hits, *keyword_hits]))
    rejection_reasons: list[str] = []
    if irrelevant_hits and not all_hits:
        rejection_reasons.append("命中与论文主题无关的领域词：" + "、".join(irrelevant_hits))
    if not all_hits:
        rejection_reasons.append("标题、摘要和关键词均未命中任务主题实体")
    if relevance < MINIMUM_RELEVANCE:
        rejection_reasons.append(f"主题相关性不足（{relevance}/{MINIMUM_RELEVANCE}）")
    if source_quality < MINIMUM_SOURCE_QUALITY:
        rejection_reasons.append(f"来源质量不足（{source_quality}/{MINIMUM_SOURCE_QUALITY}）")
    if evidence_score < MINIMUM_EVIDENCE_COMPLETENESS:
        rejection_reasons.append(f"证据完整性不足（{evidence_score}/{MINIMUM_EVIDENCE_COMPLETENESS}）")
    return {
        "literature_id": str(item.get("id") or ""),
        "accepted": not rejection_reasons,
        "total_score": total,
        "relevance_score": relevance,
        "source_quality_score": source_quality,
        "evidence_completeness_score": evidence_score,
        "matched_entities": all_hits,
        "field_matches": {
            "title": title_hits,
            "abstract": abstract_hits,
            "keywords": keyword_hits,
            "research_question_or_chapter": sorted(common_context_hits),
        },
        "context": context,
        "source_reasons": source_reasons,
        "evidence_reasons": evidence_reasons,
        "rejection_reasons": rejection_reasons,
    }


def rank_literature(
    records: list[dict[str, Any]],
    *,
    draft: dict[str, Any],
    evidence_by_literature: dict[str, list[dict[str, Any]]],
    chapter_purpose: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """评分所有候选，返回入选和被排除文献的可审计摘要。"""
    assessed = [{"record": item, "assessment": assess_literature(item, draft=draft, evidence=evidence_by_literature.get(str(item.get("id") or ""), []), chapter_purpose=chapter_purpose)} for item in records]
    assessed.sort(key=lambda value: (-int(value["assessment"]["total_score"]), str(value["record"].get("year") or ""), str(value["record"].get("title") or "")))
    accepted = [value for value in assessed if value["assessment"]["accepted"]][:max(1, limit)]
    rejected = [value for value in assessed if not value["assessment"]["accepted"]]
    return {
        "context": _context(draft, chapter_purpose),
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "candidate_count": len(assessed),
        "minimum_required": 2,
        "sufficient": len(accepted) >= 2,
    }
