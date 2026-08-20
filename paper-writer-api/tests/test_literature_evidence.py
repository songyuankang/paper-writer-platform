from pathlib import Path
from zipfile import ZipFile

import pytest

from app.config import Settings
from app.draft.service import DraftService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.research_object_service import ResearchObjectService

TASK = "l" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def metadata(**changes):
    item = {"title": "Digital learning satisfaction among university students", "authors": ["Zhang Wei", "Li Na", "Wang Yu"], "year": 2024, "journal": "Open Education", "doi": "10.1000/example.1", "url": "https://doi.org/10.1000/example.1", "abstract": "Digital learning satisfaction was positively associated with perceived support among university students.", "publisher": "Example Press", "source": "crossref", "source_id": "crossref", "external_id": "10.1000/example.1", "keywords": ["digital learning", "satisfaction"]}
    return {**item, **changes}


def draft(settings: Settings) -> DraftService:
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({"title": "文献引用测试", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "1-1", "number": "1.1", "title": "讨论", "level": 3, "gist": "", "paragraphs": []}]})
    return service


def test_literature_create_and_research_object(tmp_path):
    settings = settings_for(tmp_path); item = LiteratureService(settings).save(task_id=TASK, metadata=metadata())
    objects = ResearchObjectService(settings).list(TASK)
    assert item["id"].startswith("lit_") and any(row["type"] == "literature" and row["source_id"] == item["id"] for row in objects)


def test_doi_deduplication_and_metadata_update_preserves_note(tmp_path):
    service = LiteratureService(settings_for(tmp_path)); first = service.save(task_id=TASK, metadata=metadata(user_note="作者备注"))
    second = service.save(task_id=TASK, metadata=metadata(title="更新标题", abstract="更新摘要"))
    assert second["id"] == first["id"] and second["metadata_updated"] and second["user_note"] == "作者备注"


def test_external_source_deduplication(tmp_path):
    service = LiteratureService(settings_for(tmp_path)); first = service.save(task_id=TASK, metadata=metadata(doi="", source="openalex", external_id="https://openalex.org/W1"))
    second = service.save(task_id=TASK, metadata=metadata(doi="", source="openalex", external_id="https://openalex.org/W1", journal="更新期刊"))
    assert first["id"] == second["id"]


def test_title_year_author_fallback_deduplication(tmp_path):
    service = LiteratureService(settings_for(tmp_path)); first = service.save(task_id=TASK, metadata=metadata(doi="", source="manual", external_id=""))
    second = service.save(task_id=TASK, metadata=metadata(doi="", source="manual", external_id="", pages="1-10"))
    assert first["id"] == second["id"]


def test_search_adapter_normalization_and_deduplication(tmp_path, monkeypatch):
    service = LiteratureService(settings_for(tmp_path))
    row = metadata(); row.update(source="crossref", external_id="10.1000/example.1")
    monkeypatch.setattr(service.searcher, "_call_crossref", lambda *args: [row])
    monkeypatch.setattr(service.searcher, "_call_openalex", lambda *args: [{**row, "source": "openalex", "external_id": "W1"}])
    result = service.searcher.search(query="digital learning")
    assert len(result["results"]) == 1 and result["results"][0]["doi"] == "10.1000/example.1"


def test_search_fallback_without_external_service(tmp_path, monkeypatch):
    service = LiteratureService(settings_for(tmp_path)); monkeypatch.setattr(service.searcher, "_call_crossref", lambda *args: []); monkeypatch.setattr(service.searcher, "_call_openalex", lambda *args: [])
    result = service.searcher.search(query="unavailable provider")
    assert result["results"] == [] and "手工录入" in result["warning"]


def test_evidence_saved_with_verified_abstract_source(tmp_path):
    service = LiteratureService(settings_for(tmp_path)); item = service.save(task_id=TASK, metadata=metadata())
    evidence = service.add_evidence(literature_id=item["id"], claim="学习支持与满意度相关", evidence="positively associated with perceived support", source_location="abstract")
    assert evidence["source_location"] == "abstract" and service.evidence(item["id"])[0]["id"] == evidence["id"]


def test_unverified_or_ai_invented_evidence_rejected(tmp_path):
    service = LiteratureService(settings_for(tmp_path)); item = service.save(task_id=TASK, metadata=metadata())
    with pytest.raises(ValueError, match="核验"):
        service.add_evidence(literature_id=item["id"], claim="AI 推测结论", evidence="AI invented causal result p=0.001", source_location="abstract")


def test_hypothesis_literature_all_relations(tmp_path):
    settings = settings_for(tmp_path); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    hypothesis = HypothesisService(settings).create(task_id=TASK, title="H1", statement="学习满意度相关", analysis_ids=[])
    for relation in ["supporting", "contradicting", "contextual", "related"]:
        link = literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=item["id"], relation=relation)
        assert link["relation"] == relation


def test_citation_label_and_docx_output(tmp_path):
    settings = settings_for(tmp_path); paper = draft(settings); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    output = literature.insert_citation(task_id=TASK, section_id="1-1", literature_id=item["id"])
    assert output["citation"]["resolved_label"] == "(Wei et al., 2024)"
    files = paper.export(); docx = next(Path(value) for value in files if value.endswith(".docx")); docx = docx if docx.is_absolute() else settings.output_dir / TASK / docx
    with ZipFile(docx) as archive: document = archive.read("word/document.xml").decode("utf-8")
    assert "(Wei et al., 2024)" in document and "Digital learning satisfaction among university students" in document and "10.1000/example.1" in document


def test_deleted_literature_makes_citation_broken_without_deleting_body(tmp_path):
    settings = settings_for(tmp_path); paper = draft(settings); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    block = literature.insert_citation(task_id=TASK, section_id="1-1", literature_id=item["id"])["block"]; literature.delete(item["id"])
    citation = literature.citations(TASK)[0]
    assert citation["status"] == "broken" and "引用文献不存在" in literature.render_draft_text(TASK, paper.load())[block["id"]]


def test_dependency_graph_contains_literature_links(tmp_path):
    settings = settings_for(tmp_path); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    hypothesis = HypothesisService(settings).create(task_id=TASK, title="H1", statement="学习满意度相关", analysis_ids=[])
    literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=item["id"], relation="supporting")
    card = literature.add_evidence(literature_id=item["id"], claim="相关", evidence="positively associated with perceived support", source_location="abstract")
    citation = literature.create_citation(task_id=TASK, literature_id=item["id"])
    links = DependencyGraphService(settings).rebuild_task(TASK)
    assert any(link["source_type"] == "hypothesis" and link["target_id"] == item["id"] for link in links)
    assert any(link["target_type"] == "literature_evidence" and link["target_id"] == card["id"] for link in links)
    assert any(link["source_type"] == "citation" and link["source_id"] == citation["id"] for link in links)


def test_framework_snapshots_external_evidence(tmp_path):
    settings = settings_for(tmp_path); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    hypothesis = HypothesisService(settings).create(task_id=TASK, title="H1", statement="学习满意度相关", analysis_ids=[])
    literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=item["id"], relation="related")
    card = literature.add_evidence(literature_id=item["id"], claim="相关", evidence="positively associated with perceived support", source_location="abstract")
    framework = HypothesisService(settings).create_framework(task_id=TASK, hypothesis_ids=[hypothesis["id"]])
    assert card["id"] in framework["literature_evidence_ids"]


def test_delete_does_not_overwrite_external_evidence_snapshot(tmp_path):
    settings = settings_for(tmp_path); literature = LiteratureService(settings); item = literature.save(task_id=TASK, metadata=metadata())
    card = literature.add_evidence(literature_id=item["id"], claim="相关", evidence="positively associated with perceived support", source_location="abstract")
    literature.delete(item["id"])
    assert literature.get(item["id"])["status"] == "deleted" and literature._evidence_dir(item["id"]).joinpath(f"{card['id']}.json").is_file()
