import json
from pathlib import Path

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.cross_reference_service import CrossReferenceService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.research_object_service import ResearchObjectService

TASK = "d" * 32


def setup_settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def make_chain(tmp_path: Path):
    settings = setup_settings(tmp_path); datasets = DatasetService(settings)
    v1 = datasets.import_data(filename="survey.csv", raw=b"group,score\nA,10\nB,20\n", name="问卷数据", task_id=TASK)
    analysis_service = AnalysisService(settings)
    analysis = analysis_service.create(task_id=TASK, dataset_id=v1["dataset_id"], dataset_version=1, analysis_type="anova", variables={"group_column": "group", "value_column": "score"})
    result = {"id": "ar_chain1", "analysis_id": analysis["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": f"{v1['dataset_id']}:v1", "data_fingerprint": v1["fingerprint"], "status": "ready", "result": {"method": "anova"}, "warnings": []}
    analysis["last_result_id"] = result["id"]; analysis_service._save(analysis); analysis_service._save_result(result)
    explanation = {"id": "ex_chain1", "analysis_id": analysis["id"], "analysis_result_id": result["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"], "status": "ready"}
    exp_path = settings.db_path.parent / "explanations" / analysis["id"] / f"{explanation['id']}.json"; exp_path.parent.mkdir(parents=True, exist_ok=True); exp_path.write_text(json.dumps(explanation), encoding="utf-8")
    draft_service = DraftService(TASK, settings.output_dir / TASK)
    ref = {"analysis_id": analysis["id"], "analysis_result_id": result["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"]}
    draft_service.save({"title": "依赖图测试", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []}, "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "1-1", "number": "1.1", "title": "结果", "level": 3, "gist": "", "paragraphs": [{"id": "t_chain1", "type": "table", "title": "ANOVA 表", "headers": ["A"], "rows": [["1"]], "analysis": ref}, {"id": "f_chain1", "type": "chart", "title": "ANOVA 图", "caption": "", "status": "ready", "asset": {"png_path": ""}, "analysis": ref}]}]})
    objects = ResearchObjectService(settings); objects.renumber_document_references(TASK); object_map = {item["source_id"]: item["id"] for item in objects.list(TASK) if item["type"] in {"table", "figure"}}
    finding = {"id": "rf_chain1", "task_id": TASK, "analysis_id": analysis["id"], "analysis_result_id": result["id"], "explanation_id": explanation["id"], "dataset_id": v1["dataset_id"], "dataset_version": 1, "dataset_version_id": result["dataset_version_id"], "data_fingerprint": v1["fingerprint"], "title": "ANOVA 结果", "status": "inserted", "research_object_ids": [object_map["t_chain1"], object_map["f_chain1"]]}
    finding_path = settings.db_path.parent / "findings" / f"{finding['id']}.json"; finding_path.parent.mkdir(parents=True, exist_ok=True); finding_path.write_text(json.dumps(finding), encoding="utf-8")
    reference = CrossReferenceService(settings).insert(task_id=TASK, section_id="1-1", target_object_id=object_map["f_chain1"])
    return settings, datasets, v1, analysis, result, finding, reference


def links_of(service: DependencyGraphService):
    return {(item["source_type"], item["target_type"], item["relation"]) for item in service.rebuild_task(TASK)}


def test_dataset_analysis_dependency(tmp_path):
    settings, *_ = make_chain(tmp_path)
    assert ("dataset_version", "analysis", "derived_from") in links_of(DependencyGraphService(settings))


def test_analysis_result_dependency(tmp_path):
    settings, *_ = make_chain(tmp_path)
    assert ("analysis", "analysis_result", "derived_from") in links_of(DependencyGraphService(settings))


def test_result_figure_and_table_dependencies(tmp_path):
    settings, *_ = make_chain(tmp_path); links = links_of(DependencyGraphService(settings))
    assert ("analysis_result", "figure", "renders") in links and ("analysis_result", "table", "renders") in links


def test_result_finding_and_explanation_dependencies(tmp_path):
    settings, *_ = make_chain(tmp_path); links = links_of(DependencyGraphService(settings))
    assert ("analysis_result", "finding", "derived_from") in links and ("analysis_result", "explanation", "explains") in links


def test_finding_cross_reference_dependency(tmp_path):
    settings, *_ = make_chain(tmp_path)
    assert ("finding", "cross_reference", "references") in links_of(DependencyGraphService(settings))


def test_impact_returns_all_downstream_layers(tmp_path):
    settings, _, v1, *_ = make_chain(tmp_path); impact = DependencyGraphService(settings).get_impact(task_id=TASK, dataset_id=v1["dataset_id"], version=1)
    assert all(impact[key] for key in ("analyses", "results", "tables", "figures", "explanations", "findings", "references"))


def test_stale_propagation_after_new_dataset_version(tmp_path):
    settings, datasets, v1, *_ = make_chain(tmp_path)
    datasets.import_data(filename="survey.csv", raw=b"group,score\nA,11\nB,29\n", dataset_id=v1["dataset_id"], task_id=TASK)
    impact = DependencyGraphService(settings).get_impact(task_id=TASK, dataset_id=v1["dataset_id"], version=1)
    assert impact["analyses"][0]["status"] == "stale"
    assert {item["status"] for key in ("results", "tables", "figures", "explanations", "findings") for item in impact[key]} == {"stale_source"}
    assert impact["references"][0]["status"] == "ready"


def test_broken_reference_status(tmp_path):
    settings, _, _, _, _, _, reference = make_chain(tmp_path)
    draft = DraftService(TASK, settings.output_dir / TASK).load(); draft["sections"][0]["paragraphs"] = [item for item in draft["sections"][0]["paragraphs"] if item["id"] != "f_chain1"]; DraftService(TASK, settings.output_dir / TASK).save(draft)
    records = DependencyGraphService(settings).results_center(TASK)["items"]
    assert next(item for item in records if item["id"] == reference["reference"]["id"])["status"] == "broken"


def test_lazy_rebuild_when_index_missing(tmp_path):
    settings, *_ = make_chain(tmp_path); service = DependencyGraphService(settings); service._path(TASK).unlink(missing_ok=True)
    assert service.get_downstream(TASK, "dataset_version", next(item for item in DatasetService(settings).list_datasets(TASK) if item)["id"] + ":v1")


def test_evidence_trail(tmp_path):
    settings, _, _, _, _, finding, _ = make_chain(tmp_path); evidence = DependencyGraphService(settings).evidence(finding["id"])
    assert evidence["dataset"]["version"] == 1 and evidence["analysis"]["type"] == "analysis" and evidence["result"]["type"] == "analysis_result" and evidence["figures"] and evidence["tables"] and evidence["cross_references"]


def test_multi_layer_downstream_and_cycle_guard(tmp_path):
    settings, _, v1, *_ = make_chain(tmp_path); service = DependencyGraphService(settings); links = service.rebuild_task(TASK)
    links.append(service._link(TASK, "cross_reference", "cr_cycle", "dataset_version", f"{v1['dataset_id']}:v1", "references")); service._write(TASK, links)
    # get_downstream rebuilds canonically and must still terminate with all normal descendants.
    assert len(service.get_downstream(TASK, "dataset_version", f"{v1['dataset_id']}:v1")) >= 6


def test_duplicate_links_are_idempotent(tmp_path):
    settings, *_ = make_chain(tmp_path); service = DependencyGraphService(settings)
    assert [item["id"] for item in service.rebuild_task(TASK)] == [item["id"] for item in service.rebuild_task(TASK)]


def test_results_center_filters(tmp_path):
    settings, *_ = make_chain(tmp_path); items = DependencyGraphService(settings).results_center(TASK, "figure")["items"]
    assert len(items) == 1 and items[0]["type"] == "figure"


def test_export_records_stale_warning(tmp_path):
    settings, datasets, v1, *_ = make_chain(tmp_path); datasets.import_data(filename="survey.csv", raw=b"group,score\nA,12\nB,31\n", dataset_id=v1["dataset_id"], task_id=TASK)
    service = DraftService(TASK, settings.output_dir / TASK); service.export(); assert service.load().get("export_warnings", {}).get("warnings")
