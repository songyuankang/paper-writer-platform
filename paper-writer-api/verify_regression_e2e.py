"""Phase 4C real XLSX → OLS → native tables/charts → DOCX verification."""
from __future__ import annotations
import io, json, shutil, zipfile
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


def source_bytes() -> bytes:
    workbook = openpyxl.Workbook(); sheet = workbook.active; sheet.title = "回归数据"
    sheet.append(["满意度", "年龄", "收入", "备注"])
    for index, (age, income, noise) in enumerate([(20,4,.2),(22,5,-.1),(25,6,.3),(27,5,-.2),(30,8,.1),(32,7,.2),(35,10,-.2),(37,9,.15),(40,12,-.1),(42,11,.25),(45,14,-.2),(47,13,.1)]):
        sheet.append([20 + 1.1 * age + 2.4 * income + noise, age, income, f"样本{index + 1}"])
    workbook.create_sheet("说明").append(["字段", "说明"])
    stream = io.BytesIO(); workbook.save(stream); return stream.getvalue()


def main() -> None:
    root = Path(__file__).resolve().parent / "verification_regression_e2e"
    if root.exists(): shutil.rmtree(root)
    settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
    analysis_blocks.settings = settings
    task_id = "f" * 32; datasets, analyses = DatasetService(settings), AnalysisService(settings)
    staged = datasets.stage_upload("回归调查.xlsx", source_bytes())
    dataset = datasets.import_staged(staged["import_token"], filename=staged["filename"], name="回归调查", sheet="回归数据", task_id=task_id)
    task_dir = settings.output_dir / task_id; drafts = DraftService(task_id, task_dir)
    draft = drafts.build({"title": "线性回归 E2E 验收", "major": "管理学", "paper_type": "课程论文", "word_count": 1000, "reference_style": "gb7714", "abstract": "真实回归链路验证。", "keywords": ["线性回归"], "references": []})
    section = leaf(draft); section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]; drafts.save(draft)
    analysis = analyses.create(task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1, analysis_type="regression", variables={"dependent_variable": "满意度", "predictors": ["年龄", "收入"]}, parameters={"alpha": .05})
    result = analyses.run(analysis["id"]); assert result["status"] == "ready" and result["result"]["n"] == 12
    current = analyses.get(analysis["id"])
    table = insert_analysis_result(task_id=task_id, analysis=current, result=result, section_id=section["id"], artifact="table")
    charts = [insert_analysis_result(task_id=task_id, analysis=current, result=result, section_id=section["id"], artifact=kind)["block"] for kind in ["actual_predicted", "residual", "coefficient"]]
    assert len(table["blocks"]) == 2 and len(charts) == 3
    drafts.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        names = document.namelist(); xml = document.read("word/document.xml")
    assert sum(name.startswith("word/media/") for name in names) >= 3 and b"w:tbl" in xml
    print(json.dumps({"dataset_id": dataset["dataset_id"], "dataset_version": 1, "fingerprint": result["data_fingerprint"], "n": result["result"]["n"], "r_squared": result["result"]["r_squared"], "vif": result["result"]["vif"], "charts": [item["chart_spec"]["binding"]["regression_chart_type"] for item in charts], "docx": str(task_dir / "论文.docx"), "media": [name for name in names if name.startswith("word/media/")]}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
