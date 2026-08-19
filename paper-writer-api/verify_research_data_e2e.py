"""Phase 3 real XLSX → Dataset → Lab → FigureBlock → DOCX verification."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import openpyxl

from app.config import Settings
from app.draft.chart_runtime import (
    create_lab_chart_from_dataset,
    external_dataset_version,
    insert_chart_into_section,
    recompute_chart_block,
    update_chart_configuration,
)
from app.draft.service import DraftService
from app.services.dataset_service import DatasetService


def leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "调查数据"
    sheet.append(["年份", "区域", "渠道", "销售额", "满意度"])
    sheet.append([2022, "华北", "线上", 100, 80])
    sheet.append([2022, "华北", "线下", 70, 74])
    sheet.append([2023, "华南", "线上", 120, 85])
    sheet.append([2023, "华南", "线下", 90, 78])
    notes = workbook.create_sheet("说明")
    notes.append(["字段", "释义"])
    notes.append(["销售额", "万元"])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def main() -> None:
    root = Path(__file__).resolve().parent / "verification_research_data_e2e"
    if root.exists():
        shutil.rmtree(root)
    settings = Settings(
        db_path=root / "data" / "history.db",
        output_dir=root / "outputs",
        upload_dir=root / "uploads",
        log_dir=root / "logs",
    )
    dataset_service = DatasetService(settings)
    task_id = "e" * 32

    # 1. XLSX upload followed by explicit worksheet selection.
    staged = dataset_service.stage_upload("真实调查数据.xlsx", workbook_bytes())
    assert staged["requires_sheet_selection"] and staged["sheets"] == ["调查数据", "说明"]
    imported = dataset_service.import_staged(
        staged["import_token"], filename=staged["filename"], name="真实调查数据",
        sheet="调查数据", task_id=task_id,
    )
    assert imported["version"] == 1 and imported["quality"]["sample_size"] == 4
    assert next(column for column in imported["schema"] if column["name"] == "销售额")["type"] == "numeric"

    # 2. Create a Lab chart from the file-backed DatasetVersion and change bindings.
    task_dir = settings.output_dir / task_id
    draft_service = DraftService(task_id, task_dir)
    draft = draft_service.build({
        "title": "研究数据中心 E2E 验收", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1000, "reference_style": "gb7714", "abstract": "真实链路验证。",
        "keywords": ["研究数据"], "references": [],
    })
    section = leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文内容。"}]
    external = external_dataset_version(dataset_service.get_version(imported["dataset_id"], 1, include_rows=True))
    chart = create_lab_chart_from_dataset(draft, task_dir, "chart_research_e2e", external, "区域销售与满意度", "bar")
    assert chart["chart_spec"]["binding"]["source_type"] == "research_dataset"
    assert chart["source_ids"] == [] and not draft.get("datasets")

    loader = lambda dataset_id, version: dataset_service.get_version(dataset_id, version, include_rows=True)
    configured = update_chart_configuration(draft, task_dir, chart["id"], {
        "kind": "combo",
        "binding": {
            "source_type": "research_dataset", "dataset_id": imported["dataset_id"], "dataset_version": 1,
            "category_column": "区域", "measure_columns": ["销售额", "满意度"], "series_column": "渠道",
            "aggregation": "sum", "filters": [{"column": "年份", "operator": ">=", "value": "2023"}],
        },
        "appearance": {"template": "cn_thesis", "legend": True, "value_labels": True},
    }, loader)
    assert configured["chart_spec"]["data"]["categories"] == ["华南"]
    assert (task_dir / configured["asset"]["svg_path"]).is_file()
    assert (task_dir / configured["asset"]["png_path"]).is_file()

    # 3. Recalculate, insert native FigureBlock, and verify DOCX embedded media.
    recompute_chart_block(draft, task_dir, configured, "combo", loader)
    inserted = insert_chart_into_section(draft, configured["id"], section["id"])
    assert inserted["in_paper"] is True and inserted["type"] == "chart"
    draft_service.save(draft)
    draft_service.export()
    spec = json.loads((task_dir / "paper_spec.json").read_text(encoding="utf-8"))
    figures = [item for item in spec["sections"] if item.get("type") == "figure"]
    with zipfile.ZipFile(task_dir / "论文.docx") as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert figures and figures[0]["title"].startswith("图1 ")
    assert media

    print(json.dumps({
        "dataset_id": imported["dataset_id"], "dataset_version": imported["version"],
        "sheet": imported["source"]["sheet"], "row_count": imported["row_count"],
        "chart_id": chart["id"], "chart_kind": configured["chart_spec"]["kind"],
        "figure_title": figures[0]["title"], "docx": str(task_dir / "论文.docx"),
        "embedded_media": media,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
