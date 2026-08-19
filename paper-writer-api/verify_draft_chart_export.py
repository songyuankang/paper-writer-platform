"""End-to-end verification for the first chart refactor stage.

It intentionally uses the same public draft services as the UI:
TableBlock -> DatasetVersion -> ChartSpec -> PNG/SVG asset -> stale -> recompute
-> FigureBlock -> DOCX embedded media.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_API))

from app.draft import block_service
from app.draft.chart_blocks import ChartCreateRequest, ChartRegenerateRequest, create_chart_block, regenerate_chart_block
from app.draft.service import DraftService


def _leaf_section(draft: dict) -> dict:
    children = {item["id"].rsplit("-", 1)[0] for item in draft["sections"] if "-" in item["id"]}
    return next(item for item in draft["sections"] if item["id"] not in children)


def main() -> None:
    task_dir = PROJECT_API / "_draft_chart_export_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    paper = {
        "title": "表格到图表 DOCX 导出验证",
        "major": "管理学·工商管理类",
        "paper_type": "课程论文",
        "word_count": 1000,
        "reference_style": "gb7714",
        "abstract": "验证论文表格、数据集版本、图表资产与 DOCX 原生图片嵌入。",
        "keywords": ["表格", "图表", "导出"],
        "references": [],
    }
    service = DraftService("draft-chart-export-verification", task_dir)
    draft = service.build(paper)
    section = _leaf_section(draft)
    section["paragraphs"] = [{"id": f"{section['id']}-text", "text": "本节使用用户维护的年度指标表生成柱状图。"}]
    service.save(draft)

    table = block_service.add_table(
        service,
        section["id"],
        "数字化投入与组织敏捷性",
        ["年份", "数字化投入指数", "组织敏捷性得分"],
        [["2021", "41", "56"], ["2022", "53", "61"], ["2023", "67", "72"], ["2024", "76", "79"]],
    )
    chart = create_chart_block(service, section["id"], ChartCreateRequest(chart_kind="bar"))
    assert chart["source_ids"] == [table["id"]]
    assert chart["chart_spec"]["binding"]["source_table_id"] == table["id"]
    assert chart["chart_spec"]["binding"]["dataset_version"] == 1
    assert (task_dir / chart["asset"]["svg_path"]).is_file()
    assert (task_dir / chart["asset"]["png_path"]).is_file()

    # Editing the source table must invalidate the dependent chart before it is
    # recomputed, instead of silently exporting old values.
    block_service.update_block(service, table["id"], {
        "headers": table["headers"],
        "rows": [["2021", "42", "56"], ["2022", "55", "61"], ["2023", "69", "72"], ["2024", "80", "79"]],
    })
    stale = next(item for item in service.load()["sections"] for item in item["paragraphs"] if item.get("id") == chart["id"])
    assert stale["status"] == "stale", stale
    chart = regenerate_chart_block(service, chart["id"], ChartRegenerateRequest(chart_kind="bar"))
    assert chart["status"] == "ready"
    assert chart["chart_spec"]["binding"]["dataset_version"] == 2
    assert (task_dir / chart["asset"]["png_path"]).is_file()

    files = service.export()
    docx = task_dir / "论文.docx"
    if not docx.is_file():
        raise RuntimeError(f"未生成 DOCX，输出文件：{files}")
    spec = json.loads((task_dir / "paper_spec.json").read_text(encoding="utf-8"))
    figures = [item for item in spec["sections"] if item.get("type") == "figure"]
    assert len(figures) == 1, figures
    assert figures[0]["title"].startswith("图1 "), figures[0]
    assert figures[0]["path"] == chart["asset"]["png_path"]
    with zipfile.ZipFile(docx) as archive:
        embedded = [name for name in archive.namelist() if name.startswith("word/media/")]
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert embedded, "DOCX 没有嵌入图表媒体"
    assert "图1" in document_xml, "DOCX 缺少图号"

    print(f"DATASET={chart['chart_spec']['binding']['dataset_id']}@v{chart['chart_spec']['binding']['dataset_version']}")
    print(f"CHART={chart['id']}")
    print(f"SVG={chart['asset']['svg_path']}")
    print(f"PNG={chart['asset']['png_path']}")
    print(f"DOCX={docx}")
    print(f"FIGURE_BLOCKS={len(figures)}")
    print(f"EMBEDDED_MEDIA={len(embedded)}")


if __name__ == "__main__":
    main()
