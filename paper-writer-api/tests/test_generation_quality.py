from __future__ import annotations

from app.draft.generation_quality import evaluate_generated_body


def codes(text: str, *, target_chars: int | None = None) -> set[str]:
    return {item["code"] for item in evaluate_generated_body(text, target_chars=target_chars)["issues"]}


def test_accepts_normal_academic_paragraphs():
    result = evaluate_generated_body("第三次分配通过公益资源配置改善低收入群体的发展机会。\n\n该机制需要结合可靠数据进一步检验。", target_chars=500)
    assert result["valid"] is True


def test_rejects_markdown_heading_and_code_fence():
    found = codes("## 研究结论\n\n```python\nprint('debug')\n```\n正文。")
    assert {"markdown_heading", "code_fence"}.issubset(found)


def test_rejects_debug_markers_and_json_fragment():
    found = codes('analysis: 先分析问题\n{"sections": [{"title": "x"}]}')
    assert {"debug_marker", "json_fragment"}.issubset(found)


def test_rejects_repeated_heading_in_one_body():
    heading = "## 3-3.2 初次分配与再分配的协同效应检验"
    found = codes((heading + " 正文分析。") * 4)
    assert {"markdown_heading", "repeated_heading"}.issubset(found)


def test_rejects_continuous_repeated_ngram():
    phrase = "第三次分配能够有效缩小居民收入差距并促进共同富裕"
    assert "repeated_ngram" in codes(phrase * 4)


def test_rejects_abnormal_body_length_against_section_budget():
    result = evaluate_generated_body("正" * 3001, target_chars=300)
    assert "abnormal_length" in {item["code"] for item in result["issues"]}
