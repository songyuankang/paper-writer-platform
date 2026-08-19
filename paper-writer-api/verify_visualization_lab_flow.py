"""Exercise the same service sequence used by Visualization Lab and DOCX export."""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_API))

from app.draft import block_service
from app.draft.chart_runtime import (
    create_lab_chart,
    insert_chart_into_section,
    recompute_chart_block,
    update_chart_configuration,
)
from app.draft.service import DraftService


def leaf(draft: dict) -> dict:
    parents = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in parents)


def main() -> None:
    task_dir = PROJECT_API / "_visualization_lab_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)
    service = DraftService("visualization-lab-verification", task_dir)
    draft = service.build({
        "title": "Visualization Lab 完整流程验证", "major": "管理学", "paper_type": "课程论文",
        "word_count": 1000, "reference_style": "gb7714", "abstract": "验证。", "keywords": ["图表", "Lab"], "references": [],
    })
    section = leaf(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "正文。"}]
    service.save(draft)

    # 打开论文 → 选择 TableBlock。
    table = block_service.add_table(service, section["id"], "区域销售数据", ["年份", "区域", "系列", "销售额", "满意度"], [
        ["2022", "华北", "线上", "80", "75"], ["2022", "华北", "线下", "60", "70"],
        ["2023", "华南", "线上", "120", "84"], ["2023", "华南", "线下", "90", "78"],
        ["2024", "华北", "线上", "150", "89"], ["2024", "华北", "线下", "105", "82"],
    ])
    draft = service.load()

    # 打开 Lab → 选择数据表 → 创建图表库条目。
    chart = create_lab_chart(draft, task_dir, "chart_lab_e2e", table["id"], "区域销售与满意度", "bar")
    service.save(draft)

    # 修改 X/Y/Series、聚合、筛选、论文视觉模板并保存（服务端生成 ChartAsset）。
    chart = update_chart_configuration(draft, task_dir, chart["id"], {
        "kind": "combo",
        "binding": {
            "category_column": "区域", "measure_columns": ["销售额", "满意度"], "series_column": "系列",
            "aggregation": "sum", "filters": [{"column": "年份", "operator": ">=", "value": "2023"}],
        },
        "appearance": {"template": "cn_thesis", "legend": True, "grid": True, "value_labels": True},
    })
    service.save(draft)
    assert chart["chart_spec"]["binding"]["category_column"] == "区域"
    assert chart["chart_spec"]["binding"]["aggregation"] == "sum"
    assert chart["chart_spec"]["data"]["categories"] == ["华南", "华北"]
    assert (task_dir / chart["asset"]["svg_path"]).is_file()

    # 重新计算 → 插入论文 → DOCX 导出。
    recompute_chart_block(draft, task_dir, chart)
    inserted = insert_chart_into_section(draft, chart["id"], section["id"])
    assert inserted["in_paper"] is True
    service.save(draft)
    service.export()

    spec = json.loads((task_dir / "paper_spec.json").read_text(encoding="utf-8"))
    figures = [item for item in spec["sections"] if item.get("type") == "figure"]
    docx = task_dir / "论文.docx"
    with zipfile.ZipFile(docx) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert len(figures) == 1 and figures[0]["title"].startswith("图1 ")
    assert media
    print(f"DATASET={chart['chart_spec']['binding']['dataset_id']}@v{chart['chart_spec']['binding']['dataset_version']}")
    print(f"KIND={chart['chart_spec']['kind']}")
    print(f"FILTERED_ROWS={chart['chart_spec']['data']['row_count']}")
    print(f"ASSET={chart['asset']['svg_path']}")
    print(f"FIGURE={figures[0]['title']}")
    print(f"DOCX={docx}")
    print(f"EMBEDDED_MEDIA={len(media)}")


if __name__ == "__main__":
    main()
