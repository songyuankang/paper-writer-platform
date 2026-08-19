from __future__ import annotations

import json
import zipfile

from app.draft import block_service
from app.draft.chart_blocks import (
    ChartCreateRequest,
    ChartRegenerateRequest,
    create_chart_block,
    regenerate_chart_block,
)
from app.draft.service import DraftService


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def test_table_chart_pipeline_exports_native_figure(tmp_path):
    service = DraftService("chart-pipeline-test", tmp_path)
    draft = service.build({
        "title": "图表测试论文",
        "major": "管理学",
        "paper_type": "课程论文",
        "word_count": 1000,
        "reference_style": "gb7714",
        "abstract": "图表测试。",
        "keywords": ["图表"],
        "references": [],
    })
    section = _leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "测试正文。"}]
    service.save(draft)

    table = block_service.add_table(
        service,
        section["id"],
        "年度指标",
        ["年份", "投入", "得分"],
        [["2021", "40", "55"], ["2022", "52", "63"], ["2023", "68", "76"]],
    )
    chart = create_chart_block(service, section["id"], ChartCreateRequest(chart_kind="line"))
    assert chart["chart_spec"]["binding"]["source_table_id"] == table["id"]
    assert chart["source_ids"] == [table["id"]]
    assert (tmp_path / chart["asset"]["svg_path"]).is_file()
    assert (tmp_path / chart["asset"]["png_path"]).is_file()

    block_service.update_block(service, table["id"], {
        "headers": table["headers"],
        "rows": [["2021", "42", "57"], ["2022", "56", "66"], ["2023", "72", "80"]],
    })
    stored = service.load()
    stale = next(block for item in stored["sections"] for block in item["paragraphs"] if block.get("id") == chart["id"])
    assert stale["status"] == "stale"

    recalculated = regenerate_chart_block(service, chart["id"], ChartRegenerateRequest(chart_kind="line"))
    assert recalculated["status"] == "ready"
    assert recalculated["chart_spec"]["binding"]["dataset_version"] == 2

    service.export()
    spec = json.loads((tmp_path / "paper_spec.json").read_text(encoding="utf-8"))
    figures = [item for item in spec["sections"] if item.get("type") == "figure"]
    assert len(figures) == 1
    assert figures[0]["title"].startswith("图1 ")
    with zipfile.ZipFile(tmp_path / "论文.docx") as archive:
        assert any(name.startswith("word/media/") for name in archive.namelist())
