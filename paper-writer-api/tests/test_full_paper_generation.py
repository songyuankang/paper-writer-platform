from __future__ import annotations

from pathlib import Path
import zipfile

from app.config import Settings
from app.draft.service import DraftService
from app.services.full_paper_generation_service import FullPaperGenerationService
from app.services.dataset_service import DatasetService
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


def test_full_paper_generation_inserts_visualizations(tmp_path: Path, monkeypatch):
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
    # 正文段落后立即内联研究表图；不等待全文结束再统一追加。
    assert blocks.index(table) > 0
    assert blocks.index(chart) > blocks.index(table)

    # 新建 DraftService 模拟刷新/重新打开论文：同一正式 block 仍存在。
    reopened = DraftService(TASK, settings.output_dir / TASK).load()
    reopened_blocks = reopened["sections"][0]["paragraphs"]
    assert any(block.get("id") == table["id"] and block.get("type") == "table" for block in reopened_blocks)
    assert any(block.get("id") == chart["id"] and block.get("type") == "chart" for block in reopened_blocks)

    # 正文 API 使用的草稿对象仍含有真实 FigureBlock（type=chart）与 TableBlock。
    assert any(block.get("type") == "table" for block in reopened_blocks)
    assert any(block.get("type") == "chart" for block in reopened_blocks)

    files = draft.export()
    docx = next(Path(path) for path in files if str(path).endswith(".docx"))
    if not docx.is_absolute():
        docx = draft.task_dir / docx
    with zipfile.ZipFile(docx) as package:
        assert any(name.startswith("word/media/") for name in package.namelist())
        assert b"<w:tbl" in package.read("word/document.xml")


def test_full_paper_visualization_plan_deduplicates_five_section_e2e(tmp_path: Path, monkeypatch):
    """One task-level plan owns each evidence-backed artifact exactly once."""
    settings = settings_for(tmp_path)
    draft = DraftService(TASK, settings.output_dir / TASK)
    draft.save({
        "title": "智能传感技术研究", "meta": {"paper_type": "课程论文", "major": "电子信息", "word_count": 800, "completion_min_chars": 300, "keywords": []},
        "abstract": {"zh": "智能传感技术的研究。", "en": ""}, "keywords": {"zh": ["智能传感"], "en": []},
        "acknowledgement": "", "references": [], "outline_meta": {"confirmation_required": False, "confirmed": True},
        "sections": [
            {"id": "1-1", "number": "1.1", "title": "研究背景", "level": 2, "gist": "说明研究问题", "paragraphs": []},
            {"id": "2-1", "number": "2.1", "title": "文献综述", "level": 2, "gist": "梳理国内外研究现状", "paragraphs": []},
            {"id": "3-1", "number": "3.1", "title": "技术比较", "level": 2, "gist": "比较已核验技术指标", "paragraphs": []},
            {"id": "4-1", "number": "4.1", "title": "实验结果", "level": 2, "gist": "分析真实实验数据", "paragraphs": []},
            {"id": "5-1", "number": "5.1", "title": "结论", "level": 2, "gist": "总结研究结论", "paragraphs": []},
        ],
        "generating": False, "progress": 0, "done": 0, "total": 5,
    })
    literature = LiteratureService(settings)
    for title, year, score in [("Sensor Review A", 2021, 91), ("Sensor Review B", 2022, 94), ("Sensor Review C", 2023, 96)]:
        literature.save(task_id=TASK, metadata={"title": title, "authors": ["Author"], "year": year, "abstract": f"{title} reported accuracy {score}% in a verified evaluation.", "source": "crossref", "source_id": title, "external_id": title})
    dataset = DatasetService(settings).import_data(
        filename="experiment.csv",
        raw="样本,准确率,功耗\nA,91,12\nB,94,10\nC,96,8\n".encode("utf-8"),
        name="真实实验结果", task_id=TASK,
    )
    assert dataset["dataset_id"]

    pipeline = FullPaperGenerationService(draft)
    monkeypatch.setattr(draft, "generate_section", fake_generate(draft))
    monkeypatch.setattr(draft, "generate_en_abstract", lambda model_id=None: "English abstract")
    monkeypatch.setattr(draft, "generate_acknowledgement", lambda model_id=None: "Acknowledgement")
    monkeypatch.setattr(pipeline.research, "search", lambda **kwargs: {"results": [], "saved_literature": literature.list(TASK)})

    pipeline.start()
    completed = pipeline.run()
    plan = pipeline.visualization_plan.get(TASK)
    assert plan is not None
    assert len(plan["items"]) == 4
    assert {item["target_section_id"] for item in plan["items"]} == {"2-1", "3-1", "4-1"}
    assert [item["status"] for item in plan["items"]] == ["inserted", "inserted", "inserted", "inserted"]

    by_section = {section["id"]: section["paragraphs"] for section in completed["sections"]}
    literature_tables = [block for blocks in by_section.values() for block in blocks if block.get("type") == "table" and block.get("title") == "文献综述表"]
    annual_charts = [block for blocks in by_section.values() for block in blocks if block.get("type") == "chart" and block.get("title") == "已保存文献年度分布"]
    technology_tables = [block for block in by_section["3-1"] if block.get("research_visualization", {}).get("purpose") == "technology_comparison"]
    experiment_charts = [block for block in by_section["4-1"] if block.get("research_visualization", {}).get("purpose") == "experimental_result"]

    assert len(literature_tables) == 1 and literature_tables[0] in by_section["2-1"]
    assert len(annual_charts) == 1 and annual_charts[0] in by_section["2-1"]
    assert len(technology_tables) == 1 and technology_tables[0]["type"] == "table"
    assert len(experiment_charts) == 1 and experiment_charts[0]["type"] == "chart"
    assert not any(block.get("type") in {"chart", "table"} for block in by_section["1-1"] + by_section["5-1"])

    inserted_ids = [item["inserted_block_id"] for item in plan["items"]]
    assert len(inserted_ids) == len(set(inserted_ids))
    assert all(block.get("research_visualization", {}).get("visualization_plan_item_id") for blocks in by_section.values() for block in blocks if block.get("id") in inserted_ids)


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
