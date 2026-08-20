from __future__ import annotations

import tempfile
from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.service import DraftService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.literature_service import LiteratureService
from app.services.research_visualization_service import BROKEN, STALE, VERIFIED, ResearchVisualizationService

TASK = "v" * 32


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="research_visualizations_e2e_") as temp:
        root = Path(temp)
        settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        paper = DraftService(TASK, settings.output_dir / TASK)
        paper.save({"title": "传感器技术比较与研究可视化 E2E", "meta": {"major": "电子信息", "paper_type": "课程论文", "word_count": 1000, "keywords": []}, "abstract": {"zh": "验证", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "2-1", "number": "2.1", "title": "技术比较", "level": 2, "gist": "", "paragraphs": []}, {"id": "3-1", "number": "3.1", "title": "实验结果", "level": 2, "gist": "", "paragraphs": []}]})
        service = ResearchVisualizationService(settings)
        literature = LiteratureService(settings)

        # Case A: AI search planning executes first; public sources are then saved
        # with literal, publicly readable abstract quotations before extraction.
        plan = service.create_plan(task_id=TASK, topic="红外阵列传感器与毫米波雷达、可穿戴设备技术比较", chapter="第二章 原理与技术比较", research_question="哪些公开技术参数适合形成可追溯比较表？")
        assert plan["queries"] and plan["status"] == "planned"
        search = service.search(task_id=TASK, limit=3)
        assert search["plan"]["status"] == "searched"
        sources = service.save_sources(task_id=TASK, sources=[
            {"title": "Smart CMOS mid-infrared sensor array", "authors": ["Daniel Popa"], "year": 2019, "journal": "Optics Letters", "doi": "10.1364/OL.44.004111", "url": "https://opg.optica.org/abstract.cfm?uri=ol-44-17-4111", "abstract": "We demonstrate a pixel device with 34 V/W responsivity and enhanced optical absorption in the 8–14 μm waveband.", "source": "manual", "source_id": "opg-ol-44-4111", "external_id": "opg-ol-44-4111"},
            {"title": "Recent Advancements in Millimeter-Wave Antennas and Arrays", "authors": ["Faisal Mehmood"], "year": 2025, "journal": "Electronics", "doi": "10.3390/electronics14132705", "url": "https://www.mdpi.com/2079-9292/14/13/2705", "abstract": "A 60 GHz rectangular patch antenna fabricated on a flexible 0.05 mm Kapton substrate demonstrated a peak gain of approximately 5 dBi at 60.3 GHz.", "source": "manual", "source_id": "mdpi-electronics-2705", "external_id": "mdpi-electronics-2705"},
        ])
        evidence = service.extract(task_id=TASK, literature_ids=[item["id"] for item in sources])
        verified = [item for item in evidence if item["verification_status"] == VERIFIED and item["unit"] in {"V/W", "dBi"}]
        assert len(verified) == 2
        candidates = service.recommend(task_id=TASK, section="第二章 原理与技术比较", evidence_ids=[item["id"] for item in verified])
        comparison = next(item for item in candidates if item.get("kind") == "table" and item.get("table_type") == "technology_comparison")
        before = len(paper.load()["sections"][0]["paragraphs"])
        assert service.preview(comparison["id"])["requires_confirmation"] and len(paper.load()["sections"][0]["paragraphs"]) == before
        inserted_table = service.insert(candidate_id=comparison["id"], section_id="2-1")
        assert inserted_table["inserted"]["block"]["type"] == "table" and len(inserted_table["citations"]) == 2

        # Case B: an existing Dataset containing literal accuracy values from the
        # public PMC article drives a real ChartSpec/ChartAsset/FigureBlock.
        datasets = DatasetService(settings)
        dataset = datasets.import_data(filename="infrared_accuracy.csv", raw=b"resolution_pixels,accuracy_percent\n48,78.32\n192,90.11\n", name="红外阵列分辨率与准确率", description="Krishnan et al. (2022) abstract literal values", task_id=TASK)
        dataset_candidates = service.recommend(task_id=TASK, section="第三章 实验结果", dataset_id=dataset["dataset_id"], dataset_version=1)
        chart = next(item for item in dataset_candidates if item.get("kind") == "chart" and item.get("chart_kind") == "scatter")
        assert chart["chart"]["asset"]["png_path"]
        inserted_chart = service.insert(candidate_id=chart["id"], section_id="3-1")
        assert inserted_chart["inserted"]["block"]["type"] == "chart"

        paper.export()
        docx = settings.output_dir / TASK / "论文.docx"
        with ZipFile(docx) as archive:
            names = archive.namelist()
            document = archive.read("word/document.xml")
        assert any(name.startswith("word/media/") for name in names)
        assert b"Smart CMOS mid-infrared sensor array" in document
        assert "图1" in document.decode("utf-8") and "表1" in document.decode("utf-8")

        # Case C: source deletion marks the previously inserted comparison table
        # as broken provenance and exposes the state through the shared graph.
        literature.delete(sources[0]["id"])
        service.refresh_status(TASK)
        assert service.preview(comparison["id"])["candidate"]["status"] == BROKEN
        graph = DependencyGraphService(settings)._records(TASK)[0]
        assert graph[("visualization_candidate", comparison["id"])]["status"] == BROKEN

        # Case D: a new DatasetVersion marks the previously inserted chart stale.
        datasets.import_data(filename="infrared_accuracy_v2.csv", raw=b"resolution_pixels,accuracy_percent\n48,80.00\n192,92.00\n", dataset_id=dataset["dataset_id"], name="红外阵列分辨率与准确率", task_id=TASK)
        service.refresh_status(TASK)
        assert service.preview(chart["id"])["candidate"]["status"] == STALE
        graph = DependencyGraphService(settings)._records(TASK)[0]
        assert graph[("visualization_candidate", chart["id"])]["status"] == STALE
        print("Research Visualization E2E passed")
        print({"sources_saved": len(sources), "verified_evidence": len(verified), "table": comparison["id"], "chart": chart["id"], "docx": str(docx), "broken": comparison["id"], "stale": chart["id"]})


if __name__ == "__main__":
    main()
