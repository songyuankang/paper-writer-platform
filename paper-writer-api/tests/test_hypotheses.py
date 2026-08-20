import json
from pathlib import Path

import pytest

from app.config import Settings
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.hypothesis_service import HypothesisService

TASK = "h" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def chain(tmp_path: Path, analysis_type="pearson", payload=None):
    settings = settings_for(tmp_path); datasets = DatasetService(settings)
    version = datasets.import_data(filename="sample.csv", raw=b"x,y,group\n1,2,A\n2,3,B\n3,4,A\n4,6,B\n5,7,A\n", name="样本", task_id=TASK)
    analyses = AnalysisService(settings)
    variables = {"x": "x", "y": "y"} if analysis_type in {"pearson", "spearman"} else {"group_column": "group", "value_column": "y"} if analysis_type in {"independent_t", "anova"} else {"dependent_variable": "y", "predictors": ["x"]}
    analysis = analyses.create(task_id=TASK, dataset_id=version["dataset_id"], dataset_version=1, analysis_type=analysis_type, variables=variables)
    defaults = {
        "pearson": {"method": "pearson", "x": "x", "y": "y", "n": 5, "r": .42, "p_value": .001, "alpha": .05},
        "spearman": {"method": "spearman", "x": "x", "y": "y", "n": 5, "rho": .42, "p_value": .001, "alpha": .05},
        "independent_t": {"method": "student_t", "group_a": "A", "group_b": "B", "n_a": 3, "n_b": 2, "mean_difference": 1.2, "t_statistic": 2.5, "p_value": .02, "effect_size": .8},
        "anova": {"method": "anova", "f_statistic": 4.3, "p_value": .02, "eta_squared": .21, "alpha": .05, "groups": ["A", "B"], "tukey_hsd": [{"group1": "A", "group2": "B", "mean_difference": -1.1, "p_adjusted": .02, "reject": True}]},
        "regression": {"method": "ols", "f_statistic": 8.2, "f_p_value": .01, "r_squared": .42, "n": 5, "alpha": .05, "coefficients": [{"variable": "x", "coefficient": .6, "standardized_coefficient": .5, "p_value": .01}]},
    }
    content = {**defaults[analysis_type], **(payload or {})}
    result = {"id": "ar_" + analysis_type + "_case", "analysis_id": analysis["id"], "dataset_id": version["dataset_id"], "dataset_version": 1, "dataset_version_id": f"{version['dataset_id']}:v1", "data_fingerprint": version["fingerprint"], "status": "ready", "result": content, "warnings": []}
    analyses._save_result(result); analysis["last_result_id"] = result["id"]; analyses._save(analysis)
    return settings, datasets, version, analysis, result


def hypothesis(settings, analysis, direction="positive", bindings=None):
    return HypothesisService(settings).create(task_id=TASK, title="H1", statement="变量关系假设", direction=direction, variable_bindings=bindings or {}, analysis_ids=[analysis["id"]])


def test_hypothesis_create_and_edit(tmp_path):
    settings, _, _, analysis, _ = chain(tmp_path); service = HypothesisService(settings)
    item = hypothesis(settings, analysis); changed = service.update(item["id"], {"title": "H1 修订", "direction": "association"})
    assert changed["title"] == "H1 修订" and changed["direction"] == "association" and changed["status"] == "pending"


def test_positive_pearson_supported(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis, "positive")
    evaluation = HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert evaluation["decision"] == "supported" and evaluation["evidence"]["direction_observed"] == "positive"


def test_negative_pearson_is_not_supported(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, payload={"r": -.42}); item = hypothesis(settings, analysis, "positive")
    assert HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])["decision"] == "not_supported"


def test_non_significant_pearson_is_insufficient(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, payload={"r": .05, "p_value": .62}); item = hypothesis(settings, analysis)
    assert HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])["decision"] == "insufficient_evidence"


def test_t_test_difference_rule(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, "independent_t"); item = hypothesis(settings, analysis, "difference")
    evidence = HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert evidence["decision"] == "supported" and evidence["evidence"]["effect_size"] == .8


def test_anova_with_tukey_evidence(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, "anova"); item = hypothesis(settings, analysis, "difference")
    evaluation = HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert evaluation["decision"] == "supported" and evaluation["evidence"]["tukey_significant_pairs"][0]["group1"] == "A"


def test_regression_model_and_predictor_significant(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, "regression"); item = hypothesis(settings, analysis, "positive", {"predictors": ["x"]})
    evaluation = HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert evaluation["decision"] == "supported" and evaluation["evidence"]["model_supported"] and evaluation["evidence"]["evaluated_predictors"][0]["supported"]


def test_regression_non_significant_predictor_is_inconclusive(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, "regression", {"coefficients": [{"variable": "x", "coefficient": .6, "standardized_coefficient": .5, "p_value": .6}]}); item = hypothesis(settings, analysis, "positive", {"predictors": ["x"]})
    assert HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])["decision"] == "inconclusive"


def test_regression_does_not_claim_all_predictors(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path, "regression", {"coefficients": [{"variable": "x", "coefficient": .6, "standardized_coefficient": .5, "p_value": .01}, {"variable": "income", "coefficient": .1, "standardized_coefficient": .1, "p_value": .8}]}); item = hypothesis(settings, analysis, "association", {"predictors": ["x", "income"]})
    output = HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert output["decision"] == "inconclusive" and [x["supported"] for x in output["evidence"]["evaluated_predictors"]] == [True, False]


def test_analysis_result_mismatch_rejected(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis)
    result["analysis_id"] = "an_other_analysis"
    AnalysisService(settings)._result_path(analysis["id"], result["id"]).write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Analysis 与 AnalysisResult"):
        HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])


def test_dataset_fingerprint_mismatch_rejected(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); result["data_fingerprint"] = "bad"; AnalysisService(settings)._save_result(result)
    with pytest.raises(ValueError, match="指纹"):
        HypothesisService(settings).evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])


def test_evaluation_stale_after_dataset_update(tmp_path):
    settings, datasets, version, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); service = HypothesisService(settings)
    evaluation = service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    datasets.import_data(filename="sample.csv", raw=b"x,y,group\n1,4,A\n2,6,B\n3,9,A\n", dataset_id=version["dataset_id"], task_id=TASK)
    assert service.evaluations(item["id"])[0]["data_status"] == "stale_source"
    framework = service.create_framework(task_id=TASK, hypothesis_ids=[item["id"]], evaluation_ids=[evaluation["id"]]); assert framework["status"] == "stale_source"


def test_re_evaluation_preserves_versions(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); service = HypothesisService(settings)
    service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"]); service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    assert len(service.evaluations(item["id"])) == 2


def test_multiple_hypotheses_and_dependency_graph(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); service = HypothesisService(settings); first = hypothesis(settings, analysis); second = service.create(task_id=TASK, title="H2", statement="另一假设", direction="association", analysis_ids=[analysis["id"]])
    e1 = service.evaluate(hypothesis_id=first["id"], analysis_id=analysis["id"], analysis_result_id=result["id"]); service.evaluate(hypothesis_id=second["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    links = DependencyGraphService(settings).rebuild_task(TASK)
    assert any(link["target_type"] == "hypothesis_evaluation" and link["target_id"] == e1["id"] for link in links)


def test_evaluation_evidence_trail(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); service = HypothesisService(settings); evaluation = service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    evidence = service.evidence(evaluation["id"]); assert evidence["hypothesis"]["id"] == item["id"] and evidence["analysis_result"]["id"] == result["id"]


def test_ai_decision_or_number_is_rejected(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); service = HypothesisService(settings); evaluation = service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    with pytest.raises(ValueError, match="不能包含"):
        service.create_framework(task_id=TASK, hypothesis_ids=[item["id"]], evaluation_ids=[evaluation["id"]], ai_suggestion={"decision": "supported"})
    with pytest.raises(ValueError, match="不能包含"):
        service.create_framework(task_id=TASK, hypothesis_ids=[item["id"]], evaluation_ids=[evaluation["id"]], ai_suggestion={"point": "r=0.9"})


def test_controlled_framework_without_model(tmp_path):
    settings, _, _, analysis, result = chain(tmp_path); item = hypothesis(settings, analysis); service = HypothesisService(settings); evaluation = service.evaluate(hypothesis_id=item["id"], analysis_id=analysis["id"], analysis_result_id=result["id"])
    framework = service.create_framework(task_id=TASK, hypothesis_ids=[item["id"]], evaluation_ids=[evaluation["id"]])
    assert framework["provider"] == "controlled_evidence_framework" and framework["sections"]["hypothesis_evaluation"][0]["decision"] == "supported"
