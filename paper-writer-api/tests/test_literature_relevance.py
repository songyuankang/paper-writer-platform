from __future__ import annotations

from app.services.literature_relevance_service import rank_literature


DRAFT = {
    "title": "共同富裕目标下第三次分配对居民收入差距的调节效应研究",
    "meta": {
        "keywords": ["共同富裕", "第三次分配", "收入差距"],
        "research_question": "第三次分配是否通过慈善公益缩小居民收入差距，并存在区域异质性？",
    },
    "keywords": {"zh": ["共同富裕", "第三次分配", "收入差距"], "en": []},
}


def record(literature_id: str, **changes):
    base = {
        "id": literature_id,
        "title": "共同富裕与第三次分配的收入差距调节效应",
        "authors": ["张三"], "year": 2023,
        "abstract": "本文采用省际面板实证分析第三次分配和慈善公益对居民收入差距的调节效应。",
        "keywords": ["共同富裕", "第三次分配", "收入分配"],
        "source": "crossref", "doi": "10.1000/example", "external_id": "example",
    }
    return {**base, **changes}


def test_rank_uses_all_relevance_dimensions_and_excludes_irregular_topics():
    related = record("lit_related")
    related_second = record(
        "lit_related_second", title="慈善公益、收入分配与区域异质性研究",
        abstract="基于泰尔指数和基尼系数开展区域异质性实证检验。",
        keywords=["慈善", "收入分配", "泰尔", "实证"], source="manual", doi="", external_id="related-2",
    )
    keyword_only = record(
        "lit_keyword", title="中国居民福利研究", abstract="研究社会福利与公共政策。",
        keywords=["共同富裕", "收入差距"], source="manual", doi="", external_id="keyword-1",
    )
    irrelevant = record(
        "lit_irrelevant", title="花岗岩矿化与旅游休闲农业发展", abstract="讨论花岗岩数字工程和旅游规划。",
        keywords=["花岗岩", "旅游"], source="manual", doi="", external_id="irrelevant-1",
    )
    ranked = rank_literature(
        [irrelevant, keyword_only, related_second, related], draft=DRAFT,
        evidence_by_literature={"lit_related": [{"id": "le_1", "evidence": "省际面板实证分析"}]},
        chapter_purpose="文献综述：第三次分配、慈善公益与收入差距的实证机制",
    )
    assert ranked["candidate_count"] == 4
    assert ranked["sufficient"] is True
    assert [item["record"]["id"] for item in ranked["accepted"]] == ["lit_related", "lit_related_second"]
    assessment = ranked["accepted"][0]["assessment"]
    assert assessment["field_matches"]["title"]
    assert assessment["field_matches"]["abstract"]
    assert assessment["field_matches"]["keywords"]
    assert assessment["field_matches"]["research_question_or_chapter"]
    assert assessment["source_quality_score"] >= 4
    assert assessment["evidence_completeness_score"] >= 4
    weak = next(item["assessment"] for item in ranked["rejected"] if item["record"]["id"] == "lit_keyword")
    assert weak["accepted"] is False
    assert any("主题相关性不足" in item for item in weak["rejection_reasons"])
    rejected = next(item["assessment"] for item in ranked["rejected"] if item["record"]["id"] == "lit_irrelevant")
    assert rejected["accepted"] is False
    assert "标题、摘要和关键词均未命中任务主题实体" in rejected["rejection_reasons"]


def test_rank_declares_insufficient_instead_of_padding_with_unrelated_records():
    related = record("lit_related")
    unrelated = record("lit_travel", title="休闲农业与旅游空间规划", abstract="分析旅游目的地开发。", keywords=["旅游"], source="manual", doi="", external_id="travel")
    ranked = rank_literature([related, unrelated], draft=DRAFT, evidence_by_literature={}, chapter_purpose="文献综述")
    assert ranked["accepted_count"] == 1
    assert ranked["sufficient"] is False
    assert [item["record"]["id"] for item in ranked["accepted"]] == ["lit_related"]
