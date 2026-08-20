"""Phase 6B E2E: structured cross references follow ResearchObject numbering."""
from __future__ import annotations

import tempfile
from pathlib import Path
from zipfile import ZipFile

from app.config import Settings
from app.draft.service import DraftService
from app.services.cross_reference_service import CrossReferenceService
from app.services.research_object_service import ResearchObjectService

TASK = "x" * 32


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cross_reference_e2e_") as temporary:
        root = Path(temporary)
        settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        draft_service = DraftService(TASK, settings.output_dir / TASK)
        draft_service.save({
            "title": "交叉引用端到端验证", "meta": {"major": "测试", "paper_type": "课程论文", "word_count": 100, "reference_style": "gb7714", "keywords": []},
            "abstract": {"zh": "摘要", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [],
            "sections": [{"id": "1-1", "number": "1.1", "title": "实证结果", "level": 3, "gist": "", "paragraphs": [
                {"id": "fig_1", "type": "chart", "title": "第一图", "caption": "", "status": "ready", "asset": {"png_path": ""}},
                {"id": "fig_2", "type": "chart", "title": "第二图", "caption": "", "status": "ready", "asset": {"png_path": ""}},
                {"id": "table_1", "type": "table", "title": "样本统计表", "headers": ["类别", "数值"], "rows": [["A", "1"], ["B", "2"]]},
            ]}],
        })
        objects = ResearchObjectService(settings)
        refs = CrossReferenceService(settings)
        objects.renumber_document_references(TASK)
        candidates = {item["source_id"]: item for item in refs.reference_candidates(TASK)}
        first = refs.insert(task_id=TASK, section_id="1-1", target_object_id=candidates["fig_1"]["id"], prefix="如", suffix="所示")
        second = refs.insert(task_id=TASK, section_id="1-1", target_object_id=candidates["fig_2"]["id"], prefix="如", suffix="所示")
        third = refs.insert(task_id=TASK, section_id="1-1", target_object_id=candidates["table_1"]["id"], prefix="见", suffix="。")

        # Move original Figure 1 after Figure 2; object ID stays fixed while label changes.
        draft = draft_service.load(); paragraphs = draft["sections"][0]["paragraphs"]; item = next(block for block in paragraphs if block["id"] == "fig_1"); paragraphs.remove(item); index = next(i for i, block in enumerate(paragraphs) if block["id"] == "fig_2"); paragraphs.insert(index + 1, item); draft_service.save(draft)
        objects.renumber_document_references(TASK)
        moved = {item["id"]: item for item in refs.list(TASK)}
        assert moved[first["reference"]["id"]]["target_object_id"] == candidates["fig_1"]["id"]
        assert moved[first["reference"]["id"]]["resolved_label"] == "图2"
        assert moved[second["reference"]["id"]]["resolved_label"] == "图1"

        # Delete original Figure 2. Its reference becomes broken; Figure 1 receives 图1.
        draft = draft_service.load(); draft["sections"][0]["paragraphs"] = [block for block in draft["sections"][0]["paragraphs"] if block["id"] != "fig_2"]; draft_service.save(draft)
        objects.renumber_document_references(TASK)
        final_refs = {item["id"]: item for item in refs.list(TASK)}
        assert final_refs[first["reference"]["id"]]["resolved_label"] == "图1"
        assert final_refs[second["reference"]["id"]]["status"] == "broken"
        assert final_refs[third["reference"]["id"]]["resolved_label"] == "表1"

        files = draft_service.export()
        exported = next(item for item in files if item.endswith(".docx"))
        docx = Path(exported); docx = docx if docx.is_absolute() else settings.output_dir / TASK / docx
        with ZipFile(docx) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        for text in ("如图1所示", "见表1。", "[引用对象不存在]"):
            assert text in document, text
        print("CrossReference E2E passed")
        print({"docx": str(docx), "ready_reference": final_refs[first["reference"]["id"]], "broken_reference": final_refs[second["reference"]["id"]]})


if __name__ == "__main__":
    main()
