from __future__ import annotations

from pathlib import Path

from app.draft import block_service
from app.draft.chart_runtime import (
    SUPPORTED_CHART_KINDS,
    adapt_insight_chart,
    create_lab_chart,
    dataset_profile,
    insert_chart_into_section,
    mark_charts_stale_for_table,
    materialize_chart_data,
    recompute_chart_block,
    update_chart_configuration,
)
from app.draft.service import DraftService


def _leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def _service_with_table(tmp_path: Path) -> tuple[DraftService, dict, dict]:
    service = DraftService("visualization-lab-test", tmp_path)
    draft = service.build({
        "title": "Visualization Lab 测试论文", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1200, "reference_style": "gb7714", "abstract": "测试。", "keywords": ["可视化"], "references": [],
    })
    section = _leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]
    service.save(draft)
    table = block_service.add_table(service, section["id"], "销售与满意度", ["年份", "区域", "组别", "销售额", "满意度"], [
        ["2022", "华北", "A", "100", "80"], ["2022", "华北", "B", "70", "74"],
        ["2023", "华南", "A", "120", "85"], ["2023", "华南", "B", "90", "78"],
        ["2024", "华北", "A", "140", "88"], ["2024", "华北", "B", "110", "82"],
    ])
    return service, section, table


def test_lab_binding_aggregation_filter_profile_and_recompute(tmp_path):
    service, section, table = _service_with_table(tmp_path)
    draft = service.load()
    chart = create_lab_chart(draft, service.task_dir, "chart_lab_1", table["id"], "区域销售分析", "bar")
    service.save(draft)

    updated = update_chart_configuration(service.load(), service.task_dir, chart["id"], {
        "kind": "combo",
        "binding": {
            "category_column": "区域", "measure_columns": ["销售额", "满意度"], "series_column": "组别",
            "aggregation": "sum", "filters": [{"column": "年份", "operator": ">=", "value": "2023"}],
        },
        "appearance": {"template": "cn_thesis", "value_labels": True},
    })
    assert updated["chart_spec"]["binding"]["category_column"] == "区域"
    assert updated["chart_spec"]["binding"]["aggregation"] == "sum"
    assert updated["chart_spec"]["binding"]["filters"][0]["operator"] == ">="
    assert updated["chart_spec"]["data"]["categories"] == ["华南", "华北"]
    assert updated["chart_spec"]["appearance"]["template"] == "cn_thesis"
    assert (tmp_path / updated["asset"]["svg_path"]).is_file()
    assert (tmp_path / updated["asset"]["png_path"]).is_file()

    dataset = next(item for item in service.load()["datasets"] if item["source_table_id"] == table["id"])
    profile = dataset_profile(dataset, limit=2, offset=0)
    assert profile["limit"] == 2 and profile["has_more"] is True
    assert next(field for field in profile["fields"] if field["name"] == "销售额")["statistics"]["avg"] > 0

    block_service.update_block(service, table["id"], {"headers": table["headers"], "rows": table["rows"] + [["2025", "华南", "A", "160", "90"]]})
    draft = service.load()
    assert mark_charts_stale_for_table(draft, table["id"]) == [chart["id"]]
    _, stored_chart, _ = __import__("app.draft.chart_runtime", fromlist=["locate_chart"]).locate_chart(draft, chart["id"])
    assert stored_chart["status"] == "stale"
    recompute_chart_block(draft, service.task_dir, stored_chart)
    assert stored_chart["status"] == "ready"
    assert stored_chart["chart_spec"]["binding"]["dataset_version"] >= 2


def test_lab_aggregations_and_all_renderer_kinds(tmp_path):
    service, section, table = _service_with_table(tmp_path)
    draft = service.load()
    chart = create_lab_chart(draft, service.task_dir, "chart_lab_kinds", table["id"], "渲染验证", "bar")
    dataset = next(item for item in draft["datasets"] if item["source_table_id"] == table["id"])
    for aggregation in ("count", "sum", "avg", "median", "min", "max"):
        data = materialize_chart_data(dataset, {
            "category_column": "区域", "measure_columns": ["销售额"], "series_column": None,
            "aggregation": aggregation, "filters": [],
        })
        assert data["categories"]
        assert data["series"][0]["values"]
    for kind in SUPPORTED_CHART_KINDS:
        result = update_chart_configuration(draft, service.task_dir, chart["id"], {
            "kind": kind,
            "binding": {"category_column": "年份", "measure_columns": ["销售额", "满意度"], "aggregation": "none", "filters": []},
            "appearance": {"template": "clean_report"},
        })
        assert result["chart_spec"]["kind"] == kind
        assert (tmp_path / result["asset"]["svg_path"]).is_file()
        assert (tmp_path / result["asset"]["png_path"]).is_file()


def test_insight_adapter_and_insert_into_paper(tmp_path):
    service, section, table = _service_with_table(tmp_path)
    draft = service.load()
    draft_section = _leaf(draft)
    insight = {
        "id": "insight_chart_1", "type": "insight", "kind": "chart", "title": "旧洞察图表", "caption": "适配测试",
        "source_status": "user_data", "chart": {"kind": "line", "source_table_id": table["id"], "categories": ["2022", "2023"], "series": [{"name": "销售额", "values": [170, 210]}]},
    }
    draft_section["paragraphs"].append(insight)
    service.save(draft)
    adapted = adapt_insight_chart(draft, service.task_dir, insight["id"])
    assert adapted["type"] == "chart"
    assert adapted["chart_spec"]["schema_version"] == 2
    assert adapted["asset"]["png_path"].endswith(".png")

    library_chart = create_lab_chart(draft, service.task_dir, "chart_insert_1", table["id"], "待插入", "line")
    inserted = insert_chart_into_section(draft, library_chart["id"], draft_section["id"])
    assert inserted["in_paper"] is True
    assert any(block["id"] == library_chart["id"] for block in draft_section["paragraphs"])
