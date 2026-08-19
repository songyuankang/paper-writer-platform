from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
sys.path.insert(0, str(PROJECT_API))

from app.formatter import service as formatter_service
from app.services import chart_service


def main() -> None:
    task_dir = PROJECT_API / "_chart_export_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    paper = {
        "title": "图表导出链路验证",
        "major": "管理学·工商管理类",
        "paper_type": "课程论文",
        "word_count": 1000,
        "reference_style": "gb7714",
        "chart_enabled": True,
        "chart_config": {
            "enabled": True,
            "count": 2,
            "types": ["bar", "line"],
        },
    }
    spec = {
        "meta": {
            "title": paper["title"],
            "abstract": "用于验证 DOCX 图表嵌入链路的本地测试。",
            "keywords": ["图表", "验证"],
            "reference_style": "gb7714",
            "citation_style": "numeric",
        },
        "sections": [
            {"type": "h1", "text": "第一章 验证正文"},
            {"type": "p", "text": "该段用于验证图表将被注入到 Word 正文。"},
            {"type": "references", "items": []},
        ],
        "references": [],
    }

    charts = chart_service.generate_charts(
        task_dir,
        major=paper["major"],
        enabled=True,
        count=2,
        types=["bar", "line"],
    )
    files = formatter_service.format_paper(
        "chart-export-verification",
        task_dir,
        paper,
        spec,
        charts=charts,
    )

    docx_candidates = list(task_dir.rglob("*.docx"))
    if not docx_candidates:
        raise RuntimeError(f"未生成 DOCX，输出文件：{files}")
    docx_path = docx_candidates[0]
    with zipfile.ZipFile(docx_path) as archive:
        embedded = [name for name in archive.namelist() if name.startswith("word/media/")]
    if len(embedded) < 2:
        raise RuntimeError(f"DOCX 未嵌入预期图表：{embedded}")

    print(f"DOCX={docx_path}")
    print(f"CHARTS={len(charts)}")
    print(f"EMBEDDED_MEDIA={len(embedded)}")
    shutil.rmtree(task_dir)


if __name__ == "__main__":
    main()
