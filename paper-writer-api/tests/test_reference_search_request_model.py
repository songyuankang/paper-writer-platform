from app.models.generate import ReferenceSearchRequest


def test_reference_search_request_accepts_wizard_title_and_keywords() -> None:
    request = ReferenceSearchRequest(
        title="有机栽培模式下番茄果实品质研究",
        keywords=["有机栽培", "番茄", "土壤微生物"],
        limit=12,
    )

    assert request.title == "有机栽培模式下番茄果实品质研究"
    assert request.keywords == ["有机栽培", "番茄", "土壤微生物"]
