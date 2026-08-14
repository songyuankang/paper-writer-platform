from app.draft.service import _apply_leaf_budgets, _body_char_count, _leaf_ids


def _sections():
    return [
        {"id": "1", "title": "引言", "paragraphs": [{"text": "不计入正文叶子统计"}]},
        {"id": "1-1", "title": "研究背景", "paragraphs": [{"text": "研究 背景"}]},
        {"id": "1-2", "title": "研究方法", "paragraphs": [{"text": "方法"}]},
        {"id": "2", "title": "结论", "paragraphs": []},
        {"id": "2-1", "title": "结论与展望", "paragraphs": [{"text": "结论\n展望"}]},
    ]


def test_body_char_count_only_counts_leaf_section_paragraphs() -> None:
    assert _body_char_count({"sections": _sections()}) == len("研究背景") + len("方法") + len("结论展望")


def test_leaf_budgets_cover_buffered_target_and_set_minimums() -> None:
    sections = _sections()
    _apply_leaf_budgets(sections, 10_000)

    leaves = [section for section in sections if section["id"] in _leaf_ids(sections)]
    assert sum(section["target_chars"] for section in leaves) == 10_200
    assert all(section["min_chars"] <= section["target_chars"] for section in leaves)
    method_budget = next(section for section in leaves if section["title"] == "研究方法")["target_chars"]
    conclusion_budget = next(section for section in leaves if section["title"] == "结论与展望")["target_chars"]
    assert method_budget > conclusion_budget
