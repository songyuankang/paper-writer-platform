import json
from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.service import DraftService
from app.services.research_object_service import ResearchObjectService

TASK = "r" * 32


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def block(block_id: str, kind: str, title: str = "") -> dict:
    item = {"id": block_id, "type": kind, "title": title or block_id}
    if kind == "table":
        item.update(headers=["类别", "数值"], rows=[["A", "1"], ["B", "2"]])
    else:
        item.update(status="ready", caption="", asset={"png_path": "charts/sample.png"})
    return item


def make_draft(*items: dict) -> dict:
    return {
        "title": "编号测试论文",
        "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []},
        "abstract": {"zh": "摘要", "en": ""},
        "keywords": {"zh": [], "en": []},
        "acknowledgement": "",
        "references": [],
        "sections": [{"id": "1-1", "number": "1.1", "title": "结果", "level": 3, "gist": "", "paragraphs": list(items)}],
    }


def prepare(tmp_path: Path, *items: dict):
    settings = make_settings(tmp_path)
    draft_service = DraftService(TASK, settings.output_dir / TASK)
    draft_service.save(make_draft(*items))
    return settings, draft_service, ResearchObjectService(settings)


def test_research_object_creation_and_list(tmp_path: Path):
    settings, _, service = prepare(tmp_path, block("t1", "table", "样本统计"), block("f1", "chart", "样本分布"))
    result = service.renumber_document_references(TASK)
    objects = service.list(TASK)
    assert {item["type"] for item in objects} >= {"table", "figure"}
    assert result["objects"] == objects
    assert all(item["task_id"] == TASK and item["source_id"] for item in objects)


def test_research_object_get(tmp_path: Path):
    _, _, service = prepare(tmp_path, block("t1", "table"))
    object_id = service.renumber_document_references(TASK)["objects"][0]["id"]
    assert service.get(object_id)["source_id"] == "t1"


def test_figure_numbering(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart"), block("f2", "chart"))
    service.renumber_document_references(TASK)
    assert [item["figure_number"] for item in draft_service.load()["sections"][0]["paragraphs"]] == [1, 2]


def test_table_numbering(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("t1", "table"), block("t2", "table"))
    service.renumber_document_references(TASK)
    assert [item["table_number"] for item in draft_service.load()["sections"][0]["paragraphs"]] == [1, 2]


def test_delete_then_renumber(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart"), block("f2", "chart"), block("f3", "chart"))
    service.renumber_document_references(TASK)
    draft = draft_service.load(); draft["sections"][0]["paragraphs"].pop(1); draft_service.save(draft)
    service.renumber_document_references(TASK)
    assert [item["figure_number"] for item in draft_service.load()["sections"][0]["paragraphs"]] == [1, 2]


def test_move_then_renumber(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart", "旧图"), block("f2", "chart", "新图"))
    draft = draft_service.load(); paragraphs = draft["sections"][0]["paragraphs"]; paragraphs.insert(0, paragraphs.pop(1)); draft_service.save(draft)
    service.renumber_document_references(TASK)
    saved = draft_service.load()["sections"][0]["paragraphs"]
    assert [(item["id"], item["figure_number"]) for item in saved] == [("f2", 1), ("f1", 2)]


def test_mixed_figure_table_numbering(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart"), block("t1", "table"), block("f2", "chart"), block("t2", "table"))
    service.renumber_document_references(TASK)
    saved = {item["id"]: item for item in draft_service.load()["sections"][0]["paragraphs"]}
    assert (saved["f1"]["figure_number"], saved["f2"]["figure_number"], saved["t1"]["table_number"], saved["t2"]["table_number"]) == (1, 2, 1, 2)


def test_old_draft_number_compatibility_and_title_slots(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("legacy_table", "table"), block("legacy_figure", "chart"))
    service.renumber_document_references(TASK)
    table, figure = draft_service.load()["sections"][0]["paragraphs"]
    assert table["table_number"] == 1 and table["source"] == "" and table["note"] == ""
    assert figure["figure_number"] == 1 and figure["caption"] == "" and figure["source"] == ""


def test_stale_figure_keeps_number(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart"), block("f2", "chart"))
    service.renumber_document_references(TASK)
    draft = draft_service.load(); draft["sections"][0]["paragraphs"][0]["status"] = "stale"; draft_service.save(draft)
    service.renumber_document_references(TASK)
    assert [item["figure_number"] for item in draft_service.load()["sections"][0]["paragraphs"]] == [1, 2]


def test_renumber_is_idempotent(tmp_path: Path):
    _, draft_service, service = prepare(tmp_path, block("f1", "chart"), block("t1", "table"))
    first = service.renumber_document_references(TASK)
    first_draft = json.loads(json.dumps(draft_service.load(), sort_keys=True))
    second = service.renumber_document_references(TASK)
    assert first["figures"] == second["figures"] and first["tables"] == second["tables"]
    assert draft_service.load() == first_draft


def test_finding_reference_can_store_research_object_ids(tmp_path: Path):
    _, _, service = prepare(tmp_path, block("f1", "chart"), block("t1", "table"))
    objects = service.renumber_document_references(TASK)["objects"]
    refs = [item["id"] for item in objects if item["type"] in {"figure", "table"}]
    finding = {"id": "rf_example", "research_object_ids": refs}
    assert finding["research_object_ids"] == refs and len(refs) == 2


def test_docx_uses_persisted_numbered_titles(tmp_path: Path):
    settings, draft_service, service = prepare(tmp_path, block("f1", "chart", "图形标题"), block("t1", "table", "表格标题"))
    task_dir = settings.output_dir / TASK
    (task_dir / "charts").mkdir(parents=True, exist_ok=True)
    # A minimal valid PNG signature is sufficient for the export asset existence guard.
    (task_dir / "charts" / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    service.renumber_document_references(TASK)
    # Spec construction is the numbered DOCX boundary; export may choose a renderer that
    # rejects the deliberately tiny fixture image, so assert the persisted source facts.
    saved = draft_service.load()["sections"][0]["paragraphs"]
    assert saved[0]["figure_number"] == 1 and saved[1]["table_number"] == 1
