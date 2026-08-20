from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.draft.service import DraftService
from app.services.full_paper_generation_service import FullPaperGenerationService
from app.services.literature_service import LiteratureService

TASK = "8" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def paper(settings: Settings) -> DraftService:
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({
        "title": "智能传感技术研究",
        "meta": {"paper_type": "课程论文", "major": "电子信息", "word_count": 500, "completion_min_chars": 300, "keywords": []},
        "abstract": {"zh": "智能传感技术的研究。", "en": ""},
        "keywords": {"zh": ["智能传感"], "en": []},
        "acknowledgement": "", "references": [],
        "outline_meta": {"confirmation_required": False, "confirmed": True},
        "sections": [
            {"id": "1-1", "number": "1.1", "title": "研究背景与现状", "level": 2, "gist": "梳理智能传感相关研究现状", "paragraphs": []},
            {"id": "2-1", "number": "2.1", "title": "技术分析", "level": 2, "gist": "分析关键技术特征", "paragraphs": []},
        ],
        "generating": False, "progress": 0, "done": 0, "total": 2,
    })
    return service


def fake_generate(service: DraftService):
    def generate(section_id: str, model_id: str | None = None):
        with service.lock:
            draft = service.load()
            section = next(item for item in draft["sections"] if item["id"] == section_id)
            block = {"id": f"p-{section_id}-{len(section['paragraphs']) + 1}", "text": "本节围绕研究对象、理论基础与应用场景展开系统论述。" * 12}
            section["paragraphs"].append(block)
            service.save(draft)
            return block
    return generate


def test_full_pipeline_inserts_source_backed_table_chart_and_references(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    draft = paper(settings)
    literature = LiteratureService(settings)
    for title, year in [("Sensor Review A", 2021), ("Sensor Review B", 2022), ("Sensor Review C", 2023)]:
        literature.save(task_id=TASK, metadata={"title": title, "authors": ["Author"], "year": year, "abstract": f"Public metadata for {title}.", "source": "crossref", "source_id": title, "external_id": title})

    pipeline = FullPaperGenerationService(draft)
    monkeypatch.setattr(draft, "generate_section", fake_generate(draft))
    monkeypatch.setattr(draft, "generate_en_abstract", lambda model_id=None: "English abstract")
    monkeypatch.setattr(draft, "generate_acknowledgement", lambda model_id=None: "Acknowledgement")
    monkeypatch.setattr(pipeline.research, "search", lambda **kwargs: {"results": [], "saved_literature": literature.list(TASK)})

    pipeline.start()
    completed = pipeline.run()
    blocks = completed["sections"][0]["paragraphs"]
    assert any(block.get("type") == "table" and block.get("auto_full_paper") for block in blocks)
    assert any(block.get("type") == "chart" and block.get("auto_full_paper") for block in blocks)
    assert any(block.get("type") == "cross_reference" for block in blocks)
    chart = next(block for block in blocks if block.get("type") == "chart")
    assert chart["asset"]["png_path"]
    assert chart["figure_number"] == 1
    table = next(block for block in blocks if block.get("type") == "table")
    assert table["table_number"] == 1
    assert chart["research_visualization"]["source_snapshot"]
    assert completed["full_paper_pipeline"]["status"] == "completed"


def test_full_pipeline_pause_and_resume_state_is_persisted(tmp_path: Path):
    settings = settings_for(tmp_path)
    draft = paper(settings)
    pipeline = FullPaperGenerationService(draft)
    pipeline.start()
    requested = pipeline.pause()
    assert requested["status"] == "pause_requested"
    assert pipeline._checkpoint("planning", "正在分析") is False
    paused = pipeline.status()
    assert paused["generating"] is False
    assert paused["pipeline"]["status"] == "paused"
    resumed = pipeline.start(resume=True)
    assert resumed["status"] == "running"
    assert draft.load()["generating"] is True
