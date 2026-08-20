"""Run a real source-backed full-paper generation verification.

This is intentionally an integration script rather than a unit test: it calls
the existing public-metadata literature search, starts the body-first pipeline,
and validates the emitted DOCX contains a real chart image.  It never inserts
unverified numeric claims; the chart is a deterministic annual count of saved
literature metadata and the table preserves its source titles.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

from app.config import Settings
from app.draft.service import DraftService
from app.services.full_paper_generation_service import FullPaperGenerationService
from app.services.literature_service import LiteratureSearchService, LiteratureService

TASK = "f" * 32
ROOT = Path(__file__).resolve().parent / ".e2e_full_paper"


def build_settings() -> Settings:
    return Settings(
        db_path=ROOT / "data" / "history.db",
        output_dir=ROOT / "outputs",
        upload_dir=ROOT / "uploads",
        log_dir=ROOT / "logs",
    )


def main() -> int:
    shutil.rmtree(ROOT, ignore_errors=True)
    settings = build_settings()
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({
        "title": "智能传感技术研究进展",
        "meta": {"paper_type": "课程论文", "major": "电子信息工程", "word_count": 500, "completion_min_chars": 300, "keywords": ["智能传感", "边缘计算"]},
        "abstract": {"zh": "本文梳理智能传感技术的研究背景、发展现状与应用趋势。", "en": ""},
        "keywords": {"zh": ["智能传感", "边缘计算"], "en": []},
        "acknowledgement": "", "references": [],
        "outline_meta": {"confirmation_required": False, "confirmed": True},
        "sections": [
            {"id": "1-1", "number": "1.1", "title": "研究背景与国内外现状", "level": 2, "gist": "概述智能传感技术的研究背景、公开文献研究现状与时间分布", "paragraphs": []},
            {"id": "2-1", "number": "2.1", "title": "关键技术分析", "level": 2, "gist": "分析智能传感系统的关键技术路线", "paragraphs": []},
        ],
        "generating": False, "progress": 0, "done": 0, "total": 2,
    })

    # Public metadata comes from the existing CrossRef/OpenAlex search adapter.
    results = LiteratureSearchService(settings).search(query="smart sensor review", limit=10).get("results") or []
    if len(results) < 2:
        raise RuntimeError("未获取到足够公开文献元数据，无法执行真实来源 E2E")
    literature = LiteratureService(settings)
    saved = [literature.save(task_id=TASK, metadata=item) for item in results[:8]]
    if len({item.get("year") for item in saved if item.get("year")}) < 2:
        raise RuntimeError("公开检索结果的年份不足两个，无法验证年度分布图")

    pipeline = FullPaperGenerationService(service)
    pipeline.start()
    document = pipeline.run()
    blocks = [block for section in document["sections"] for block in section["paragraphs"]]
    table = next((block for block in blocks if block.get("type") == "table" and block.get("auto_full_paper")), None)
    chart = next((block for block in blocks if block.get("type") == "chart" and block.get("auto_full_paper")), None)
    reference = next((block for block in blocks if block.get("type") == "cross_reference"), None)
    if not table or not chart or not reference:
        raise RuntimeError("全文流水线未产出正文内联表格、图表和交叉引用")
    if not chart.get("asset", {}).get("png_path") or not chart.get("figure_number") or not table.get("table_number"):
        raise RuntimeError("图表资产或正式编号不完整")
    # Reload from disk to model a browser refresh/reopen. Both formal blocks must
    # remain in the persisted draft, not only in a candidate or memory object.
    reopened = DraftService(TASK, settings.output_dir / TASK).load()
    reloaded_blocks = [block for section in reopened["sections"] for block in section["paragraphs"]]
    if not any(block.get("id") == table.get("id") and block.get("type") == "table" for block in reloaded_blocks):
        raise RuntimeError("刷新后 TableBlock 未保留在正文草稿中")
    if not any(block.get("id") == chart.get("id") and block.get("type") == "chart" for block in reloaded_blocks):
        raise RuntimeError("刷新后 FigureBlock 未保留在正文草稿中")

    files = service.export()
    docx_name = next((str(path) for path in files if str(path).lower().endswith(".docx")), "")
    docx = Path(docx_name)
    if docx_name and not docx.is_absolute():
        docx = service.task_dir / docx
    if not docx_name or not docx.is_file():
        raise RuntimeError("DOCX 未生成")
    with zipfile.ZipFile(docx) as package:
        media = [name for name in package.namelist() if name.startswith("word/media/")]
        document_xml = package.read("word/document.xml")
    if not media:
        raise RuntimeError("DOCX 未包含图表媒体资产")
    if b"<w:tbl" not in document_xml:
        raise RuntimeError("DOCX 未包含由 TableBlock 导出的原生表格")

    print("FULL_PAPER_E2E_OK")
    print(f"sources={len(saved)} table={table['table_number']} chart={chart['figure_number']} media={len(media)} native_table=yes")
    print(f"docx={docx}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FULL_PAPER_E2E_FAILED: {exc}", file=sys.stderr)
        raise
