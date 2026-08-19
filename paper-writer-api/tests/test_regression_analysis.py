from __future__ import annotations

import zipfile
from pathlib import Path

from app.config import Settings
from app.draft import analysis_blocks
from app.draft.analysis_blocks import insert_analysis_result
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

TASK_ID = "e" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def _services(tmp_path: Path, rows: str) -> tuple[Settings, DatasetService, AnalysisService, dict]:
    settings = _settings(tmp_path)
    datasets = DatasetService(settings)
    dataset = datasets.import_data(filename="regression.csv", raw=("y,x1,x2,label\n" + rows).encode("utf-8"), name="回归样本", task_id=TASK_ID)
    return settings, datasets, AnalysisService(settings), dataset


def _create(service: AnalysisService, dataset: dict, predictors: list[str] | None = None, dependent: str = "y") -> dict:
    return service.create(task_id=TASK_ID, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="regression", variables={"dependent_variable": dependent, "predictors": predictors or ["x1", "x2"]}, parameters={"alpha": .05})


def _rows() -> str:
    values = []
    for index, (x1, x2, noise) in enumerate([(1,2,.4),(2,1,-.2),(3,4,.3),(4,2,-.4),(5,6,.2),(6,3,.1),(7,8,-.1),(8,5,.35),(9,7,-.25),(10,9,.15),(11,4,-.3),(12,10,.25)]):
        values.append(f"{3 + 1.8*x1 - .7*x2 + noise},{x1},{x2},r{index}")
    return "\n".join(values) + "\n"


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def test_ols_single_multiple_coefficients_r2_f_ci_vif_and_missing(tmp_path: Path):
    settings, _, analyses, dataset = _services(tmp_path, _rows() + ",13,2,missing\n")
    single = analyses.run(_create(analyses, dataset, ["x1"])["id"])
    assert single["status"] == "ready" and single["result"]["n"] == 12
    multiple = analyses.run(_create(analyses, dataset)["id"])
    payload = multiple["result"]
    assert multiple["status"] == "ready" and payload["method"] == "ols"
    assert payload["r_squared"] > .98 and payload["adjusted_r_squared"] > .97 and payload["f_p_value"] < .001
    coefficients = {item["variable"]: item for item in payload["coefficients"]}
    assert abs(coefficients["x1"]["coefficient"] - 1.8) < .1 and abs(coefficients["x2"]["coefficient"] + .7) < .1
    assert coefficients["x1"]["ci_lower"] < coefficients["x1"]["coefficient"] < coefficients["x1"]["ci_upper"]
    assert all(item["vif"] >= 1 for item in payload["vif"]) and payload["excluded_rows"] == 1


def test_regression_rejects_duplicate_self_constant_and_collinear_predictors(tmp_path: Path):
    _, _, analyses, dataset = _services(tmp_path, _rows())
    duplicate = analyses.run(_create(analyses, dataset, ["x1", "x1"])["id"])
    assert duplicate["status"] == "failed" and "重复" in duplicate["warnings"][0]
    self_predictor = analyses.run(_create(analyses, dataset, ["y"])["id"])
    assert self_predictor["status"] == "failed" and "因变量" in self_predictor["warnings"][0]
    constant = _services(tmp_path / "constant", "1,1,2,a\n2,1,3,b\n3,1,4,c\n4,1,5,d\n5,1,6,e\n6,1,7,f\n")
    constant_result = constant[2].run(_create(constant[2], constant[3], ["x1", "x2"])["id"])
    assert constant_result["status"] == "failed" and "常数自变量" in constant_result["warnings"][0]
    collinear = _services(tmp_path / "collinear", "3,1,2,a\n5,2,4,b\n7,3,6,c\n9,4,8,d\n11,5,10,e\n13,6,12,f\n")
    collinear_result = collinear[2].run(_create(collinear[2], collinear[3])["id"])
    assert collinear_result["status"] == "failed" and "共线" in collinear_result["warnings"][0]


def test_regression_stale_and_rerun_preserve_result_history(tmp_path: Path):
    _, datasets, analyses, dataset = _services(tmp_path, _rows())
    analysis = _create(analyses, dataset)
    first = analyses.run(analysis["id"])
    changed = datasets.import_data(filename="regression.csv", raw=("y,x1,x2,label\n" + _rows() + "28,13,0,new\n").encode("utf-8"), dataset_id=dataset["dataset_id"])
    assert changed["version"] == 2 and analyses.get(analysis["id"])["status"] == "stale"
    second = analyses.run(analysis["id"])
    assert second["dataset_version"] == 2 and second["id"] != first["id"]
    assert analyses.get_result(analysis["id"], first["id"])["dataset_version"] == 1


def test_regression_tables_three_chart_specs_and_docx(tmp_path: Path, monkeypatch):
    settings, _, analyses, dataset = _services(tmp_path, _rows())
    monkeypatch.setattr(analysis_blocks, "settings", settings)
    task_dir = settings.output_dir / TASK_ID
    drafts = DraftService(TASK_ID, task_dir)
    draft = drafts.build({"title": "回归验证", "major": "管理学", "paper_type": "课程论文", "word_count": 1000, "reference_style": "gb7714", "abstract": "验证。", "keywords": ["回归"], "references": []})
    section = _leaf(draft); section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]; drafts.save(draft)
    analysis = _create(analyses, dataset); result = analyses.run(analysis["id"]); current = analyses.get(analysis["id"])
    table = insert_analysis_result(task_id=TASK_ID, analysis=current, result=result, section_id=section["id"], artifact="table")
    charts = [insert_analysis_result(task_id=TASK_ID, analysis=current, result=result, section_id=section["id"], artifact=kind)["block"] for kind in ["actual_predicted", "residual", "coefficient"]]
    assert len(table["blocks"]) == 2 and [item["chart_spec"]["binding"]["regression_chart_type"] for item in charts] == ["actual_predicted", "residual", "coefficient"]
    drafts.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        assert sum(name.startswith("word/media/") for name in document.namelist()) >= 3
        assert b"w:tbl" in document.read("word/document.xml")
