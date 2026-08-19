from pathlib import Path

import pytest

from app.formatter.service import format_paper
from app.services import content_quality_guard


def test_export_guard_blocks_generation_failure_and_markdown(tmp_path: Path) -> None:
    spec = {
        "sections": [
            {"type": "h1", "text": "第一章"},
            {"type": "p", "text": "（生成结果为空）请检查模型配置后重新生成。"},
            {"type": "p", "text": "##"},
            {"type": "references", "items": ["有效参考文献"]},
        ],
        "references": ["有效参考文献"],
    }
    with pytest.raises(content_quality_guard.ExportQualityError):
        content_quality_guard.assert_exportable(spec, tmp_path)
    report = (tmp_path / "export_guard.json").read_text(encoding="utf-8")
    assert "generation_failure_marker" in report
    assert "markdown_leak" in report


def test_export_guard_normalizes_reference_numbers_and_source_text(tmp_path: Path) -> None:
    spec = {
        "sections": [
            {"type": "p", "text": "该结论见[1]。"},
            {"type": "p", "text": "数据来源：数据来源：公开数据。"},
            {"type": "references", "items": ["真实参考文献"]},
        ],
        "references": ["真实参考文献"],
    }
    normalized, report = content_quality_guard.prepare_spec_for_export(spec)
    assert report["blockers"] == []
    assert normalized["references"] == ["[1] 真实参考文献"]
    assert normalized["sections"][1]["text"] == "数据来源：公开数据。"


def test_format_service_blocks_bad_content_before_word_export(tmp_path: Path) -> None:
    spec = {
        "meta": {"title": "测试", "abstract": "摘要", "keywords": ["测试"]},
        "sections": [
            {"type": "h1", "text": "第一章"},
            {"type": "p", "text": "（生成结果为空）请检查模型配置后重新生成。"},
            {"type": "references", "items": []},
        ],
        "references": [],
    }
    with pytest.raises(content_quality_guard.ExportQualityError):
        format_paper("guard-test", tmp_path, {"title": "测试"}, spec, build_docx=True)
    assert (tmp_path / "export_guard.json").exists()
    assert not list(tmp_path.glob("*.docx"))


def test_export_guard_removes_unresolved_table_and_figure_references() -> None:
    spec = {
        "sections": [
            {"type": "p", "text": "如表5-1所示，模型性能得到提升；见图3-1，变化趋势趋于稳定。"},
            {"type": "references", "items": []},
        ],
        "references": [],
    }
    normalized, report = content_quality_guard.prepare_spec_for_export(spec)
    assert report["blockers"] == []
    assert any(item["code"] == "unresolved_visual_reference_removed" for item in report["warnings"])
    assert "表5-1" not in normalized["sections"][0]["text"]
    assert "图3-1" not in normalized["sections"][0]["text"]
    assert "模型性能得到提升" in normalized["sections"][0]["text"]
