"""Phase 4A real XLSX → Analysis → native table/chart → DOCX verification."""
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
    sheet.title = "问卷数据"
    sheet.append(["年龄", "满意度", "收入", "学历"])
    sheet.append([20, 62, 4000, "本科"])
    sheet.append([24, 70, 5200, "本科"])
    sheet.append([28, 75, 6100, "硕士"])
    sheet.append([32, 84, 7600, "硕士"])
    sheet.append([36, 88, 8800, "博士"])
    sheet.append([40, 91, 9600, "博士"])
    notes = workbook.create_sheet("说明")
    notes.append(["字段", "说明"])
    notes.append(["满意度", "问卷得分"])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def main() -> None:
    root = Path(__file__).resolve().parent / "verification_research_analysis_e2e"
    if root.exists():
        shutil.rmtree(root)
    settings = Settings(
        db_path=root / "data" / "history.db",
        output_dir=root / "outputs",
        upload_dir=root / "uploads",
        log_dir=root / "logs",
    )
    analysis_blocks.settings = settings
    task_id = "b" * 32
    datasets = DatasetService(settings)
    analyses = AnalysisService(settings)

    staged = datasets.stage_upload("问卷调查.xlsx", workbook_bytes())
    assert staged["requires_sheet_selection"]
    dataset = datasets.import_staged(
        staged["import_token"], filename=staged["filename"], name="问卷调查",
        sheet="问卷数据", task_id=task_id,
    )
    assert dataset["version"] == 1 and dataset["row_count"] == 6

    task_dir = settings.output_dir / task_id
    draft_service = DraftService(task_id, task_dir)
    draft = draft_service.build({
        "title": "研究分析 E2E 验收", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1000, "reference_style": "gb7714", "abstract": "真实分析链路验证。",
        "keywords": ["统计分析"], "references": [],
    })
    section = leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文内容。"}]
    draft_service.save(draft)

    descriptive = analyses.create(
        task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1,
        analysis_type="descriptive", variables={"columns": ["年龄", "满意度", "学历"]},
        name="样本描述性统计",
    )
    descriptive_result = analyses.run(descriptive["id"])
    assert descriptive_result["status"] == "ready"
    table = insert_analysis_result(
        task_id=task_id, analysis=analyses.get(descriptive["id"]), result=descriptive_result,
        section_id=section["id"], artifact="table",
    )
    assert table["blocks"]

    pearson = analyses.create(
        task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1,
        analysis_type="pearson", variables={"x": "年龄", "y": "满意度"}, name="年龄与满意度 Pearson 相关",
    )
    pearson_result = analyses.run(pearson["id"])
    assert pearson_result["status"] == "ready" and pearson_result["result"]["n"] == 6
    chart = insert_analysis_result(
        task_id=task_id, analysis=analyses.get(pearson["id"]), result=pearson_result,
        section_id=section["id"], artifact="chart",
    )
    assert chart["block"]["chart_spec"]["kind"] == "scatter"

    draft_service.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        names = document.namelist()
        document_xml = document.read("word/document.xml")
    assert any(name.startswith("word/media/") for name in names)
    assert b"w:tbl" in document_xml
    print(json.dumps({
        "dataset_id": dataset["dataset_id"], "dataset_version": dataset["version"], "sheet": dataset["source"]["sheet"],
        "descriptive_result_id": descriptive_result["id"], "pearson_result_id": pearson_result["id"],
        "pearson_n": pearson_result["result"]["n"], "pearson_r": pearson_result["result"]["r"],
        "table_blocks": len(table["blocks"]), "chart": chart["block"]["title"],
        "docx": str(task_dir / "论文.docx"), "embedded_media": [name for name in names if name.startswith("word/media/")],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
