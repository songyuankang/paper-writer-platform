from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
sys.path.insert(0, str(PROJECT_API))

from app.draft.service import DraftService


def main() -> None:
    task_dir = PROJECT_API / "_draft_real_chart_export_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    (task_dir / "chart_data").mkdir(parents=True)
    (task_dir / "chart_data" / "dataset.csv").write_text(
        "年度,数字化能力,组织敏捷性\n2021,40,54\n2022,52,62\n2023,65,71\n",
        encoding="utf-8",
    )
    paper = {
        "title": "草稿模式真实图表验证",
        "major": "管理学·工商管理类",
        "paper_type": "课程论文",
        "word_count": 1000,
        "reference_style": "gb7714",
        "chart_enabled": True,
        "chart_config": {
            "enabled": True,
            "count": 1,
            "types": ["line"],
            "data_origin": "real",
            "data_file": "chart_data/dataset.csv",
            "x_column": "年度",
            "y_columns": ["数字化能力", "组织敏捷性"],
            "source_note": "测试数据集：草稿真实数据图表导出验证，不构成研究结论。",
            "chart_title": "数字化能力与组织敏捷性趋势",
        },
        "abstract": "用于验证草稿实际导出路径。",
        "keywords": ["真实数据", "图表"],
        "references": [],
    }
    service = DraftService("draft-real-chart-verification", task_dir)
    draft = service.build(paper)
    for section in draft["sections"]:
        if section.get("level") == 3:
            section["paragraphs"] = [{"id": f"{section['id']}-p", "text": "验证正文。"}]
    service.save(draft)
    service.export()
    docx = task_dir / "论文.docx"
    assert docx.is_file()
    with zipfile.ZipFile(docx) as archive:
        media = [item for item in archive.namelist() if item.startswith("word/media/")]
        xml = archive.read("word/document.xml").decode("utf-8")
    assert media, media
    assert "测试数据集" in xml
    print(f"EMBEDDED_MEDIA={len(media)}")
    shutil.rmtree(task_dir)


if __name__ == "__main__":
    main()
