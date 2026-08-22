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
            body = "".join([
                "问题界定明确了研究对象及其现实边界。",
                "理论基础阐释了关键概念之间的逻辑关系。",
                "方法说明交代了分析路径与识别思路。",
                "资料来源限定了证据的适用范围。",
                "变量设计区分了核心指标与控制因素。",
                "比较分析呈现了不同条件下的差异。",
                "结果讨论解释了主要发现的经济含义。",
                "稳健检验考察了替代设定下的结论。",
                "机制部分说明了影响发生的传导渠道。",
                "异质性视角识别了群体间的不同表现。",
                "局限说明保留了证据不足与待验证之处。",
                "小结归纳了本节论证与后文的衔接关系。",
            ])
            block = {"id": f"p-{section_id}-{len(section['paragraphs']) + 1}", "text": body}
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


def semantic_plan_paper(settings: Settings) -> DraftService:
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({
        "title": "基于深度学习的校园网络安全异常检测系统设计与实现",
        "meta": {"paper_type": "毕业论文", "major": "计算机", "word_count": 800, "completion_min_chars": 300, "keywords": []},
        "abstract": {"zh": "校园网络安全异常检测研究。", "en": ""},
        "keywords": {"zh": ["网络安全"], "en": []},
        "acknowledgement": "", "references": [], "outline_meta": {"confirmation_required": False, "confirmed": True},
        "sections": [
            {"id": "1-1", "number": "1.1", "title": "相关研究与发展现状", "level": 2, "gist": "梳理网络异常检测的研究进展", "paragraphs": []},
            {"id": "2-1", "number": "2.1", "title": "传统与深度学习检测技术对比", "level": 2, "gist": "比较传统方法与深度学习方法的检测指标", "paragraphs": []},
            {"id": "4-1-2", "number": "4.1.2", "title": "实验环境与超参数配置", "level": 3, "gist": "列出 GPU、框架与超参数设置", "paragraphs": []},
            {"id": "4-2-1", "number": "4.2.1", "title": "与 Baseline 模型的性能对比", "level": 3, "gist": "呈现准确率、召回率、F1 和 AUC 的对比实验结果", "paragraphs": []},
            {"id": "4-2-2", "number": "4.2.2", "title": "CNN 与 LSTM 模块的消融实验", "level": 3, "gist": "分析模块移除后的实验结果", "paragraphs": []},
        ],
        "generating": False, "progress": 0, "done": 0, "total": 5,
    })
    return service


def seed_verified_literature(settings: Settings) -> LiteratureService:
    literature = LiteratureService(settings)
    for title, year, latency in [("Method A", 2021, 120), ("Method B", 2022, 95), ("Method C", 2023, 70)]:
        literature.save(task_id=TASK, metadata={
            "title": title, "authors": ["Author"], "year": year,
            "abstract": f"{title} reported latency {latency} ms in a verified evaluation.",
            "source": "crossref", "source_id": title, "external_id": title,
        })
    return literature


def configure_pipeline_for_local_sources(pipeline: FullPaperGenerationService, draft: DraftService, literature: LiteratureService, monkeypatch) -> None:
    monkeypatch.setattr(draft, "generate_section", fake_generate(draft))
    monkeypatch.setattr(draft, "generate_en_abstract", lambda model_id=None: "English abstract")
    monkeypatch.setattr(draft, "generate_acknowledgement", lambda model_id=None: "Acknowledgement")
    monkeypatch.setattr(pipeline.research, "search", lambda **kwargs: {"results": [], "saved_literature": literature.list(TASK)})


def test_final_plan_is_built_after_global_research_and_scores_semantic_sections(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    draft = semantic_plan_paper(settings)
    literature = seed_verified_literature(settings)
    pipeline = FullPaperGenerationService(draft)
    configure_pipeline_for_local_sources(pipeline, draft, literature, monkeypatch)

    started = pipeline.start()
    assert started["visualization_plan"]["status"] == "preparing"
    assert pipeline.visualization_plan.get(TASK) is None

    completed = pipeline.run()
    plan = pipeline.visualization_plan.get(TASK)
    assert plan is not None and plan["finalized"] is True
    by_purpose = {item["purpose"]: item for item in plan["items"]}
    assert by_purpose["literature_review_table"]["target_section_id"] == "1-1"
    assert by_purpose["literature_year_distribution"]["target_section_id"] == "1-1"
    assert by_purpose["technology_comparison"]["target_section_id"] == "2-1"
    assert "experimental_result" not in by_purpose
    assert plan["summary"]["experiment_section_id"] == "4-2-1"
    assert "实验图已跳过：尚未添加研究数据。" in plan["summary"]["notices"]
    summary = completed["full_paper_pipeline"]["visualization_plan"]
    assert summary["total_items"] == 3
    assert summary["ready_candidate_count"] == 0
    assert summary["inserted_count"] + summary["skipped_count"] + summary["broken_count"] == 3


def test_dataset_version_materializes_ready_candidate_then_inserts_figureblock(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    draft = semantic_plan_paper(settings)
    literature = seed_verified_literature(settings)
    dataset = DatasetService(settings).import_data(
        filename="network-results.csv",
        raw="model,accuracy,recall\nSVM,85.2,72.1\nCNN-LSTM,93.7,89.8\n".encode("utf-8"),
        name="真实网络异常检测实验结果",
        task_id=TASK,
    )
    assert dataset["dataset_id"]
    pipeline = FullPaperGenerationService(draft)
    configure_pipeline_for_local_sources(pipeline, draft, literature, monkeypatch)

    pipeline.start()
    pipeline._prepare_global_research(None)
    plan = pipeline.visualization_plan.get(TASK)
    assert plan is not None
    experiment = next(item for item in plan["items"] if item["purpose"] == "experimental_result")
    assert experiment["target_section_id"] == "4-2-1"
    assert experiment["dataset_ids"] == [dataset["dataset_id"]]

    candidates = pipeline._candidates_for_plan_items([experiment], "4.2.1 与 Baseline 模型的性能对比")
    candidate = pipeline._candidate_for_item(experiment, candidates, set())
    assert candidate is not None and candidate["status"] == "ready"
    accepted, _ = pipeline.visualization_plan.accept_candidate(TASK, experiment["id"], candidate, draft.load())
    assert accepted is True
    ready_summary = pipeline.visualization_plan.summary(TASK)
    assert ready_summary is not None and ready_summary["ready_candidate_count"] == 1

    result = pipeline.research.insert(candidate_id=candidate["id"], section_id="4-2-1")
    block_id = pipeline._record_insert("4-2-1", result)
    assert block_id
    pipeline.visualization_plan.mark_inserted(TASK, experiment["id"], block_id)
    inserted_summary = pipeline.visualization_plan.summary(TASK)
    assert inserted_summary is not None
    assert inserted_summary["ready_candidate_count"] == 0
    assert inserted_summary["inserted_count"] == 1
    blocks = next(section for section in draft.load()["sections"] if section["id"] == "4-2-1")["paragraphs"]
    assert any(block.get("id") == block_id and block.get("type") == "chart" for block in blocks)


def test_resume_rebuilds_legacy_provisional_plan_after_research_is_ready(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    draft = semantic_plan_paper(settings)
    literature = seed_verified_literature(settings)
    pipeline = FullPaperGenerationService(draft)
    configure_pipeline_for_local_sources(pipeline, draft, literature, monkeypatch)

    pipeline.start()
    pipeline._prepare_global_research(None)
    legacy = pipeline.visualization_plan.get(TASK)
    assert legacy is not None and legacy["finalized"] is True
    legacy.update({"finalized": False, "status": "planned", "items": []})
    pipeline.visualization_plan._write(TASK, legacy)

    completed = pipeline.run()
    rebuilt = pipeline.visualization_plan.get(TASK)
    assert rebuilt is not None and rebuilt["finalized"] is True
    assert len(rebuilt["items"]) == 3
    assert completed["full_paper_pipeline"]["visualization_plan"]["total_items"] == 3


def test_full_pipeline_records_quality_blocked_section_without_visualization_insert(tmp_path: Path, monkeypatch):
    settings = settings_for(tmp_path)
    draft = paper(settings)
    pipeline = FullPaperGenerationService(draft)
    blocked = {"id": "", "status": "quality_blocked", "attempt_count": 2, "quality_issues": [{"code": "repeated_heading"}]}
    monkeypatch.setattr(draft, "generate_section", lambda *_args, **_kwargs: blocked)

    pipeline.start()
    section = draft.load()["sections"][0]
    assert pipeline._generate_one_section(section, 1, 2, None, allow_research=True) is True
    current = draft.load()
    state = current["full_paper_pipeline"]
    assert state["quality_blocked_sections"][0]["section_id"] == "1-1"
    assert "1-1" not in state["completed_section_ids"]
    assert not current["sections"][0]["paragraphs"]

    with draft.lock:
        current = draft.load()
        current["full_paper_pipeline"].update(status="running", quality_blocked_sections=state["quality_blocked_sections"])
        draft.save(current)
    monkeypatch.setattr(pipeline, "_prepare_global_research", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_generate_one_section", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(pipeline, "_supplement", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(draft, "generate_en_abstract", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(draft, "generate_acknowledgement", lambda *_args, **_kwargs: "")
    completed = pipeline.run()
    assert completed["full_paper_pipeline"]["status"] == "completed_with_quality_blocks"
    assert completed["word_status"] == "quality_blocked"
