from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
sys.path.insert(0, str(PROJECT_API))

from app.draft.service import DraftService


def main() -> None:
    task_dir = PROJECT_API / "_draft_chart_export_verification"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    paper = {
        "title": "草稿路径图表导出验证",
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
        "abstract": "用于验证草稿编辑器路径中的图表导出。",
        "keywords": ["图表", "草稿", "导出"],
        "references": [],
    }

    service = DraftService("draft-chart-export-verification", task_dir)
    draft = service.build(paper)
    for section in draft["sections"]:
        if section.get("level") == 3:
            section["paragraphs"] = [
                {
                    "id": f"{section['id']}-p1",
                    "text": "这是用于验证图表导出链路的正文内容。",
                }
            ]
    service.save(draft)

    files = service.export()
    docx_candidates = list(task_dir.rglob("*.docx"))
    if not docx_candidates:
        raise RuntimeError(f"未生成 DOCX，输出文件：{files}")
    with zipfile.ZipFile(docx_candidates[0]) as archive:
        embedded = [name for name in archive.namelist() if name.startswith("word/media/")]
    if len(embedded) < 2:
        raise RuntimeError(f"草稿导出没有嵌入预期图表：{embedded}")

    print(f"DOCX={docx_candidates[0]}")
    print(f"FILES={len(files)}")
    print(f"EMBEDDED_MEDIA={len(embedded)}")
    shutil.rmtree(task_dir)


if __name__ == "__main__":
    main()
