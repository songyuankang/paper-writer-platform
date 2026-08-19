from __future__ import annotations

import io
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def _workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "样本数据"
    sheet.append(["年份", "地区", "组别", "销售额", "满意度"])
    sheet.append([2022, "华北", "A", 100, 80])
    sheet.append([2023, "华南", "B", 120, 85])
    second = workbook.create_sheet("说明")
    second.append(["字段", "含义"])
    second.append(["销售额", "万元"])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_dataset_csv_profile_versions_and_paginated_preview(tmp_path: Path):
    service = DatasetService(_settings(tmp_path))
    raw = "年份,地区,销售额\n2022,华北,100\n2023,华南,120\n2023,华南,120\n2024,,140\n".encode("utf-8")

    first = service.import_data(filename="sales.csv", raw=raw, name="销售样本", task_id="a" * 32)
    assert first["version"] == 1
    assert first["schema"][2]["type"] == "numeric"
    assert first["quality"]["duplicate_rows"] == 1
    assert next(item for item in first["schema"] if item["name"] == "地区")["missing_count"] == 1

    page = service.preview(first["dataset_id"], 1, limit=2, offset=1)
    assert page["rows"][0]["年份"] == "2023"
    assert page["limit"] == 2 and page["has_more"] is True

    duplicate = service.import_data(filename="sales.csv", raw=raw, dataset_id=first["dataset_id"])
    assert duplicate["deduplicated"] is True
    assert duplicate["version"] == 1
    changed = service.import_data(
        filename="sales.csv",
        raw=raw.replace("2024,,140".encode("utf-8"), "2024,华东,150".encode("utf-8")),
        dataset_id=first["dataset_id"],
    )
    assert changed["version"] == 2
    assert len(service.versions(first["dataset_id"])) == 2


def test_xlsx_staging_requires_sheet_selection_and_preserves_filename(tmp_path: Path):
    service = DatasetService(_settings(tmp_path))
    staged = service.stage_upload("研究样本.xlsx", _workbook_bytes())
    assert staged["requires_sheet_selection"] is True
    assert staged["sheets"] == ["样本数据", "说明"]

    imported = service.import_staged(
        staged["import_token"],
        filename=staged["filename"],
        name="问卷样本",
        sheet="样本数据",
    )
    assert imported["source"]["filename"] == "研究样本.xlsx"
    assert imported["source"]["sheet"] == "样本数据"
    assert imported["row_count"] == 2
    assert next(item for item in imported["schema"] if item["name"] == "销售额")["type"] == "numeric"


def test_research_dataset_lab_chart_recompute_insert_and_docx_export(tmp_path: Path):
    settings = _settings(tmp_path)
    datasets = DatasetService(settings)
    imported = datasets.import_data(
        filename="lab.csv",
        raw="年份,地区,组别,销售额,满意度\n2022,华北,A,100,80\n2022,华北,B,70,74\n2023,华南,A,120,85\n2023,华南,B,90,78\n".encode("utf-8"),
        name="Lab 研究数据",
    )
    version = external_dataset_version(datasets.get_version(imported["dataset_id"], 1, include_rows=True))

    task_dir = tmp_path / "task"
    draft_service = DraftService("research-dataset-test", task_dir)
    draft = draft_service.build({
        "title": "研究数据集图表导出", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1000, "reference_style": "gb7714", "abstract": "测试。", "keywords": ["数据"], "references": [],
    })
    section = _leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]
    chart = create_lab_chart_from_dataset(draft, task_dir, "chart_research_1", version, "地区销售分析", "bar")
    assert chart["chart_spec"]["binding"]["source_type"] == "research_dataset"
    assert chart["source_ids"] == []
    assert draft.get("datasets", []) == []

    loader = lambda dataset_id, dataset_version: datasets.get_version(dataset_id, dataset_version, include_rows=True)
    updated = update_chart_configuration(draft, task_dir, chart["id"], {
        "kind": "combo",
        "binding": {
            "source_type": "research_dataset", "dataset_id": imported["dataset_id"], "dataset_version": 1,
            "category_column": "地区", "measure_columns": ["销售额", "满意度"], "series_column": "组别",
            "aggregation": "sum", "filters": [{"column": "年份", "operator": ">=", "value": "2023"}],
        },
        "appearance": {"template": "academic", "value_labels": True},
    }, loader)
    assert updated["chart_spec"]["data"]["categories"] == ["华南"]
    assert (task_dir / updated["asset"]["png_path"]).is_file()
    recompute_chart_block(draft, task_dir, updated, "combo", loader)
    assert updated["status"] == "ready"

    inserted = insert_chart_into_section(draft, chart["id"], section["id"])
    assert inserted["in_paper"] is True
    draft_service.save(draft)
    draft_service.export()
    with zipfile.ZipFile(task_dir / "论文.docx") as document:
        assert any(name.startswith("word/media/") for name in document.namelist())
