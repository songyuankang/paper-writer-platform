from __future__ import annotations

import json

import pytest

from app.draft import outline
from app.draft.outline_entities import entity_coverage_details, extract_title_entities, topic_fallback_titles
from app.draft.outline_quality import evaluate_outline
from app.services import deepseek


EDGE_TITLE = "基于边缘计算的轻量化目标检测算法优化与实现"
SECURITY_TITLE = "基于深度学习的校园网络安全异常检测系统设计与实现"
PAPER = {
    "title": EDGE_TITLE,
    "major": "计算机科学与技术",
    "paper_type": "毕业论文",
    "word_count": 12000,
    "keywords": ["边缘计算", "轻量化", "目标检测"],
    "references": ["[1] 边缘智能目标检测研究"],
}


def valid_payload() -> dict:
    return {
        "sections": [{
            "title": "绪论", "level": 1, "children": [{
                "title": "研究背景", "level": 2, "children": [{
                    "title": "研究问题", "level": 3, "gist": "说明边缘端目标检测的性能约束。", "children": [],
                }],
            }],
        }],
    }


def content(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_normalize_valid_sections_and_three_levels():
    normalized, alias, error = outline.normalize_outline_payload(valid_payload())
    assert error is None
    assert alias == "sections"
    assert normalized["sections"][0]["children"][0]["children"][0]["level"] == 3


@pytest.mark.parametrize("alias", ["outline", "chapters"])
def test_normalize_explicit_object_array_alias_to_sections(alias: str):
    payload = valid_payload()
    raw = payload.pop("sections")
    payload[alias] = raw
    normalized, applied, error = outline.normalize_outline_payload(payload)
    assert error is None
    assert applied == alias
    assert normalized["sections"] == raw


@pytest.mark.parametrize("payload, expected", [
    ({"outline": "第一章 绪论"}, "outline 必须为非空章节对象数组"),
    ({"sections": [{"level": 1, "children": []}]}, "章节节点缺少非空 title"),
    ({"sections": [{"title": "绪论", "level": 4, "children": []}]}, "章节节点 level 必须为 1~3 整数"),
    ({"sections": [{"title": "绪论", "level": 1, "children": [{"title": "节", "level": 2, "children": [{"title": "小节", "level": 3, "children": [{"title": "四级", "level": 4, "children": []}]}]}]}]}, "章节层级最多三级"),
])
def test_normalize_rejects_unsafe_or_invalid_trees(payload: dict, expected: str):
    normalized, _, error = outline.normalize_outline_payload(payload)
    assert normalized is None
    assert expected in error


def test_leaf_node_may_safely_omit_children_when_gist_present():
    payload = {"sections": [{"title": "绪论", "level": 1, "gist": "说明研究背景"}]}
    normalized, _, error = outline.normalize_outline_payload(payload)
    assert error is None
    assert normalized["sections"][0]["children"] == []


def test_first_outline_alias_is_normalized_without_fallback(monkeypatch):
    alias_payload = valid_payload()
    alias_payload["outline"] = alias_payload.pop("sections")
    calls: list[bool] = []

    def fake_chat_json(*_args, **kwargs):
        calls.append(True)
        return content(alias_payload), False

    monkeypatch.setattr(outline.deepseek, "is_enabled", lambda: True)
    monkeypatch.setattr(outline.deepseek, "chat_json", fake_chat_json)
    flat, meta = outline.build_outline_with_meta(PAPER)
    assert len(calls) == 1
    assert flat and meta["source"] == "ai"
    assert meta["normalization_applied"] == "outline"
    assert meta["attempt_count"] == 1


def test_missing_sections_retries_once_then_succeeds(monkeypatch):
    responses = iter([content({"outline": "无效文本"}), content(valid_payload())])
    prompts: list[list[dict]] = []

    def fake_chat_json(messages, **_kwargs):
        prompts.append(messages)
        return next(responses), True

    monkeypatch.setattr(outline.deepseek, "is_enabled", lambda: True)
    monkeypatch.setattr(outline.deepseek, "chat_json", fake_chat_json)
    flat, meta = outline.build_outline_with_meta(PAPER)
    assert flat and meta["source"] == "ai"
    assert meta["attempt_count"] == 2
    assert "outline 必须为非空章节对象数组" in meta["first_failure_reason"]
    assert meta["second_failure_reason"] is None
    assert meta["structured_output_used"] is True
    assert "顶层必须包含 sections" in prompts[1][-1]["content"]


def test_invalid_json_twice_uses_topic_fallback_and_records_failures(monkeypatch):
    monkeypatch.setattr(outline.deepseek, "is_enabled", lambda: True)
    monkeypatch.setattr(outline.deepseek, "chat_json", lambda *_args, **_kwargs: ("not json", False))
    flat, meta = outline.build_outline_with_meta(PAPER)
    titles = [item["title"] for item in flat if item["level"] == 1]
    assert meta["source"] == "fallback"
    assert meta["fallback_kind"] == "topic"
    assert meta["attempt_count"] == 2
    assert meta["first_failure_reason"] and meta["second_failure_reason"]
    assert titles == [
        "绪论", "边缘计算与目标检测相关理论", "轻量化目标检测算法设计与优化",
        "系统实现与边缘端部署", "实验设计与性能验证", "基线对比与消融分析", "总结与展望",
    ]


@pytest.mark.parametrize("title, research_type", [
    (SECURITY_TITLE, "technical"),
    ("数字金融发展对绿色创新的影响研究", "empirical"),
    ("人工智能教育应用研究进展综述", "review"),
])
def test_topic_fallback_handles_technical_engineering_and_empirical_titles(title: str, research_type: str):
    titles = topic_fallback_titles(title, research_type)
    assert titles is not None
    assert len(titles) >= 5
    assert any(title_part in " ".join(titles) for title_part in extract_title_entities(title)[:2])


def test_chinese_entities_and_synonyms_have_explainable_coverage():
    entities = extract_title_entities(EDGE_TITLE)
    assert {"边缘计算", "轻量化", "目标检测", "算法", "优化", "实现"}.issubset(set(entities))
    sections = [
        {"number": "第二章", "title": "边缘端视觉检测理论", "gist": ""},
        {"number": "第三章", "title": "模型压缩与检测算法改进", "gist": ""},
        {"number": "第四章", "title": "工程实现与性能优化", "gist": ""},
    ]
    matches = entity_coverage_details(EDGE_TITLE, sections)
    by_entity = {item["entity"]: item for item in matches}
    assert "边缘端" in by_entity["边缘计算"]["matched_terms"]
    assert "模型压缩" in by_entity["轻量化"]["matched_terms"]
    assert "检测算法" in by_entity["目标检测"]["matched_terms"]
    assert by_entity["实现"]["matched_sections"]


def test_zero_entity_coverage_is_capped_below_misleading_quality_score():
    flat = [
        {"id": "1", "number": "第一章", "level": 1, "title": "方法研究", "gist": ""},
        {"id": "2", "number": "第二章", "level": 1, "title": "实验验证", "gist": ""},
        {"id": "3", "number": "第三章", "level": 1, "title": "对比分析", "gist": ""},
    ]
    meta = evaluate_outline({**PAPER, "title": "基于边缘计算的轻量化目标检测"}, flat, source="ai")
    assert meta["entity_coverage"] == 0
    assert meta["score"] <= 55
    assert meta["score_breakdown"]["entity"] == 0


def test_structured_output_is_forwarded_to_provider_payload(monkeypatch):
    captured: dict = {}

    def fake_post(_base_url, _api_key, payload, _timeout):
        captured.update(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(deepseek, "_post", fake_post)
    result = deepseek.chat_with(
        "https://example.invalid/v1", "key", "model", [{"role": "user", "content": "x"}],
        response_format={"type": "json_schema"}, retries=0,
    )
    assert result == "{}"
    assert captured["response_format"] == {"type": "json_schema"}


def test_structured_output_unsupported_safely_downgrades(monkeypatch):
    calls: list[dict | None] = []

    def fake_chat(_messages, *, max_tokens=None, response_format=None):
        calls.append(response_format)
        if response_format is not None:
            raise deepseek.DeepSeekModelError("response_format is not supported")
        return "{}"

    monkeypatch.setattr(deepseek, "chat", fake_chat)
    payload, used = deepseek.chat_json([{"role": "user", "content": "x"}], response_format={"type": "json_schema"})
    assert payload == "{}"
    assert used is False
    assert calls == [{"type": "json_schema"}, None]


def test_real_title_e2e_second_attempt_sections_is_ai_customized(monkeypatch):
    customized_payload = valid_payload()
    customized_payload["sections"][0]["title"] = "深度学习网络安全异常检测研究"
    customized_payload["sections"][0]["children"][0]["title"] = "校园网络异常检测系统设计"
    customized_payload["sections"][0]["children"][0]["children"][0]["title"] = "系统实现与实验性能验证"
    responses = iter([
        content({"chapters": "not an object array"}),
        content(customized_payload),
    ])
    monkeypatch.setattr(outline.deepseek, "is_enabled", lambda: True)
    monkeypatch.setattr(outline.deepseek, "chat_json", lambda *_args, **_kwargs: (next(responses), True))
    flat, meta = outline.build_outline_with_meta({**PAPER, "title": SECURITY_TITLE})
    assert flat
    assert meta["source"] == "ai"
    assert meta["attempt_count"] == 2
    assert meta["entity_coverage"] > 0


def test_empirical_first_chapter_role_conflict_is_low_score_and_retried(monkeypatch):
    paper = {
        **PAPER,
        "title": "共同富裕目标下第三次分配对居民收入差距的调节效应研究",
        "keywords": ["共同富裕", "第三次分配", "收入差距"],
    }
    bad = {
        "sections": [
            {"title": "绪论", "level": 1, "children": [
                {"title": "研究背景", "level": 2, "children": []},
                {"title": "研究假设", "level": 2, "children": []},
                {"title": "实证结果分析", "level": 2, "children": []},
                {"title": "结论与政策建议", "level": 2, "children": []},
            ]},
            {"title": "理论机制", "level": 1, "children": []},
            {"title": "研究设计", "level": 1, "children": []},
            {"title": "实证检验", "level": 1, "children": []},
        ],
    }
    good = {
        "sections": [
            {"title": "绪论", "level": 1, "children": [{"title": "研究背景与研究意义", "level": 2, "children": []}]},
            {"title": "理论机制与研究假设", "level": 1, "children": []},
            {"title": "研究设计与变量说明", "level": 1, "children": []},
            {"title": "实证结果与稳健性检验", "level": 1, "children": []},
            {"title": "结论与政策建议", "level": 1, "children": []},
        ],
    }
    responses = iter([content(bad), content(good)])
    monkeypatch.setattr(outline.deepseek, "is_enabled", lambda: True)
    monkeypatch.setattr(outline.deepseek, "chat_json", lambda *_args, **_kwargs: (next(responses), True))
    flat, meta = outline.build_outline_with_meta(paper)
    assert meta["research_type"] == "empirical"
    assert meta["attempt_count"] == 2
    assert "第一章职责冲突" in meta["first_failure_reason"]
    assert meta["chapter_role_conflicts"] == []
    assert all(not (item["id"].startswith("1-") and item["title"] == "实证结果分析") for item in flat)


def test_empirical_role_conflict_caps_quality_score():
    sections = [
        {"id": "1", "number": "第一章", "level": 1, "title": "绪论", "gist": ""},
        {"id": "1-1", "number": "1.1", "level": 2, "title": "研究假设", "gist": ""},
        {"id": "1-2", "number": "1.2", "level": 2, "title": "实证结果", "gist": ""},
        {"id": "2", "number": "第二章", "level": 1, "title": "理论机制", "gist": ""},
        {"id": "3", "number": "第三章", "level": 1, "title": "研究设计", "gist": ""},
        {"id": "4", "number": "第四章", "level": 1, "title": "结论与政策建议", "gist": ""},
    ]
    meta = evaluate_outline({**PAPER, "title": "共同富裕与第三次分配的收入差距实证研究"}, sections, source="ai")
    assert meta["research_type"] == "empirical"
    assert meta["chapter_role_conflicts"]
    assert meta["score"] <= 45
