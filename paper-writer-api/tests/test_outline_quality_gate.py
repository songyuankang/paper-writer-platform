import json
from unittest import mock

import pytest

from app.draft.outline import (
    _extract_json,
    _flatten,
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


def _node(title: str, purpose: str, children: list[dict] | None = None, level: int = 2) -> dict:
    return {"title": title, "level": level, "purpose": purpose, "children": children or []}


def graduation_roots(*, with_level_3: bool = False) -> list[dict]:
    """Five chapters, each with two concrete level-2 writing units."""
    empirical_children = [
        _node("基准回归结果", "检验第三次分配对居民收入差距的调节效应", level=2),
        _node("稳健性与区域异质性检验", "验证模型设定和区域差异下结论的可靠性", level=2),
    ]
    if with_level_3:
        empirical_children[0]["children"] = [
            _node("变量处理与模型设定", "说明基准回归的变量处理与识别策略", level=3),
            _node("回归结果解释", "解释核心系数的经济学含义和边界", level=3),
        ]
    return [
        {"title": "共同富裕与第三次分配问题提出", "level": 1, "purpose": "说明共同富裕、第三次分配与居民收入差距的研究背景", "children": [
            _node("研究背景与意义", "阐述共同富裕目标下收入差距治理的现实背景"),
            _node("研究内容与技术路线", "说明研究问题、研究方法与论文结构"),
        ]},
        {"title": "第三次分配调节收入差距的理论机制与研究假设", "level": 1, "purpose": "构建慈善公益与收入分配的调节效应理论机制", "children": [
            _node("收入分配与第三次分配理论", "梳理收入分配、慈善公益和共同富裕理论"),
            _node("作用机制与研究假设", "提出第三次分配调节收入差距的理论假设"),
        ]},
        {"title": "居民收入数据、变量设计与计量模型", "level": 1, "purpose": "说明样本、变量、泰尔指数和计量模型设定", "children": [
            _node("样本来源与变量说明", "说明居民收入、第三次分配与控制变量的测量"),
            _node("计量模型与识别策略", "构建调节效应的计量模型和识别方案"),
        ]},
        {"title": "第三次分配调节效应的实证检验", "level": 1, "purpose": "开展基准回归、稳健性与区域异质性检验", "children": empirical_children},
        {"title": "研究结论、政策建议与局限", "level": 1, "purpose": "总结收入差距调节效应并提出共同富裕政策建议", "children": [
            _node("研究结论与政策建议", "总结实证结论并提出共同富裕政策建议"),
            _node("研究局限与未来展望", "说明研究局限并提出未来研究方向"),
        ]},
    ]


def valid_outline(alias: str = "sections", *, with_level_3: bool = False) -> str:
    payload = {
        "title": EMPIRICAL_TITLE,
        "research_paradigm": "empirical_economics",
        alias: graduation_roots(with_level_3=with_level_3),
    }
    return json.dumps(payload, ensure_ascii=False)


def root_only_outline() -> str:
    payload = {
        "title": EMPIRICAL_TITLE,
        "research_paradigm": "empirical_economics",
        "sections": [
            {"title": title, "level": 1, "purpose": purpose, "children": []}
            for title, purpose in [
                ("共同富裕与第三次分配问题提出", "研究背景"),
                ("理论机制与研究假设", "理论机制"),
                ("数据变量与计量模型", "数据模型"),
                ("实证检验", "基准回归"),
                ("结论与政策建议", "结论建议"),
            ]
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize("alias", ["sections", "outline", "chapters"])
def test_outline_aliases_normalize_to_sections(alias: str):
    payload, error = _extract_json(valid_outline(alias))
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {}, paper_type="毕业论文")
    assert error is None
    assert canonical is not None
    assert canonical["normalized_from"] == alias
    assert canonical["sections"][0]["title"].startswith("共同富裕")
    assert len(canonical["sections"][0]["children"]) == 2


def test_markdown_fenced_json_is_extracted_and_normalized():
    payload, error = _extract_json(f"```json\n{valid_outline()}\n```")
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {}, paper_type="毕业论文")
    assert error is None
    assert canonical is not None
    assert len(canonical["sections"]) == 5


def test_root_only_graduation_outline_is_rejected_by_canonical_contract():
    payload, error = _extract_json(root_only_outline())
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {}, paper_type="毕业论文")
    assert canonical is None
    assert "至少需要 2 个二级小节" in (error or "")


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
    assert meta["level_2_count"] == 10
    assert chat.call_count == 2
    assert chat.call_args_list[0].kwargs["response_format"]["type"] == "json_schema"
    assert chat.call_args_list[0].kwargs["response_format"]["json_schema"]["strict"] is True


def test_root_only_first_response_retries_then_succeeds_with_multilevel_outline():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat",
        side_effect=[root_only_outline(), valid_outline()],
    ) as chat:
        sections, meta = build_outline_with_meta(paper_info())

    assert meta["source"] == "ai"
    assert meta["generation_attempts"] == 2
    assert meta["hierarchy_valid"] is True
    assert meta["level_1_count"] == 5
    assert meta["level_2_count"] == 10
    assert all(count >= 2 for count in meta["children_per_chapter"].values())
    assert len(sections) == 15
    retry_prompt = chat.call_args_list[1].args[0][-1]["content"]
    assert "每个一级章节必须至少包含 2 个 level=2 的 children" in retry_prompt


def test_root_only_retry_failure_keeps_only_blocked_fallback_preview():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat",
        side_effect=[root_only_outline(), root_only_outline()],
    ):
        sections, meta = build_outline_with_meta(paper_info())

    assert sections
    assert meta["source"] == "fallback"
    assert meta["generation_attempts"] == 2
    assert meta["generation_status"] == "outline_generation_failed"
    assert meta["outline_quality"] == "blocked"
    assert meta["is_generation_ready"] is False
    assert meta["score"] == 0


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


def test_two_level_graduation_outline_passes_hard_gate():
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=True), mock.patch(
        "app.draft.outline.deepseek.chat", return_value=valid_outline()
    ):
        _, meta = build_outline_with_meta(paper_info())

    assert meta["research_paradigm"] == "empirical_economics"
    assert meta["entity_coverage"] > 0.30
    assert meta["level_1_count"] == 5
    assert meta["level_2_count"] == 10
    assert meta["level_3_count"] == 0
    assert meta["leaf_count"] == 10
    assert meta["hierarchy_valid"] is True
    assert meta["outline_quality"] == "pass"
    assert meta["is_generation_ready"] is True
    assert meta["score"] > 0


def test_three_level_graduation_outline_passes_and_flattening_preserves_ids():
    payload, error = _extract_json(valid_outline(with_level_3=True))
    assert error is None
    canonical, error = _normalize_outline_payload(payload or {}, paper_type="毕业论文")
    assert error is None
    assert canonical is not None
    flat: list[dict] = []
    for index, root in enumerate(canonical["sections"]):
        _flatten(root, "", index, flat)
    ids = [section["id"] for section in flat]
    assert "1" in ids and "1-1" in ids and "1-1-1" not in ids
    # The fourth chapter carries the selected level-3 branch.
    assert "4" in ids and "4-1" in ids and "4-1-1" in ids and "4-1-2" in ids
    numbers = {section["id"]: section["number"] for section in flat}
    assert numbers["4-1-1"] == "4.1.1"
    assert numbers["4-1-2"] == "4.1.2"
    meta = evaluate_outline(paper_info(), flat, source="ai")
    assert meta["level_3_count"] == 2
    assert meta["hierarchy_valid"] is True


def test_every_root_with_empty_children_is_blocked_by_quality_gate():
    sections = [
        {"id": str(index), "level": 1, "title": f"第{index}章", "gist": "方法 实验 对比", "children": []}
        for index in range(1, 6)
    ]
    meta = evaluate_outline(paper_info(), sections, source="ai")
    assert meta["level_2_count"] == 0
    assert len(meta["chapters_without_children"]) == 5
    assert meta["hierarchy_valid"] is False
    assert meta["outline_quality"] == "blocked"
    assert "大纲层级不足，请重新生成大纲。" in meta["block_reasons"]


def test_first_chapter_empirical_role_conflict_blocks_generation():
    sections = [
        {"id": "1", "level": 1, "title": "绪论", "gist": ""},
        {"id": "1-1", "level": 2, "title": "基准回归与稳健性检验", "gist": "给出完整实证结果"},
        {"id": "1-2", "level": 2, "title": "异质性分析与研究结论", "gist": "提出政策建议"},
        {"id": "2", "level": 1, "title": "第三次分配理论机制", "gist": ""},
        {"id": "2-1", "level": 2, "title": "理论基础", "gist": ""},
        {"id": "2-2", "level": 2, "title": "研究假设", "gist": ""},
        {"id": "3", "level": 1, "title": "数据变量与计量模型", "gist": ""},
        {"id": "3-1", "level": 2, "title": "样本数据", "gist": ""},
        {"id": "3-2", "level": 2, "title": "变量设计", "gist": ""},
        {"id": "4", "level": 1, "title": "实证检验", "gist": ""},
        {"id": "4-1", "level": 2, "title": "基准模型", "gist": ""},
        {"id": "4-2", "level": 2, "title": "稳健检验", "gist": ""},
        {"id": "5", "level": 1, "title": "结论与政策建议", "gist": ""},
        {"id": "5-1", "level": 2, "title": "研究结论", "gist": ""},
        {"id": "5-2", "level": 2, "title": "政策建议", "gist": ""},
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


def test_blockchain_medical_record_platform_is_classified_as_technical():
    info = {
        "title": "基于区块链的电子病历共享平台设计与实现",
        "paper_type": "毕业论文",
        "keywords": ["区块链", "电子病历", "智能合约"],
    }
    assert classify_research(info) == "technical"
