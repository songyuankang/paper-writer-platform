from app.models.generate import AbstractRequest


def test_abstract_request_allows_wizard_payload_without_outline() -> None:
    """摘要步骤在大纲步骤之前，前端不会传 outline。"""
    request = AbstractRequest(
        title="有机栽培模式下番茄果实品质研究",
        major="农学·设施农业",
        special_requirements="突出土壤微生物多样性",
    )

    assert request.outline == ""
    assert request.special_requirements == "突出土壤微生物多样性"
