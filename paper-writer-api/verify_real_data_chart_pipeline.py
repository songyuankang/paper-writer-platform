from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
sys.path.insert(0, str(PROJECT_API))

from app.formatter import service as formatter_service
from app.models.generate import ChartConfig, GenerateRequest
from app.services import data_chart_service, quality_service


def main() -> None:
    task_dir = PROJECT_API / "_real_chart_pipeline_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    (task_dir / "chart_data").mkdir(parents=True)

    fixture = (
        "年份,数字化投入指数,组织敏捷性得分\n"
        "2021,41,56\n"
        "2022,53,61\n"
        "2023,67,72\n"
        "2024,76,79\n"
    ).encode("utf-8")
    profile = data_chart_service.profile_dataset("fixture.csv", fixture)
    assert profile["row_count"] == 4
    assert {item["name"] for item in profile["columns"]} == {"年份", "数字化投入指数", "组织敏捷性得分"}
    data_file = task_dir / "chart_data" / "fixture.csv"
    data_file.write_bytes(fixture)

    config = {
        "enabled": True,
        "count": 2,
        "types": ["bar", "line"],
        "data_origin": "real",
        "data_file": "chart_data/fixture.csv",
        "x_column": "年份",
        "y_columns": ["数字化投入指数", "组织敏捷性得分"],
        "source_note": "测试夹具数据，仅用于验证真实数据图表处理链路，不构成研究结论。",
        "source_url": "https://example.test/dataset",
        "chart_title": "数字化投入与组织敏捷性趋势",
    }
    charts = data_chart_service.generate_real_charts(task_dir, "管理学·工商管理类", config)
    assert len(charts) == 2
    assert all(item["data_origin"] == "real" for item in charts)
    assert all(item["export_ready"] for item in charts)
    assert all((task_dir / "charts" / item["file"]).is_file() for item in charts)

    spec = {
        "meta": {
            "title": "真实数据图表管线验证",
            "abstract": "验证真实数据图表导出。",
            "keywords": ["真实数据", "图表"],
            "reference_style": "gb7714",
            "citation_style": "numeric",
        },
        "sections": [
            {"type": "h1", "text": "第一章 验证正文"},
            {"type": "p", "text": "以下图表应来自任务目录中的 CSV 数据文件。"},
            {"type": "references", "items": []},
        ],
        "references": [],
    }
    paper = {
        "title": "真实数据图表管线验证",
        "major": "管理学·工商管理类",
        "paper_type": "课程论文",
        "word_count": 1000,
        "reference_style": "gb7714",
        "chart_enabled": True,
        "chart_config": config,
    }
    formatter_service.format_paper("real-chart-pipeline", task_dir, paper, spec, charts=charts)
    docx = task_dir / "论文.docx"
    assert docx.is_file()
    with zipfile.ZipFile(docx) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert len(media) >= 2, media
    assert "测试夹具数据" in document_xml

    request = GenerateRequest(
        title=paper["title"], major=paper["major"], paper_type=paper["paper_type"],
        word_count=1000, chart_enabled=True, chart_config=ChartConfig(**config),
    )
    report = quality_service.build_quality_report(task_dir, request, charts)
    assert report["formal_export_ready"], json.dumps(report, ensure_ascii=False)
    print(f"PROFILE_ROWS={profile['row_count']}")
    print(f"CHARTS={len(charts)}")
    print(f"EMBEDDED_MEDIA={len(media)}")
    print(f"FORMAL_EXPORT_READY={report['formal_export_ready']}")
    shutil.rmtree(task_dir)


if __name__ == "__main__":
    main()
