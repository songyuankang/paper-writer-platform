from pathlib import Path

import pytest

from app.config import Settings
from app.draft.service import DraftService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.literature_service import LiteratureService
from app.services.research_visualization_service import (
    BROKEN,
    CONFLICT,
    STALE,
    VERIFIED,
    ResearchVisualizationService,
)

TASK = "9" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def paper(settings: Settings) -> DraftService:
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({"title": "AI 可视化测试", "meta": {"paper_type": "课程论文", "keywords": []}, "abstract": {"zh": "", "en": ""}, "keywords": {"zh": [], "en": []}, "acknowledgement": "", "references": [], "sections": [{"id": "2-1", "number": "2.1", "title": "技术比较", "level": 2, "gist": "", "paragraphs": []}]})
    return service


def verified_evidence(service: ResearchVisualizationService):
    values = [("红外阵列", 120, "mW"), ("毫米波雷达", 80, "mW"), ("可穿戴设备", 40, "mW")]
    return [service.add_manual_evidence(task_id=TASK, subject=subject, metric="功耗", value=value, unit=unit, source_title=f"{subject}公开规格", source_location="Table 3", source_quote=f"{subject} power consumption is {value} {unit}.", year=2024, device_model="公开型号", test_condition="标准条件") for subject, value, unit in values]


def test_verified_evidence_generates_confirmable_table_and_chart(tmp_path: Path):
    settings = settings_for(tmp_path)
    draft = paper(settings)
    service = ResearchVisualizationService(settings)
    evidence = verified_evidence(service)
    assert {item["verification_status"] for item in evidence} == {VERIFIED}
    candidates = service.recommend(task_id=TASK, section="第二章技术比较", evidence_ids=[item["id"] for item in evidence])
    table = next(item for item in candidates if item["kind"] == "table")
    chart = next(item for item in candidates if item["kind"] == "chart")
    assert table["table_type"] == "technology_comparison"
    assert chart["chart"]["asset"]["png_path"]
    before = len(draft.load()["sections"][0]["paragraphs"])
    assert service.preview(table["id"])["requires_confirmation"] is True
    assert len(draft.load()["sections"][0]["paragraphs"]) == before
    inserted = service.insert(candidate_id=table["id"], section_id="2-1")
    assert inserted["inserted"]["block"]["type"] == "table"
    inserted_chart = service.insert(candidate_id=chart["id"], section_id="2-1")
    assert inserted_chart["inserted"]["block"]["type"] == "chart"
    blocks = draft.load()["sections"][0]["paragraphs"]
    assert any(block.get("research_visualization", {}).get("candidate_id") == table["id"] for block in blocks)
    assert any(block.get("research_visualization", {}).get("candidate_id") == chart["id"] for block in blocks)


def test_conflicting_sources_are_not_recommended(tmp_path: Path):
    settings = settings_for(tmp_path)
    paper(settings)
    service = ResearchVisualizationService(settings)
    first = service.add_manual_evidence(task_id=TASK, subject="红外阵列", metric="功耗", value=120, unit="mW", source_title="来源 A", source_location="Table 3", source_quote="Power is 120 mW.")
    second = service.add_manual_evidence(task_id=TASK, subject="红外阵列", metric="功耗", value=150, unit="mW", source_title="来源 B", source_location="Table 3", source_quote="Power is 150 mW.")
    records = {item["id"]: item for item in service.evidence(TASK)}
    assert records[first["id"]]["verification_status"] == CONFLICT
    assert records[second["id"]]["verification_status"] == CONFLICT
    assert service.recommend(task_id=TASK, evidence_ids=[first["id"], second["id"]])[0]["status"] == "pending"


def test_literature_deletion_marks_inserted_candidate_broken(tmp_path: Path):
    settings = settings_for(tmp_path)
    draft = paper(settings)
    literature = LiteratureService(settings)
    source_a = literature.save(task_id=TASK, metadata={"title": "Infrared source", "authors": ["A"], "year": 2024, "abstract": "The power consumption is 120 mW.", "source": "manual", "source_id": "a", "external_id": "a"})
    source_b = literature.save(task_id=TASK, metadata={"title": "Radar source", "authors": ["B"], "year": 2024, "abstract": "The power consumption is 80 mW.", "source": "manual", "source_id": "b", "external_id": "b"})
    service = ResearchVisualizationService(settings)
    evidence = service.extract(task_id=TASK, literature_ids=[source_a["id"], source_b["id"]])
    assert all(item["verification_status"] == VERIFIED for item in evidence)
    table = next(item for item in service.recommend(task_id=TASK, evidence_ids=[item["id"] for item in evidence]) if item["kind"] == "table")
    service.insert(candidate_id=table["id"], section_id="2-1")
    literature.delete(source_a["id"])
    graph_records = DependencyGraphService(settings)._records(TASK)[0]
    assert graph_records[("visualization_candidate", table["id"])]["status"] == BROKEN
    service.refresh_status(TASK)
    assert service.preview(table["id"])["candidate"]["status"] == BROKEN
    block = next(item for item in draft.load()["sections"][0]["paragraphs"] if item.get("research_visualization", {}).get("candidate_id") == table["id"])
    assert block["status"] == BROKEN


def test_dataset_version_update_marks_dataset_candidate_stale(tmp_path: Path):
    settings = settings_for(tmp_path)
    paper(settings)
    datasets = DatasetService(settings)
    dataset = datasets.import_data(filename="source.csv", raw=b"x,y\n1,2\n2,4\n3,6\n", name="现有数据", task_id=TASK)
    service = ResearchVisualizationService(settings)
    candidate = next(item for item in service.recommend(task_id=TASK, dataset_id=dataset["dataset_id"], dataset_version=1) if item["kind"] == "chart")
    assert candidate["chart_kind"] == "scatter"
    assert candidate["chart"]["asset"]["png_path"]
    datasets.import_data(filename="source-v2.csv", raw=b"x,y\n1,3\n2,6\n3,9\n", dataset_id=dataset["dataset_id"], name="现有数据", task_id=TASK)
    graph_records = DependencyGraphService(settings)._records(TASK)[0]
    assert graph_records[("visualization_candidate", candidate["id"])]["status"] == STALE
    service.refresh_status(TASK)
    assert service.preview(candidate["id"])["candidate"]["status"] == STALE


def test_unverifiable_manual_number_cannot_become_candidate(tmp_path: Path):
    settings = settings_for(tmp_path)
    paper(settings)
    service = ResearchVisualizationService(settings)
    item = service.add_manual_evidence(task_id=TASK, subject="对象", metric="功耗", value=120, unit="mW", source_title="来源", source_location="Table 3", source_quote="The consumption value is not stated here.")
    assert item["verification_status"] != VERIFIED
    assert service.recommend(task_id=TASK, evidence_ids=[item["id"]])[0]["status"] == "pending"


def test_visualization_api_plan_evidence_preview_and_confirmation_gate(tmp_path: Path, monkeypatch):
    from fastapi import HTTPException
    from app.api import research_visualizations as api

    settings = settings_for(tmp_path)
    paper(settings)
    monkeypatch.setattr(api, "settings", settings)
    planned = api.create_plan(api.PlanRequest(task_id=TASK, topic="红外阵列与毫米波技术比较", chapter="第二章"))
    assert planned["plan"]["queries"]
    records = []
    for subject, value in [("红外阵列", 120), ("毫米波雷达", 80)]:
        records.append(api.manual_evidence(api.ManualEvidenceRequest(task_id=TASK, subject=subject, metric="功耗", value=value, unit="mW", source_title=f"{subject}公开规格", source_location="Table 3", source_quote=f"{subject} power is {value} mW."))["evidence"])
    candidate = next(item for item in api.recommend_visualizations(api.RecommendRequest(task_id=TASK, evidence_ids=[item["id"] for item in records]))["candidates"] if item.get("kind") == "table")
    assert api.preview_candidate(candidate["id"])["requires_confirmation"] is True
    with pytest.raises(HTTPException, match="请确认"):
        api.insert_candidate(candidate["id"], api.InsertRequest(section_id="2-1", confirmed=False))


def test_different_verified_metrics_generate_parameter_comparison_table(tmp_path: Path):
    settings = settings_for(tmp_path)
    paper(settings)
    service = ResearchVisualizationService(settings)
    infrared = service.add_manual_evidence(task_id=TASK, subject="红外阵列", metric="响应度", value=34, unit="V/W", source_title="公开红外阵列论文", source_location="Abstract", source_quote="The pixel device has 34 V/W responsivity.")
    radar = service.add_manual_evidence(task_id=TASK, subject="毫米波天线", metric="峰值增益", value=5, unit="dB", source_title="公开毫米波论文", source_location="Section 3", source_quote="The antenna demonstrated a peak gain of 5 dB.")
    candidates = service.recommend(task_id=TASK, evidence_ids=[infrared["id"], radar["id"]])
    table = next(item for item in candidates if item.get("kind") == "table")
    assert table["title"] == "技术参数对比表"
    assert table["table_spec"]["headers"] == ["对象", "指标", "数值", "单位", "来源"]
    assert not any(item.get("kind") == "chart" for item in candidates)
