"""Phase 7B E2E: public metadata -> Literature -> evidence -> discussion -> citation."""
from __future__ import annotations

import tempfile
import html
import re
from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.research_object_service import ResearchObjectService

TASK = "v" * 32


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="literature_evidence_e2e_") as temp:
        root = Path(temp); settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        literature = LiteratureService(settings)
        # E2E 1: a real public metadata search; candidate data is not saved until this explicit call.
        response = literature.searcher.search(query="digital learning satisfaction university students", sources=["crossref", "openalex"], limit=8)
        assert response["results"], response
        candidate = response["results"][0]; saved = literature.save(task_id=TASK, metadata=candidate)
        research_object = next(item for item in ResearchObjectService(settings).list(TASK) if item["type"] == "literature" and item["source_id"] == saved["id"])
        evidence_text = saved["abstract"] or saved["title"]
        location = "abstract" if saved["abstract"] else "metadata"
        card = literature.add_evidence(literature_id=saved["id"], claim="与数字学习满意度相关的公开研究证据", evidence=evidence_text, source_location=location)

        # Internal evidence remains an independently computed AnalysisResult.
        datasets, analyses, hypotheses = DatasetService(settings), AnalysisService(settings), HypothesisService(settings)
        dataset = datasets.import_data(filename="internal.csv", raw=b"engagement,satisfaction\n1,2\n2,3\n3,5\n4,6\n5,8\n6,9\n7,11\n8,12\n", name="内部相关数据", task_id=TASK)
        analysis = analyses.create(task_id=TASK, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="pearson", variables={"x": "engagement", "y": "satisfaction"}, name="参与度与满意度")
        result = analyses.run(analysis["id"])
        hypothesis = hypotheses.create(task_id=TASK, title="H1", statement="学习参与度与满意度正相关。", direction="positive", analysis_ids=[analysis["id"]])
        evaluation = hypotheses.evaluate(hypothesis_id=hypothesis["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
        assert evaluation["decision"] == "supported"
        link = literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis["id"], literature_id=saved["id"], relation="contextual")
        framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[hypothesis["id"]], evaluation_ids=[evaluation["id"]])
        assert card["id"] in framework["literature_evidence_ids"]

        # E2E 2: citation is object-backed, emitted into DOCX, then becomes broken on deletion.
        paper = DraftService(TASK, settings.output_dir / TASK)
        paper.save({"title": "文献证据 E2E", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "1-1", "number": "1.1", "title": "讨论", "level": 3, "gist": "", "paragraphs": []}]})
        inserted = literature.insert_citation(task_id=TASK, section_id="1-1", literature_id=saved["id"])
        files = paper.export(); docx = next(Path(item) for item in files if item.endswith(".docx")); docx = docx if docx.is_absolute() else settings.output_dir / TASK / docx
        with ZipFile(docx) as archive: document = archive.read("word/document.xml").decode("utf-8")
        docx_text = html.unescape(re.sub(r"<[^>]+>", "", document))
        assert inserted["citation"]["resolved_label"] in docx_text and saved["title"] in docx_text
        links = DependencyGraphService(settings).rebuild_task(TASK)
        assert any(item["source_type"] == "hypothesis" and item["target_id"] == saved["id"] for item in links)
        assert any(item["source_type"] == "discussion_framework" and item["target_id"] == card["id"] for item in links)
        literature.delete(saved["id"])
        assert literature.citations(TASK)[0]["status"] == "broken"
        assert "引用文献不存在" in literature.render_draft_text(TASK, paper.load())[inserted["block"]["id"]]
        print("Literature evidence E2E passed")
        print({"source": saved["source"], "literature": saved["id"], "research_object": research_object["id"], "evaluation": evaluation["decision"], "external_evidence": card["id"], "citation": "broken_after_delete"})


if __name__ == "__main__":
    main()
