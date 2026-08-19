from __future__ import annotations

import math
import zipfile
from pathlib import Path

from app.config import Settings
from app.draft import analysis_blocks
from app.draft.analysis_blocks import insert_analysis_result
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

TASK_ID = "a" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def _services(tmp_path: Path) -> tuple[Settings, DatasetService, AnalysisService, dict]:
    settings = _settings(tmp_path)
    datasets = DatasetService(settings)
    raw = (
        "x,y,rank,category,constant,label\n"
        "1,2,10,A,1,alpha\n"
        "2,4,30,B,1,beta\n"
        "3,6,20,A,1,gamma\n"
        "4,,40,,1,delta\n"
        "5,10,50,B,1,epsilon\n"
    ).encode("utf-8")
    dataset = datasets.import_data(filename="analysis.csv", raw=raw, name="分析样本", task_id=TASK_ID)
    return settings, datasets, AnalysisService(settings), dataset


def _create(service: AnalysisService, dataset: dict, kind: str, variables: dict) -> dict:
    return service.create(task_id=TASK_ID, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type=kind, variables=variables)


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def test_descriptive_numeric_categorical_and_missing_values(tmp_path: Path):
    _, _, analyses, dataset = _services(tmp_path)
    analysis = _create(analyses, dataset, "descriptive", {"columns": ["x", "y", "category"]})
    result = analyses.run(analysis["id"])
    assert result["status"] == "ready"
    numeric = {item["variable"]: item for item in result["result"]["numeric"]}
    assert numeric["x"]["count"] == 5 and numeric["x"]["mean"] == 3.0
    assert numeric["y"]["missing"] == 1 and numeric["y"]["median"] == 5.0
    categorical = result["result"]["categorical"][0]
    assert categorical["variable"] == "category" and categorical["missing"] == 1
    assert {item["category"]: item["frequency"] for item in categorical["frequency"]} == {"A": 2, "B": 2}


def test_pearson_uses_pairwise_valid_observations_and_fingerprint(tmp_path: Path):
    _, _, analyses, dataset = _services(tmp_path)
    analysis = _create(analyses, dataset, "pearson", {"x": "x", "y": "y"})
    result = analyses.run(analysis["id"])
    assert result["status"] == "ready"
    assert result["result"]["n"] == 4
    assert math.isclose(result["result"]["r"], 1.0)
    assert result["data_fingerprint"] == dataset["fingerprint"]
    assert result["warnings"] and "排除 1 行" in result["warnings"][0]


def test_spearman_constant_and_non_numeric_failures_are_structured(tmp_path: Path):
    _, _, analyses, dataset = _services(tmp_path)
    spearman = analyses.run(_create(analyses, dataset, "spearman", {"x": "x", "y": "rank"})["id"])
    assert spearman["status"] == "ready" and math.isfinite(spearman["result"]["rho"])
    constant = analyses.run(_create(analyses, dataset, "pearson", {"x": "x", "y": "constant"})["id"])
    assert constant["status"] == "failed" and "常数变量" in constant["warnings"][0]
    text = analyses.run(_create(analyses, dataset, "pearson", {"x": "x", "y": "label"})["id"])
    assert text["status"] == "failed" and "数值变量" in text["warnings"][0]


def test_dataset_version_marks_analysis_stale_and_rerun_preserves_old_result(tmp_path: Path):
    _, datasets, analyses, dataset = _services(tmp_path)
    analysis = _create(analyses, dataset, "pearson", {"x": "x", "y": "y"})
    old = analyses.run(analysis["id"])
    changed = datasets.import_data(
        filename="analysis.csv",
        raw=("x,y,rank,category,constant,label\n1,2,10,A,1,alpha\n2,4,30,B,1,beta\n3,7,20,A,1,gamma\n4,8,40,C,1,delta\n5,10,50,B,1,epsilon\n").encode("utf-8"),
        dataset_id=dataset["dataset_id"],
    )
    assert changed["version"] == 2
    assert analyses.get(analysis["id"])["status"] == "stale"
    rerun = analyses.run(analysis["id"])
    assert rerun["dataset_version"] == 2 and rerun["id"] != old["id"]
    assert analyses.get_result(analysis["id"], old["id"])["dataset_version"] == 1


def test_analysis_result_table_chart_and_docx_export(tmp_path: Path, monkeypatch):
    settings, _, analyses, dataset = _services(tmp_path)
    monkeypatch.setattr(analysis_blocks, "settings", settings)
    task_dir = settings.output_dir / TASK_ID
    draft_service = DraftService(TASK_ID, task_dir)
    draft = draft_service.build({
        "title": "统计分析导出验证", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1000, "reference_style": "gb7714", "abstract": "验证。", "keywords": ["统计"], "references": [],
    })
    section = _leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]
    draft_service.save(draft)
    descriptive = _create(analyses, dataset, "descriptive", {"columns": ["x", "category"]})
    descriptive_result = analyses.run(descriptive["id"])
    table_insert = insert_analysis_result(task_id=TASK_ID, analysis=analyses.get(descriptive["id"]), result=descriptive_result, section_id=section["id"], artifact="table")
    assert table_insert["blocks"] and table_insert["blocks"][0]["analysis"]["analysis_result_id"] == descriptive_result["id"]
    correlation = _create(analyses, dataset, "pearson", {"x": "x", "y": "y"})
    correlation_result = analyses.run(correlation["id"])
    chart_insert = insert_analysis_result(task_id=TASK_ID, analysis=analyses.get(correlation["id"]), result=correlation_result, section_id=section["id"], artifact="chart")
    assert chart_insert["block"]["chart_spec"]["kind"] == "scatter"
    draft_service.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        names = document.namelist()
        xml = document.read("word/document.xml")
    assert any(name.startswith("word/media/") for name in names)
    assert b"w:tbl" in xml
