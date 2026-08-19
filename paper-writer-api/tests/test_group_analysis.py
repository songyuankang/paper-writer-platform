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

TASK_ID = "c" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def _services(tmp_path: Path, rows: str) -> tuple[Settings, DatasetService, AnalysisService, dict]:
    settings = _settings(tmp_path)
    datasets = DatasetService(settings)
    dataset = datasets.import_data(filename="groups.csv", raw=("group,value,label\n" + rows).encode("utf-8"), name="组间样本", task_id=TASK_ID)
    return settings, datasets, AnalysisService(settings), dataset


def _create(service: AnalysisService, dataset: dict, kind: str) -> dict:
    return service.create(task_id=TASK_ID, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type=kind, variables={"group_column": "group", "value_column": "value"})


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def test_student_t_missing_values_cohens_d_and_group_validation(tmp_path: Path):
    rows = "A,10,a\nA,11,a\nA,12,a\nA,13,a\nB,15,b\nB,16,b\nB,17,b\nB,,b\n"
    _, _, analyses, dataset = _services(tmp_path, rows)
    result = analyses.run(_create(analyses, dataset, "independent_t")["id"])
    assert result["status"] == "ready" and result["result"]["method"] == "student_t"
    assert result["result"]["n_a"] == 4 and result["result"]["n_b"] == 3
    assert result["result"]["effect_size_type"] == "cohens_d" and math.isfinite(result["result"]["effect_size"])
    bad = _services(tmp_path / "bad", "A,1,a\nA,2,a\nB,3,b\nB,4,b\nC,5,c\nC,6,c\n")
    failed = bad[2].run(_create(bad[2], bad[3], "independent_t")["id"])
    assert failed["status"] == "failed" and "恰好两个" in failed["warnings"][0]


def test_welch_t_and_invalid_group_data_are_structured(tmp_path: Path):
    rows = "A,9,a\nA,10,a\nA,10,a\nA,11,a\nA,10,a\nA,9,a\nB,2,b\nB,20,b\nB,40,b\nB,60,b\nB,80,b\nB,100,b\n"
    _, _, analyses, dataset = _services(tmp_path, rows)
    result = analyses.run(_create(analyses, dataset, "independent_t")["id"])
    assert result["status"] == "ready" and result["result"]["method"] == "welch_t"
    constant = _services(tmp_path / "constant", "A,1,a\nA,1,a\nB,2,b\nB,3,b\n")
    failed = constant[2].run(_create(constant[2], constant[3], "independent_t")["id"])
    assert failed["status"] == "failed" and "常数组" in failed["warnings"][0]
    non_numeric = _services(tmp_path / "text", "A,x,a\nA,y,a\nB,z,b\nB,q,b\n")
    failed_text = non_numeric[2].run(_create(non_numeric[2], non_numeric[3], "independent_t")["id"])
    assert failed_text["status"] == "failed" and "数值变量" in failed_text["warnings"][0]


def test_anova_eta_tukey_stale_and_rerun(tmp_path: Path):
    rows = "A,1,a\nA,2,a\nA,3,a\nB,10,b\nB,11,b\nB,12,b\nC,20,c\nC,21,c\nC,22,c\n"
    _, datasets, analyses, dataset = _services(tmp_path, rows)
    analysis = _create(analyses, dataset, "anova")
    result = analyses.run(analysis["id"])
    assert result["status"] == "ready" and result["result"]["method"] == "anova"
    assert result["result"]["eta_squared"] > .9 and len(result["result"]["tukey_hsd"]) == 3
    changed = datasets.import_data(filename="groups.csv", raw=("group,value,label\n" + rows + "C,23,c\n").encode("utf-8"), dataset_id=dataset["dataset_id"])
    assert changed["version"] == 2 and analyses.get(analysis["id"])["status"] == "stale"
    rerun = analyses.run(analysis["id"])
    assert rerun["dataset_version"] == 2 and rerun["id"] != result["id"]


def test_group_analysis_table_boxplot_and_docx(tmp_path: Path, monkeypatch):
    rows = "A,1,a\nA,2,a\nA,3,a\nB,10,b\nB,11,b\nB,12,b\nC,20,c\nC,21,c\nC,22,c\n"
    settings, _, analyses, dataset = _services(tmp_path, rows)
    monkeypatch.setattr(analysis_blocks, "settings", settings)
    task_dir = settings.output_dir / TASK_ID
    draft_service = DraftService(TASK_ID, task_dir)
    draft = draft_service.build({"title": "组间统计验证", "major": "管理学", "paper_type": "课程论文", "word_count": 1000, "reference_style": "gb7714", "abstract": "验证。", "keywords": ["ANOVA"], "references": []})
    section = _leaf(draft); section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]; draft_service.save(draft)
    analysis = _create(analyses, dataset, "anova")
    result = analyses.run(analysis["id"])
    table = insert_analysis_result(task_id=TASK_ID, analysis=analyses.get(analysis["id"]), result=result, section_id=section["id"], artifact="table")
    chart = insert_analysis_result(task_id=TASK_ID, analysis=analyses.get(analysis["id"]), result=result, section_id=section["id"], artifact="chart")
    assert len(table["blocks"]) >= 2 and chart["block"]["chart_spec"]["kind"] == "boxplot"
    draft_service.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        assert any(name.startswith("word/media/") for name in document.namelist())
        assert b"w:tbl" in document.read("word/document.xml")
