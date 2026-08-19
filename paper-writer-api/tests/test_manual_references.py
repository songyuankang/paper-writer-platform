import pytest
from pydantic import ValidationError

from app.api.generate import _format_manual_reference, _manual_reference_item
from app.models.generate import ManualReferenceRequest


def _journal_reference(**overrides: str) -> ManualReferenceRequest:
    payload = {
        "reference_type": "journal",
        "authors": "张敏；李华",
        "title": "新入职幼儿园教师专业成长的关键事件研究",
        "source": "学前教育研究",
        "year": "2024",
        "volume": "12",
        "issue": "3",
        "pages": "45-56",
        "doi": "10.1234/example.2024.003",
        "url": "",
    }
    payload.update(overrides)
    return ManualReferenceRequest(**payload)


def test_manual_journal_reference_formats_as_gbt_7714() -> None:
    citation = _format_manual_reference(_journal_reference())

    assert citation == (
        "张敏；李华. 新入职幼儿园教师专业成长的关键事件研究[J]. "
        "学前教育研究, 2024, 12(3): 45-56. DOI:10.1234/example.2024.003."
    )


def test_manual_reference_maps_to_existing_wizard_candidate_shape() -> None:
    item = _manual_reference_item(_journal_reference())

    assert item["source_name"] == "manual"
    assert item["type"] == "期刊论文"
    assert item["title"] == "新入职幼儿园教师专业成长的关键事件研究"
    assert item["manual"]["title"] == "新入职幼儿园教师专业成长的关键事件研究"
    assert item["citation"].startswith("张敏；李华.")


def test_manual_reference_rejects_invalid_doi_and_year() -> None:
    with pytest.raises(ValidationError):
        _journal_reference(doi="doi:invalid")
    with pytest.raises(ValidationError):
        _journal_reference(year="24")


def test_manual_web_reference_uses_eb_ol_marker() -> None:
    reference = _journal_reference(
        reference_type="web",
        source="教育部网站",
        volume="",
        issue="",
        pages="",
        doi="",
        url="https://www.moe.gov.cn/example",
    )

    assert "[EB/OL]" in _format_manual_reference(reference)
    assert "https://www.moe.gov.cn/example" in _format_manual_reference(reference)
