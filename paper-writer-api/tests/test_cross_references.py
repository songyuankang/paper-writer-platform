from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.service import DraftService
from app.services.cross_reference_service import CrossReferenceService
from app.services.research_object_service import ResearchObjectService

TASK = "c" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def figure(identifier: str, title: str) -> dict:
    return {"id": identifier, "type": "chart", "title": title, "caption": "", "status": "ready", "asset": {"png_path": ""}}


def table(identifier: str, title: str) -> dict:
    return {"id": identifier, "type": "table", "title": title, "headers": ["类别", "数值"], "rows": [["A", "1"], ["B", "2"]]}


def prepare(tmp_path: Path):
    settings = settings_for(tmp_path)
    draft = DraftService(TASK, settings.output_dir / TASK)
    doc = {"title": "交叉引用测试", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "1-1", "number": "1.1", "title": "结果", "level": 3, "gist": "", "paragraphs": [figure("f1", "第一图"), figure("f2", "第二图"), table("t1", "统计表"), {"id": "p1", "type": "paragraph", "text": "旧正文保持不变"}]}]}
    draft.save(doc)
    objects = ResearchObjectService(settings)
    objects.renumber_document_references(TASK)
    return settings, draft, objects, CrossReferenceService(settings)


def candidate(service: CrossReferenceService, object_type: str, source_id: str) -> dict:
    return next(item for item in service.reference_candidates(TASK) if item["type"] == object_type and item["source_id"] == source_id)


def test_create_figure_cross_reference(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    result = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f1")["id"])
    assert result["reference"]["target_type"] == "figure" and result["block"]["type"] == "cross_reference"


def test_create_table_cross_reference(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    result = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "table", "t1")["id"], prefix="见", suffix="")
    assert result["reference"]["target_type"] == "table" and result["block"]["text"] == "见表1"


def test_reference_displays_current_number(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f2")["id"])
    assert output["block"]["text"] == "如图2所示"


def test_deleted_target_becomes_broken(tmp_path: Path):
    _, draft, objects, service = prepare(tmp_path)
    reference = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f1")["id"])["reference"]
    doc = draft.load(); doc["sections"][0]["paragraphs"] = [item for item in doc["sections"][0]["paragraphs"] if item["id"] != "f1"]; draft.save(doc)
    objects.renumber_document_references(TASK)
    assert next(item for item in service.list(TASK) if item["id"] == reference["id"])["status"] == "broken"


def test_broken_reference_can_be_repaired(tmp_path: Path):
    _, draft, objects, service = prepare(tmp_path)
    old_target = candidate(service, "figure", "f1")["id"]
    reference = service.insert(task_id=TASK, section_id="1-1", target_object_id=old_target)["reference"]
    doc = draft.load(); doc["sections"][0]["paragraphs"] = [item for item in doc["sections"][0]["paragraphs"] if item["id"] != "f1"]; draft.save(doc); objects.renumber_document_references(TASK)
    updated = service.update(task_id=TASK, reference_id=reference["id"], target_object_id=candidate(service, "figure", "f2")["id"])
    assert updated["status"] == "ready" and updated["resolved_label"] == "图1"


def test_renumber_changes_label_but_not_target_id(tmp_path: Path):
    _, draft, objects, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f2")["id"])
    target_id = output["reference"]["target_object_id"]
    doc = draft.load(); doc["sections"][0]["paragraphs"] = [item for item in doc["sections"][0]["paragraphs"] if item["id"] != "f1"]; draft.save(doc); objects.renumber_document_references(TASK)
    current = next(item for item in service.list(TASK) if item["id"] == output["reference"]["id"])
    assert current["target_object_id"] == target_id and current["resolved_label"] == "图1"


def test_move_figure_updates_reference_label(tmp_path: Path):
    _, draft, objects, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f1")["id"])
    doc = draft.load(); blocks = doc["sections"][0]["paragraphs"]; blocks.insert(1, blocks.pop(0)); draft.save(doc); objects.renumber_document_references(TASK)
    current = next(item for item in service.list(TASK) if item["id"] == output["reference"]["id"])
    assert current["resolved_label"] == "图2"


def test_multiple_references_share_one_target(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    target = candidate(service, "figure", "f1")["id"]
    first = service.insert(task_id=TASK, section_id="1-1", target_object_id=target)["reference"]
    second = service.insert(task_id=TASK, section_id="1-1", target_object_id=target, prefix="见", suffix="") ["reference"]
    assert {first["target_object_id"], second["target_object_id"]} == {target} and len(service.list(TASK)) == 2


def test_delete_reference_removes_its_body_block(tmp_path: Path):
    _, draft, _, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f1")["id"])
    service.delete(task_id=TASK, reference_id=output["reference"]["id"])
    assert not service.list(TASK) and all(item["id"] != output["block"]["id"] for item in draft.load()["sections"][0]["paragraphs"])


def test_reference_candidates_only_include_figures_and_tables(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    assert {(item["type"], item["display_label"]) for item in service.reference_candidates(TASK)} == {("figure", "图1"), ("figure", "图2"), ("table", "表1")}


def test_reference_display_uses_object_not_cached_label(tmp_path: Path):
    _, draft, objects, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f2")["id"])
    path = settings_for(tmp_path).db_path.parent / "cross_references" / TASK / "references.json"
    raw = path.read_text(encoding="utf-8").replace("图2", "图999")
    path.write_text(raw, encoding="utf-8")
    doc = draft.load(); doc["sections"][0]["paragraphs"] = [item for item in doc["sections"][0]["paragraphs"] if item["id"] != "f1"]; draft.save(doc); objects.renumber_document_references(TASK)
    assert next(item for item in service.list(TASK) if item["id"] == output["reference"]["id"])["resolved_label"] == "图1"


def test_docx_uses_dynamic_cross_reference_label(tmp_path: Path):
    settings, draft, _, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "table", "t1")["id"], prefix="见", suffix="。")
    files = draft.export(); docx = next(Path(item) for item in files if item.endswith(".docx")); docx = docx if docx.is_absolute() else settings.output_dir / TASK / docx
    with ZipFile(docx) as archive: document = archive.read("word/document.xml").decode("utf-8")
    assert output["reference"]["target_object_id"] and "见表1。" in document


def test_finding_and_cross_reference_use_same_research_object(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    target = candidate(service, "table", "t1")["id"]
    reference = service.insert(task_id=TASK, section_id="1-1", target_object_id=target)["reference"]
    finding_like = {"research_object_ids": [target]}
    assert reference["target_object_id"] in finding_like["research_object_ids"]


def test_old_text_only_body_remains_compatible(tmp_path: Path):
    _, draft, _, service = prepare(tmp_path)
    old = next(item for item in draft.load()["sections"][0]["paragraphs"] if item["id"] == "p1")
    assert service.render_block_text(TASK, old) == "旧正文保持不变"


def test_references_are_listed_with_source_block(tmp_path: Path):
    _, _, _, service = prepare(tmp_path)
    output = service.insert(task_id=TASK, section_id="1-1", target_object_id=candidate(service, "figure", "f1")["id"])
    found = service.list(TASK)[0]
    assert found["source_block_id"] == output["block"]["id"] and found["task_id"] == TASK
