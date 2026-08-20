"""Phase 8 E2E: Research Workspace -> explicit Research to Paper -> DOCX."""
from __future__ import annotations

import tempfile
from pathlib import Path
from zipfile import ZipFile

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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="research_workspace_e2e_") as temp:
        root = Path(temp)
        settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        paper = DraftService(TASK, settings.output_dir / TASK)
        paper.save({"title": "Research Workspace E2E", "meta": {"major": "教育学", "paper_type": "课程论文", "word_count": 800, "keywords": []}, "abstract": {"zh": "验证", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "4-1", "number": "4.1", "title": "讨论", "level": 3, "gist": "", "paragraphs": []}]})
        datasets, analyses, hypotheses = DatasetService(settings), AnalysisService(settings), HypothesisService(settings)
        dataset = datasets.import_data(filename="workspace.csv", raw=b"participation,satisfaction\n1,2\n2,5\n3,7\n4,9\n5,12\n6,14\n", name="学习参与数据", task_id=TASK)
        analysis = analyses.create(task_id=TASK, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="pearson", variables={"x": "participation", "y": "satisfaction"}, name="学习参与与满意度")
        result = analyses.run(analysis["id"])
        hypothesis = hypotheses.create(task_id=TASK, title="H1", statement="学习参与度与满意度呈正向关联。", direction="positive", analysis_ids=[analysis["id"]])
        evaluation = hypotheses.evaluate(hypothesis_id=hypothesis["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
        explanation = ResearchExplanationService(settings).explain(analysis_id=analysis["id"], analysis_result_id=result["id"])
        finding = ResearchFindingService(settings).generate(task_id=TASK, analysis_id=analysis["id"], analysis_result_id=result["id"], explanation_id=explanation["id"], style={"length": "standard"})
        literature = LiteratureService(settings)
        item = literature.save(task_id=TASK, metadata={"title": "Participation and Satisfaction", "authors": ["Zhang Wei"], "year": 2024, "abstract": "The abstract reports an association.", "source": "manual", "source_id": "workspace-e2e", "external_id": "workspace-e2e"})
        evidence = literature.add_evidence(literature_id=item["id"], claim="学习参与关联证据", evidence="The abstract reports an association.", source_location="abstract")
        literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=item["id"], relation="supporting")
        framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[hypothesis["id"]], finding_ids=[finding["id"]], evaluation_ids=[evaluation["id"]])
        discussion = DiscussionWriterService(settings).generate(task_id=TASK, framework_id=framework["id"], section_type="literature_comparison", hypothesis_ids=[hypothesis["id"]], finding_ids=[finding["id"]], literature_evidence_ids=[evidence["id"]])
        # Existing pipeline creates a real FigureBlock and persisted image asset.
        figure = insert_analysis_result(task_id=TASK, analysis=analysis, result=result, section_id="4-1", artifact="chart", storage_settings=settings)
        assert figure["block"]["type"] == "chart"
        workspace = ResearchWorkspaceService(settings)
        before = workspace.get(TASK)
        assert before["datasets"]["count"] == 1 and before["charts"]["count"] == 1
        assert before["findings"]["count"] == 1 and before["discussion"]["count"] == 1
        # Preview has no side effects; explicit confirmation executes table/finding/discussion insertion.
        insert = ResearchWorkspaceInsertService(settings)
        paragraphs_before = len(paper.load()["sections"][0]["paragraphs"])
        preview = insert.preview(task_id=TASK, source_type="analysis_result", source_id=result["id"], analysis_id=analysis["id"], section_id="4-1", artifact="table")
        assert preview["requires_confirmation"] and len(paper.load()["sections"][0]["paragraphs"]) == paragraphs_before
        assert insert.insert(task_id=TASK, source_type="analysis_result", source_id=result["id"], analysis_id=analysis["id"], section_id="4-1", artifact="table")["inserted"]["type"] == "table"
        assert insert.insert(task_id=TASK, source_type="finding", source_id=finding["id"], section_id="4-1")["inserted"]["block"]["type"] == "finding"
        assert insert.insert(task_id=TASK, source_type="discussion_draft", source_id=discussion["id"], section_id="4-1")["inserted"]["blocks"][0]["type"] == "discussion"
        paper.export()
        docx = settings.output_dir / TASK / "论文.docx"
        with ZipFile(docx) as archive:
            names = archive.namelist()
            document = archive.read("word/document.xml")
        assert any(name.startswith("word/media/") for name in names) and b"Participation and Satisfaction" in document
        # A fresh DatasetVersion and deleted cited source become human-facing Workspace warnings.
        datasets.import_data(filename="workspace-v2.csv", raw=b"participation,satisfaction\n1,3\n2,6\n3,9\n4,12\n5,15\n6,18\n", dataset_id=dataset["dataset_id"], task_id=TASK, name="学习参与数据")
        literature.delete(item["id"])
        after = workspace.get(TASK)
        issue_codes = {issue["code"] for issue in after["issues"]}
        assert {"stale_analyses", "stale_figures", "broken_citations"}.issubset(issue_codes)
        print("Research Workspace E2E passed")
        print({"workspace_datasets": after["datasets"]["count"], "stale_figures": after["charts"]["stale_count"], "issues": sorted(issue_codes), "docx": str(docx)})


if __name__ == "__main__":
    main()
