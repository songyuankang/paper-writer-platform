from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.draft.chart_blocks import (
    ChartCreateRequest,
    ChartSpecUpdateRequest,
    create_chart_block,
    update_chart_spec_block,
)
from app.draft.service import DraftService
from app.services.cross_reference_service import CrossReferenceService
from app.services.research_object_service import ResearchObjectService


TASK = "b" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def _draft() -> dict:
    return {
        "title": "正文图表编辑测试",
        "meta": {"major": "计算机", "paper_type": "课程论文", "word_count": 500, "reference_style": "gb7714", "keywords": []},
        "abstract": {"zh": "摘要", "en": ""},
        "keywords": {"zh": [], "en": []},
        "acknowledgement": "",
        "references": [],
        "sections": [{
            "id": "1-1", "number": "1.1", "title": "实验结果", "level": 3, "gist": "",
            "paragraphs": [
                {"id": "p_text", "text": "模型效果如图所示。"},
                {"id": "table_metrics", "type": "table", "title": "模型指标", "headers": ["模型", "准确率"], "rows": [["YOLOv5", "92.1"], ["YOLOv8", "95.3"]]},
            ],
        }],
    }


def test_body_chart_spec_edit_persists_asset_cross_reference_and_docx(tmp_path: Path):
    settings = _settings(tmp_path)
    task_dir = settings.output_dir / TASK
    service = DraftService(TASK, task_dir)
    service.save(_draft())

    draft = service.load()
    section = draft["sections"][0]
    chart = create_chart_block(service, section["id"], ChartCreateRequest(title_hint="模型准确率比较"))
    objects = ResearchObjectService(settings)
    objects.renumber_document_references(TASK)
    chart = next(item for item in service.load()["sections"][0]["paragraphs"] if item.get("id") == chart["id"])
    original_number = chart["figure_number"]
    original_asset = chart["asset"]["png_path"]
    figure_object = next(item for item in objects.list(TASK) if item["source_id"] == chart["id"])
    reference = CrossReferenceService(settings).insert(task_id=TASK, section_id="1-1", target_object_id=figure_object["id"])

    edited_spec = json.loads(json.dumps(chart["chart_spec"]))
    edited_spec["title"] = "模型准确率比较（修订）"
    edited_spec["caption"] = "基于正文内编辑的数据。"
    edited_spec["kind"] = "line"
    edited_spec["data"]["categories"] = ["YOLOv5", "YOLOv8"]
    edited_spec["data"]["series"] = [{"name": "准确率", "values": [92.1, 96.0], "axis": "left"}]

    updated = update_chart_spec_block(service, chart["id"], ChartSpecUpdateRequest(chart_spec=edited_spec))
    assert updated["figure_number"] == original_number
    assert updated["chart_spec"]["data"]["series"][0]["values"] == [92.1, 96.0]
    assert updated["chart_spec"]["kind"] == "line"
    assert updated["asset"]["png_path"] != original_asset
    assert (task_dir / updated["asset"]["png_path"]).is_file()
    assert (task_dir / updated["asset"]["svg_path"]).is_file()

    reopened = DraftService(TASK, task_dir).load()
    reopened_chart = next(item for item in reopened["sections"][0]["paragraphs"] if item.get("id") == chart["id"])
    assert reopened_chart["chart_spec"]["data"]["series"][0]["values"][1] == 96.0
    stored_reference = next(item for item in CrossReferenceService(settings).list(TASK) if item["id"] == reference["reference"]["id"])
    assert stored_reference["target_object_id"] == figure_object["id"]

    files = service.export()
    docx = next(Path(path) for path in files if str(path).endswith(".docx"))
    if not docx.is_absolute():
        docx = task_dir / docx
    with zipfile.ZipFile(docx) as document:
        assert any(name.startswith("word/media/") for name in document.namelist())


def test_body_chart_spec_editor_rejects_provenance_and_invalid_numbers(tmp_path: Path):
    settings = _settings(tmp_path)
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save(_draft())
    chart = create_chart_block(service, "1-1", ChartCreateRequest(title_hint="模型准确率比较"))
    raw = json.loads(json.dumps(chart["chart_spec"]))
    raw["provenance"] = {"status": "forged"}
    with pytest.raises(ValueError, match="来源追踪"):
        update_chart_spec_block(service, chart["id"], ChartSpecUpdateRequest(chart_spec=raw))

    raw = json.loads(json.dumps(chart["chart_spec"]))
    raw["data"]["series"][0]["values"][0] = "96"
    with pytest.raises(ValueError, match="有限数值"):
        update_chart_spec_block(service, chart["id"], ChartSpecUpdateRequest(chart_spec=raw))
