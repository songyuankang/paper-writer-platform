"""Phase 6A end-to-end verification: document objects and persistent numbering."""
from __future__ import annotations

import tempfile
from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.chart_runtime import create_chart_block_from_table
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService
from app.services.research_object_service import ResearchObjectService

TASK = "o" * 32


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="research_objects_e2e_") as temporary:
        root = Path(temporary)
        settings = Settings(
            db_path=root / "data" / "history.db",
            output_dir=root / "outputs",
            upload_dir=root / "uploads",
            log_dir=root / "logs",
        )
        datasets = DatasetService(settings)
        dataset = datasets.import_data(
            filename="research.csv",
            raw=b"group,x,y\nA,1,2\nA,2,4\nB,3,6\nB,4,8\n",
            name="研究样本",
            task_id=TASK,
        )
        analyses = AnalysisService(settings)
        analysis = analyses.create(
            task_id=TASK,
            dataset_id=dataset["dataset_id"],
            dataset_version=1,
            analysis_type="pearson",
            variables={"x": "x", "y": "y"},
        )
        result = analyses.run(analysis["id"])
        explanation = ResearchExplanationService(settings).explain(
            analysis_id=analysis["id"], analysis_result_id=result["id"]
        )

        draft_service = DraftService(TASK, settings.output_dir / TASK)
        draft = draft_service.build({
            "title": "ResearchObject 编号验证", "major": "统计学", "paper_type": "课程论文",
            "word_count": 100, "reference_style": "gb7714", "abstract": "摘要", "keywords": [], "references": [],
        })
        section = draft["sections"][-1]
        table_one = {"id": "table_1", "type": "table", "title": "相关性统计表", "headers": ["类别", "数值"], "rows": [["A", "1"], ["B", "2"]], "analysis": {"analysis_result_id": result["id"]}}
        table_two = {"id": "table_2", "type": "table", "title": "待删除表", "headers": ["类别", "数值"], "rows": [["A", "3"], ["B", "4"]]}
        section["paragraphs"].extend([table_one, table_two])
        task_dir = settings.output_dir / TASK
        figure_one = create_chart_block_from_table(draft, task_dir, section, "figure_1", "bar", "样本柱状图", .75, "table_1", True)
        figure_two = create_chart_block_from_table(draft, task_dir, section, "figure_2", "line", "样本折线图", .75, "table_1", True)
        figure_one["analysis"] = {"analysis_result_id": result["id"]}
        figure_two["analysis"] = {"analysis_result_id": result["id"]}
        section["paragraphs"].extend([figure_one, figure_two])
        # Move the second FigureBlock before the first and remove the second TableBlock.
        paragraphs = section["paragraphs"]
        paragraphs.insert(2, paragraphs.pop(paragraphs.index(figure_two)))
        paragraphs.remove(table_two)
        draft_service.save(draft)

        objects = ResearchObjectService(settings)
        outcome = objects.renumber_document_references(TASK)
        saved = draft_service.load()
        content = saved["sections"][-1]["paragraphs"]
        labels = {item["id"]: (item.get("figure_number"), item.get("table_number")) for item in content}
        assert labels["figure_2"] == (1, None)
        assert labels["figure_1"] == (2, None)
        assert labels["table_1"] == (None, 1)
        assert len(outcome["figures"]) == 2 and len(outcome["tables"]) == 1

        finding = ResearchFindingService(settings).generate(
            task_id=TASK,
            analysis_id=analysis["id"],
            analysis_result_id=result["id"],
            explanation_id=explanation["id"],
            style={"length": "standard"},
        )
        assert len(finding["research_object_ids"]) == 3
        assert any(reference["label"].startswith("图1") for reference in finding["figure_references"])
        assert finding["table_references"][0]["label"].startswith("表1")

        files = draft_service.export()
        exported = next(item for item in files if item.endswith(".docx"))
        docx = Path(exported)
        if not docx.is_absolute():
            docx = task_dir / docx
        with ZipFile(docx) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        for title in ("图1 样本折线图", "图2 样本柱状图", "表1 相关性统计表"):
            assert title in document, title
        print("ResearchObject E2E passed")
        print({"figures": outcome["figures"], "tables": outcome["tables"], "docx": str(docx), "finding": finding["id"]})


if __name__ == "__main__":
    main()
