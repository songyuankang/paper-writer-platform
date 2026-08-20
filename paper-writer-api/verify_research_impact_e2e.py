"""Phase 6C E2E: DatasetVersion dependency impact is read-only and complete."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.cross_reference_service import CrossReferenceService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.research_object_service import ResearchObjectService

TASK = "i" * 32


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="research_impact_e2e_") as temporary:
        root = Path(temporary); settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        datasets = DatasetService(settings)
        v1 = datasets.import_data(filename="survey.csv", raw=b"group,score\nA,10\nB,20\n", name="问卷数据", task_id=TASK)
        analyses = AnalysisService(settings)
        analysis = analyses.create(task_id=TASK, dataset_id=v1["dataset_id"], dataset_version=1, analysis_type="anova", variables={"group_column": "group", "value_column": "score"}, name="ANOVA")
        result = {"id": "ar_impact_e2e", "analysis_id": analysis["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": f"{v1['dataset_id']}:v1", "data_fingerprint": v1["fingerprint"], "status": "ready", "result": {"method": "anova"}, "warnings": []}
        analysis["last_result_id"] = result["id"]; analyses._save(analysis); analyses._save_result(result)
        explanation = {"id": "ex_impact_e2e", "analysis_id": analysis["id"], "analysis_result_id": result["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"]}
        explanation_path = settings.db_path.parent / "explanations" / analysis["id"] / f"{explanation['id']}.json"; explanation_path.parent.mkdir(parents=True, exist_ok=True); explanation_path.write_text(json.dumps(explanation), encoding="utf-8")
        draft = DraftService(TASK, settings.output_dir / TASK); reference = {"analysis_id": analysis["id"], "analysis_result_id": result["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"]}
        draft.save({"title": "影响分析 E2E", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "1-1", "number": "1.1", "title": "结果", "level": 3, "gist": "", "paragraphs": [{"id": "table_e2e", "type": "table", "title": "ANOVA 表", "headers": ["A"], "rows": [["1"]], "analysis": reference}, {"id": "figure_e2e", "type": "chart", "title": "ANOVA 图", "caption": "", "status": "ready", "asset": {"png_path": ""}, "analysis": reference}]}]})
        objects = ResearchObjectService(settings); objects.renumber_document_references(TASK); object_ids = {item["source_id"]: item["id"] for item in objects.list(TASK) if item["type"] in {"table", "figure"}}
        finding = {"id": "rf_impact_e2e", "task_id": TASK, "analysis_id": analysis["id"], "analysis_result_id": result["id"], "explanation_id": explanation["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"], "title": "ANOVA 结果", "status": "inserted", "research_object_ids": list(object_ids.values())}
        finding_path = settings.db_path.parent / "findings" / f"{finding['id']}.json"; finding_path.parent.mkdir(parents=True, exist_ok=True); finding_path.write_text(json.dumps(finding), encoding="utf-8")
        inserted_reference = CrossReferenceService(settings).insert(task_id=TASK, section_id="1-1", target_object_id=object_ids["figure_e2e"])

        # The update creates v2 only; no result, figure, finding or reference is overwritten.
        v2 = datasets.import_data(filename="survey.csv", raw=b"group,score\nA,12\nB,31\n", dataset_id=v1["dataset_id"], task_id=TASK)
        graph = DependencyGraphService(settings); impact = graph.get_impact(task_id=TASK, dataset_id=v1["dataset_id"], version=1)
        assert v2["version"] == 2
        assert all(impact[key] for key in ("analyses", "results", "tables", "figures", "explanations", "findings", "references"))
        assert impact["analyses"][0]["status"] == "stale"
        assert all(item["status"] == "stale_source" for key in ("results", "tables", "figures", "explanations", "findings") for item in impact[key])
        assert impact["references"][0]["status"] == "ready"
        evidence = graph.evidence(finding["id"]); assert evidence["cross_references"][0]["id"] == inserted_reference["reference"]["id"]
        draft.export(); assert draft.load().get("export_warnings", {}).get("warnings")
        print("Research impact E2E passed")
        print({"dataset": v1["dataset_id"], "updated_to": v2["version"], "impact_counts": {key: len(impact[key]) for key in ("analyses", "results", "tables", "figures", "explanations", "findings", "references")}, "warning_count": len(draft.load()["export_warnings"]["warnings"])})


if __name__ == "__main__":
    main()
