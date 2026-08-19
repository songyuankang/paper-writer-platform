"""Phase 4B real XLSX → t/ANOVA → native tables/boxplots → DOCX verification."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import openpyxl

from app.config import Settings
from app.draft import analysis_blocks
from app.draft.analysis_blocks import insert_analysis_result
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService


def leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "组间数据"
    sheet.append(["t组别", "ANOVA组别", "得分"])
    for t_group, a_group, score in [
        ("实验组", "低", 62), ("实验组", "低", 65), ("实验组", "低", 68),
        ("实验组", "中", 72), ("实验组", "中", 74), ("实验组", "中", 76),
        ("对照组", "高", 85), ("对照组", "高", 88), ("对照组", "高", 91),
    ]:
        sheet.append([t_group, a_group, score])
    notes = workbook.create_sheet("说明")
    notes.append(["字段", "说明"])
    notes.append(["得分", "测试得分"])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def main() -> None:
    root = Path(__file__).resolve().parent / "verification_group_analysis_e2e"
    if root.exists():
        shutil.rmtree(root)
    settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
    analysis_blocks.settings = settings
    task_id = "d" * 32
    datasets, analyses = DatasetService(settings), AnalysisService(settings)
    staged = datasets.stage_upload("组间分析.xlsx", workbook_bytes())
    dataset = datasets.import_staged(staged["import_token"], filename=staged["filename"], name="组间分析样本", sheet="组间数据", task_id=task_id)
    assert dataset["row_count"] == 9

    task_dir = settings.output_dir / task_id
    drafts = DraftService(task_id, task_dir)
    draft = drafts.build({"title": "组间分析 E2E 验收", "major": "管理学", "paper_type": "课程论文", "word_count": 1000, "reference_style": "gb7714", "abstract": "真实链路验证。", "keywords": ["组间差异"], "references": []})
    section = leaf(draft); section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文内容。"}]; drafts.save(draft)

    t_analysis = analyses.create(task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="independent_t", variables={"group_column": "t组别", "value_column": "得分"})
    t_result = analyses.run(t_analysis["id"])
    assert t_result["status"] == "ready"
    t_table = insert_analysis_result(task_id=task_id, analysis=analyses.get(t_analysis["id"]), result=t_result, section_id=section["id"], artifact="table")
    t_chart = insert_analysis_result(task_id=task_id, analysis=analyses.get(t_analysis["id"]), result=t_result, section_id=section["id"], artifact="chart")
    assert t_table["blocks"] and t_chart["block"]["chart_spec"]["kind"] == "boxplot"

    anova = analyses.create(task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="anova", variables={"group_column": "ANOVA组别", "value_column": "得分"})
    anova_result = analyses.run(anova["id"])
    assert anova_result["status"] == "ready" and anova_result["result"]["tukey_hsd"]
    anova_table = insert_analysis_result(task_id=task_id, analysis=analyses.get(anova["id"]), result=anova_result, section_id=section["id"], artifact="table")
    anova_chart = insert_analysis_result(task_id=task_id, analysis=analyses.get(anova["id"]), result=anova_result, section_id=section["id"], artifact="chart")
    assert len(anova_table["blocks"]) >= 3 and anova_chart["block"]["chart_spec"]["kind"] == "boxplot"
    drafts.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        names = document.namelist(); xml = document.read("word/document.xml")
    assert sum(name.startswith("word/media/") for name in names) >= 2 and b"w:tbl" in xml
    print(json.dumps({"dataset_id": dataset["dataset_id"], "sheet": dataset["source"]["sheet"], "t_method": t_result["result"]["method"], "anova_f": anova_result["result"]["f_statistic"], "tukey_rows": len(anova_result["result"]["tukey_hsd"]), "docx": str(task_dir / "论文.docx"), "media": [name for name in names if name.startswith("word/media/")]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
