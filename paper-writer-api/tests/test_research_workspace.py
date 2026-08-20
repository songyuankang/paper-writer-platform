from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import research_workspace as workspace_api
from app.api import research_workspace_insert as workspace_insert_api

from app.config import Settings
from app.draft.analysis_blocks import insert_analysis_result
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.discussion_writer_service import DiscussionWriterService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService
from app.services.research_workspace_insert_service import ResearchWorkspaceInsertService
from app.services.research_workspace_service import ResearchWorkspaceService

TASK = "8" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def build_chain(tmp_path: Path):
    settings = settings_for(tmp_path)
    paper = DraftService(TASK, settings.output_dir / TASK)
    paper.save({"title": "Workspace 验证", "meta": {"paper_type": "课程论文", "word_count": 100, "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "4-1", "number": "4.1", "title": "讨论", "level": 3, "gist": "", "paragraphs": []}]})
    datasets, analyses, hypotheses = DatasetService(settings), AnalysisService(settings), HypothesisService(settings)
    dataset = datasets.import_data(filename="workspace.csv", raw=b"x,y\n1,2\n2,4\n3,7\n4,9\n5,12\n6,14\n", name="Workspace 数据", task_id=TASK)
    analysis = analyses.create(task_id=TASK, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="pearson", variables={"x": "x", "y": "y"}, name="X 与 Y")
    result = analyses.run(analysis["id"])
    hypothesis = hypotheses.create(task_id=TASK, title="H1", statement="X 与 Y 呈正向关联。", direction="positive", analysis_ids=[analysis["id"]])
    evaluation = hypotheses.evaluate(hypothesis_id=hypothesis["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    explanation = ResearchExplanationService(settings).explain(analysis_id=analysis["id"], analysis_result_id=result["id"])
    finding = ResearchFindingService(settings).generate(task_id=TASK, analysis_id=analysis["id"], analysis_result_id=result["id"], explanation_id=explanation["id"], style={})
    literature = LiteratureService(settings)
    item = literature.save(task_id=TASK, metadata={"title": "Workspace Literature", "authors": ["Zhang Wei"], "year": 2024, "abstract": "Association evidence.", "source": "manual", "source_id": "workspace", "external_id": "workspace"})
    evidence = literature.add_evidence(literature_id=item["id"], claim="关联证据", evidence="Association evidence.", source_location="abstract")
    literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=item["id"], relation="supporting")
    framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[hypothesis["id"]], finding_ids=[finding["id"]], evaluation_ids=[evaluation["id"]])
    discussion = DiscussionWriterService(settings).generate(task_id=TASK, framework_id=framework["id"], section_type="main_findings", finding_ids=[finding["id"]], literature_evidence_ids=[evidence["id"]])
    inserted_chart = insert_analysis_result(task_id=TASK, analysis=analysis, result=result, section_id="4-1", artifact="chart", storage_settings=settings)
    citation = literature.insert_citation(task_id=TASK, section_id="4-1", literature_id=item["id"])
    return settings, datasets, analyses, literature, paper, analysis, result, finding, evaluation, discussion, inserted_chart, citation, item


def test_workspace_summary_is_lightweight_and_human_facing(tmp_path: Path):
    settings, _, _, _, _, _, _, finding, _, discussion, _, _, _ = build_chain(tmp_path)
    payload = ResearchWorkspaceService(settings).get(TASK)
    assert payload["project"]["has_paper"] is True
    assert payload["datasets"]["count"] == 1 and "rows" not in payload["datasets"]["items"][0]
    assert payload["analyses"]["count"] == 1
    assert payload["charts"]["count"] == 1 and payload["tables"]["count"] == 0
    assert payload["findings"]["count"] == 1 and payload["discussion"]["count"] == 1
    assert payload["discussion"]["items"][0]["id"] == discussion["id"]
    assert payload["impact_summary"]["relationship_count"] >= 1
    assert {item["id"] for item in payload["templates"]} == {"survey", "experiment", "empirical", "custom"}
    assert finding["id"] not in str(payload["issues"])


def test_workspace_reports_stale_and_broken_without_rewriting_sources(tmp_path: Path):
    settings, datasets, _, literature, _, _, result, _, _, discussion, _, _, item = build_chain(tmp_path)
    datasets.import_data(filename="workspace-v2.csv", raw=b"x,y\n1,3\n2,6\n3,9\n4,12\n5,15\n6,18\n", dataset_id=result["dataset_id"], task_id=TASK, name="Workspace 数据")
    literature.delete(item["id"])
    payload = ResearchWorkspaceService(settings).get(TASK)
    codes = {item["code"] for item in payload["issues"]}
    assert "stale_analyses" in codes and "stale_figures" in codes and "broken_citations" in codes
    assert payload["charts"]["stale_count"] == 1
    assert ResearchWorkspaceService(settings).discussion.get(discussion["id"])["status"] == "stale"


def test_workspace_api_summary_templates_and_confirmation_gate(tmp_path: Path, monkeypatch):
    settings, _, _, _, _, analysis, result, _, _, _, _, _, _ = build_chain(tmp_path)
    monkeypatch.setattr(workspace_api, "settings", settings)
    monkeypatch.setattr(workspace_insert_api, "settings", settings)
    payload = workspace_api.research_workspace(TASK)
    assert payload["project"]["title"] == "Workspace 验证"
    assert len(workspace_api.workspace_templates()["templates"]) == 4
    request = workspace_insert_api.InsertPreviewRequest(task_id=TASK, source_type="analysis_result", source_id=result["id"], analysis_id=analysis["id"], section_id="4-1", artifact="table")
    assert workspace_insert_api.insert_preview(request)["requires_confirmation"] is True
    with pytest.raises(HTTPException, match="请确认"):
        workspace_insert_api.insert_into_paper(workspace_insert_api.ConfirmInsertRequest(**request.model_dump(), confirmed=False))


def test_workspace_preview_never_writes_and_confirmed_insert_uses_existing_blocks(tmp_path: Path):
    settings, _, _, _, paper, analysis, result, finding, evaluation, discussion, _, _, _ = build_chain(tmp_path)
    service = ResearchWorkspaceInsertService(settings)
    before = len(paper.load()["sections"][0]["paragraphs"])
    preview = service.preview(task_id=TASK, source_type="analysis_result", source_id=result["id"], analysis_id=analysis["id"], section_id="4-1", artifact="table")
    assert preview["requires_confirmation"] is True and len(paper.load()["sections"][0]["paragraphs"]) == before
    inserted_table = service.insert(task_id=TASK, source_type="analysis_result", source_id=result["id"], analysis_id=analysis["id"], section_id="4-1", artifact="table")
    assert inserted_table["inserted"]["type"] == "table"
    inserted_finding = service.insert(task_id=TASK, source_type="finding", source_id=finding["id"], section_id="4-1")
    assert inserted_finding["inserted"]["block"]["type"] == "finding"
    inserted_discussion = service.insert(task_id=TASK, source_type="discussion_draft", source_id=discussion["id"], section_id="4-1")
    assert inserted_discussion["inserted"]["blocks"][0]["type"] == "discussion"
    inserted_evaluation = service.insert(task_id=TASK, source_type="hypothesis_evaluation", source_id=evaluation["id"], section_id="4-1")
    assert inserted_evaluation["inserted"]["block"]["hypothesis_evaluation"]["evaluation_id"] == evaluation["id"]
