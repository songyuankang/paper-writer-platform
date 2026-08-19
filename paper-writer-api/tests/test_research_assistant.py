from __future__ import annotations
from pathlib import Path
import pytest
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.research_assistant_service import ResearchAssistantService

TASK_ID = "a" * 32


def setup(tmp_path: Path):
    settings = Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")
    data = "学历,年龄,收入,满意度\n本科,22,5,66\n本科,25,6,70\n硕士,28,8,78\n硕士,30,9,81\n博士,34,12,90\n博士,36,13,93\n"
    dataset = DatasetService(settings).import_data(filename="assistant.csv", raw=data.encode(), name="助手样本", task_id=TASK_ID)
    return settings, ResearchAssistantService(settings), dataset


def method(service, dataset, question: str):
    return service.recommend(question=question, hypothesis="", dataset_id=dataset["dataset_id"], dataset_version=1)["recommendation"]["recommended_methods"][0]["type"]


def test_rules_recommend_anova_correlation_and_regression(tmp_path):
    _, service, dataset = setup(tmp_path)
    assert method(service, dataset, "不同学历是否影响满意度？") == "anova"
    assert method(service, dataset, "年龄与满意度是否相关？") == "pearson"
    assert method(service, dataset, "年龄、收入是否影响满意度？") == "regression"


def test_recommendation_rejects_missing_dataset_and_invalid_model_structure(tmp_path, monkeypatch):
    _, service, dataset = setup(tmp_path)
    with pytest.raises(ValueError): service.recommend(question="", hypothesis="", dataset_id=dataset["dataset_id"], dataset_version=1)
    with pytest.raises(Exception): service.recommend(question="年龄与满意度相关", hypothesis="", dataset_id="missing", dataset_version=1)
    class Runtime: base_url="https://example.invalid"; api_key="key"; model="mock"; max_tokens=200
    monkeypatch.setattr("app.services.research_assistant_service.resolve_model", lambda _: Runtime())
    monkeypatch.setattr("app.services.research_assistant_service.deepseek.chat_with", lambda *args, **kwargs: '{"recommended_methods":[{"type":"logistic","variables":["年龄"]}]}')
    response = service.recommend(question="年龄与满意度是否相关？", hypothesis="", dataset_id=dataset["dataset_id"], dataset_version=1)
    assert response["provider"] == "configured_model" and response["recommendation"]["recommended_methods"][0]["type"] == "pearson"


def test_confirmed_recommendation_runs_existing_analysis_only_after_confirmation(tmp_path):
    _, service, dataset = setup(tmp_path)
    recommendation = service.recommend(question="年龄、收入是否影响满意度？", hypothesis="", dataset_id=dataset["dataset_id"], dataset_version=1)["recommendation"]
    selected = recommendation["recommended_methods"][0]
    output = service.run_confirmed(task_id=TASK_ID, dataset_id=dataset["dataset_id"], dataset_version=1, method=selected["type"], variables={"dependent_variable": selected["variables"][0], "predictors": selected["variables"][1:]})
    assert output["analysis"]["type"] == "regression" and output["result"]["result"]["method"] == "ols"
    with pytest.raises(ValueError): service.run_confirmed(task_id=TASK_ID, dataset_id=dataset["dataset_id"], dataset_version=1, method="regression", variables={"dependent_variable": "满意度", "predictors": ["学历"]})
