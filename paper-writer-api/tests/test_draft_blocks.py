from pathlib import Path
from threading import RLock

from app.draft import block_service
from app.api.draft import router as draft_router


class _FakeDraftService:
    def __init__(self) -> None:
        self.lock = RLock()
        self.draft = {"sections": [{"id": "1-1", "paragraphs": []}]}

    def load(self):
        return self.draft

    def save(self, draft):
        self.draft = draft

    def _find_section(self, draft, section_id):
        for section in draft["sections"]:
            if section["id"] == section_id:
                return section
        raise ValueError("section missing")

    @staticmethod
    def _next_paragraph_id(section):
        return f"p-{len(section['paragraphs']) + 1}"


def test_structured_block_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in draft_router.routes}
    assert "/api/draft/{task_id}/table" in paths
    assert "/api/draft/{task_id}/block/{block_id}" in paths


def test_table_block_add_and_edit_preserves_rows() -> None:
    service = _FakeDraftService()
    block = block_service.add_table(service, "1-1", "性能对比", ["特点", "优势"], [["功率密度", "输出大"]])
    assert block["type"] == "table"
    updated = block_service.update_block(service, block["id"], {
        "headers": ["特点", "优势", "局限性"],
        "rows": [["功率密度", "输出大", "占用空间较大"]],
    })
    assert updated["rows"][0][2] == "占用空间较大"
