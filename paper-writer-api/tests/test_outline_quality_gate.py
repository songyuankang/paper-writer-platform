import json
from unittest import mock

import pytest

from app.draft.outline import (
    _extract_json,
    _normalize_outline_payload,
    build_outline_with_meta,
)
from app.draft.outline_quality import (
    classify_research,
    evaluate_outline,
    extract_title_entities,
)
from app.draft.service import DraftService


EMPIRICAL_TITLE = "共同富裕目标下第三次分配对居民收入差距的调节效应研究"


def paper_info() -> dict:
    return {
        "title": EMPIRICAL_TITLE,
        "major": "经济学",
        "paper_type": "毕业论文",
        "word_count": 8000,
        "abstract": "考察第三次分配在共同富裕目标下对居民收入差距的调节效应。",
        "keywords": ["共同富裕", "第三次分配", "收入差距", "调节效应"],
        "special_requirements": "开展计量实证、稳健性与异质性分析。",
        "references": ["共同富裕与收入分配研究"],
    }


def valid_outline(alias: str = "sections") -> str:
    payload = {
        "title": EMPIRICAL_TITLE,
        "research_paradigm": "empirical_economics",
        alias: [
            {"title": "共同富裕与第三次分配问题提出", "level": 1, "purpose": "说明共同富裕、第三次分配与居民收入差距的研究背景", "children": []},
            {"title": "第三次分配调节收入差距的理论机制与研究假设", "level": 1, "purpose": "构建慈善公益与收入分配的调节效应理论机制", "children": []},
            {"title": "居民收入数据、变量设计与计量模型", "level": 1, "purpose": "说明样本、变量、泰尔指数和计量模型设定", "children": []},
            {"title": "第三次分配调节效应的实证检验", "level": 1, "purpose": "开展基准回归、稳健性与区域异质性检验", "children": []},
            {"title": "研究结论、政策建议与局限", "level": 1, "purpose": "总结收入差距调节效应并提出共同富裕政策建议", "children": []},
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize("alias", ["sections", "outline", "chapters"])
def test_outline_aliases_normalize_to_sections(alias: str):
    payload, error = _extract_json(valid_outline(alias))
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {})
    assert error is None
    assert canonical is not None
    assert canonical["normalized_from"] == alias
    assert canonical["sections"][0]["title"].startswith("共同富裕")


def test_markdown_fenced_json_is_extracted_and_normalized():
    payload, error = _extract_json(f"```json\n{valid_outline()}\n```")
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {})
    assert error is None
    assert canonical is not None
    assert len(canonical["sections"]) == 5


def test_malformed_first_response_retries_once_then_succeeds():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat",
        side_effect=['{"title":"bad","items":[]}', valid_outline("chapters")],
    ) as chat:
        sections, meta = build_outline_with_meta(paper_info())

    assert sections
    assert meta["source"] == "ai"
    assert meta["generation_attempts"] == 2
    assert meta["is_generation_ready"] is True
    assert chat.call_count == 2
    assert chat.call_args_list[0].kwargs["response_format"]["type"] == "json_schema"
    assert chat.call_args_list[0].kwargs["response_format"]["json_schema"]["strict"] is True


def test_retry_failure_keeps_only_blocked_fallback_preview():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat",
        side_effect=["not json", '{"outline": []}'],
    ):
        sections, meta = build_outline_with_meta(paper_info())

    assert sections
    assert meta["source"] == "fallback"
    assert meta["generation_attempts"] == 2
    assert meta["generation_status"] == "outline_generation_failed"
    assert meta["outline_quality"] == "blocked"
    assert meta["is_generation_ready"] is False
    assert meta["score"] == 0


def test_chinese_entities_and_empirical_economics_paradigm_are_detected():
    entities = extract_title_entities(EMPIRICAL_TITLE)
    assert {"共同富裕", "第三次分配", "居民收入", "收入差距", "调节效应"}.issubset(entities)
    assert classify_research(paper_info()) == "empirical_economics"


def test_valid_empirical_economics_outline_passes_hard_gate():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat", return_value=valid_outline()
    ):
        _, meta = build_outline_with_meta(paper_info())

    assert meta["research_paradigm"] == "empirical_economics"
    assert meta["entity_coverage"] > 0.30
    assert meta["outline_quality"] == "pass"
    assert meta["is_generation_ready"] is True
    assert meta["score"] > 0


def test_first_chapter_empirical_role_conflict_blocks_generation():
    sections = [
        {"id": "1", "level": 1, "title": "绪论", "gist": ""},
        {"id": "1-1", "level": 2, "title": "基准回归与稳健性检验", "gist": "给出完整实证结果"},
        {"id": "1-2", "level": 2, "title": "异质性分析与研究结论", "gist": "提出政策建议"},
        {"id": "2", "level": 1, "title": "第三次分配理论机制", "gist": ""},
        {"id": "3", "level": 1, "title": "数据变量与计量模型", "gist": ""},
        {"id": "4", "level": 1, "title": "实证检验", "gist": ""},
        {"id": "5", "level": 1, "title": "结论与政策建议", "gist": ""},
    ]
    meta = evaluate_outline(paper_info(), sections, source="ai")
    assert meta["role_conflicts"]
    assert meta["is_generation_ready"] is False
    assert meta["outline_quality"] == "blocked"


def test_fallback_cannot_confirm_or_start_full_generation(tmp_path):
    service = DraftService("blocked-fallback", tmp_path)
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=False):
        draft = service.build(paper_info(), require_confirmation=True)

    assert draft["outline_meta"]["is_generation_ready"] is False
    with pytest.raises(ValueError, match="不能确认"):
        service.confirm_outline()
    with pytest.raises(ValueError, match="质量未通过"):
        service.oneclick()
