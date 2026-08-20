"""Phase 7A E2E: XLSX -> real analysis -> hypothesis -> evidence framework."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import openpyxl

from app.config import Settings
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.hypothesis_service import HypothesisService

TASK = "q" * 32


def xlsx_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    book = openpyxl.Workbook(); sheet = book.active; sheet.append(headers)
    for row in rows: sheet.append(row)
    buffer = io.BytesIO(); book.save(buffer); return buffer.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hypothesis_discussion_e2e_") as temp:
        root = Path(temp); settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
        datasets, analyses, hypotheses = DatasetService(settings), AnalysisService(settings), HypothesisService(settings)

        # E2E 1: XLSX -> Pearson -> positive statistically supported hypothesis.
        pearson_data = datasets.import_data(filename="pearson.xlsx", raw=xlsx_bytes(["age", "satisfaction"], [[i, 3 * i + (i % 2)] for i in range(1, 18)]), name="相关数据", task_id=TASK)
        pearson = analyses.create(task_id=TASK, dataset_id=pearson_data["dataset_id"], dataset_version=1, analysis_type="pearson", variables={"x": "age", "y": "satisfaction"}, name="年龄与满意度 Pearson")
        pearson_result = analyses.run(pearson["id"])
        h1 = hypotheses.create(task_id=TASK, title="H1", statement="年龄与满意度呈正相关。", direction="positive", analysis_ids=[pearson["id"]])
        e1 = hypotheses.evaluate(hypothesis_id=h1["id"], analysis_id=pearson["id"], analysis_result_id=pearson_result["id"])
        assert e1["decision"] == "supported", e1

        # E2E 2: XLSX -> ANOVA -> Tukey group-pair evidence.
        anova_data = datasets.import_data(filename="anova.xlsx", raw=xlsx_bytes(["education", "satisfaction"], [["高中", value] for value in [40, 42, 41, 43, 39]] + [["本科", value] for value in [60, 62, 59, 61, 63]] + [["研究生", value] for value in [80, 82, 79, 81, 83]]), name="ANOVA 数据", task_id=TASK)
        anova = analyses.create(task_id=TASK, dataset_id=anova_data["dataset_id"], dataset_version=1, analysis_type="anova", variables={"group_column": "education", "value_column": "satisfaction"}, name="学历差异 ANOVA")
        anova_result = analyses.run(anova["id"])
        h2 = hypotheses.create(task_id=TASK, title="H2", statement="不同学历群体的满意度存在显著差异。", direction="difference", analysis_ids=[anova["id"]])
        e2 = hypotheses.evaluate(hypothesis_id=h2["id"], analysis_id=anova["id"], analysis_result_id=anova_result["id"])
        assert e2["decision"] == "supported" and e2["evidence"]["tukey_significant_pairs"], e2

        # E2E 3: XLSX -> OLS -> separate model and predictor evaluation.
        regression_rows = []
        for index in range(1, 25):
            age, income, duration = index, (index * 7) % 19 + 2, (index * 5) % 11 + 1
            satisfaction = 2.4 * age + .35 * income + .02 * duration + ((index % 3) - 1) * .3
            regression_rows.append([age, income, duration, satisfaction])
        regression_data = datasets.import_data(filename="regression.xlsx", raw=xlsx_bytes(["age", "income", "duration", "satisfaction"], regression_rows), name="回归数据", task_id=TASK)
        regression = analyses.create(task_id=TASK, dataset_id=regression_data["dataset_id"], dataset_version=1, analysis_type="regression", variables={"dependent_variable": "satisfaction", "predictors": ["age", "income", "duration"]}, name="满意度 OLS")
        regression_result = analyses.run(regression["id"])
        h3 = hypotheses.create(task_id=TASK, title="H3", statement="年龄、收入和使用时长能够显著预测满意度。", direction="positive", variable_bindings={"predictors": ["age", "income", "duration"]}, analysis_ids=[regression["id"]])
        e3 = hypotheses.evaluate(hypothesis_id=h3["id"], analysis_id=regression["id"], analysis_result_id=regression_result["id"])
        assert "model_supported" in e3["evidence"] and len(e3["evidence"]["predictors"]) == 3, e3

        framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[h1["id"], h2["id"], h3["id"]], evaluation_ids=[e1["id"], e2["id"], e3["id"]])
        assert framework["provider"] == "controlled_evidence_framework"
        assert DependencyGraphService(settings).get_upstream(TASK, "hypothesis_evaluation", e1["id"])

        # A new DatasetVersion marks historical evaluation/framework stale, but retains all snapshots.
        datasets.import_data(filename="pearson.xlsx", raw=xlsx_bytes(["age", "satisfaction"], [[i, 5 * i] for i in range(1, 18)]), dataset_id=pearson_data["dataset_id"], task_id=TASK)
        assert hypotheses.evaluations(h1["id"])[0]["data_status"] == "stale_source"
        assert hypotheses.get_framework(framework["id"])["status"] == "stale_source"
        print("Hypothesis discussion E2E passed")
        print({"h1": e1["decision"], "h2_tukey_pairs": len(e2["evidence"]["tukey_significant_pairs"]), "h3_model_supported": e3["evidence"]["model_supported"], "framework": framework["id"]})


if __name__ == "__main__":
    main()
