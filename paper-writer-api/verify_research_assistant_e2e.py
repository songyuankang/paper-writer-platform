"""Phase 5A Dataset → assistant → confirmed existing Analysis verification."""
from __future__ import annotations
import json, shutil
from pathlib import Path
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.research_assistant_service import ResearchAssistantService


def main() -> None:
    root = Path(__file__).resolve().parent / "verification_research_assistant_e2e"
    if root.exists(): shutil.rmtree(root)
    settings = Settings(db_path=root / "data" / "history.db", output_dir=root / "outputs", upload_dir=root / "uploads", log_dir=root / "logs")
    task_id = "b" * 32
    raw = "学历,年龄,收入,满意度\n本科,22,5,66\n本科,25,6,70\n硕士,28,8,78\n硕士,30,9,81\n博士,34,12,90\n博士,36,13,93\n"
    dataset = DatasetService(settings).import_data(filename="assistant.csv", raw=raw.encode(), name="助手验收样本", task_id=task_id)
    assistant = ResearchAssistantService(settings)
    questions = ["不同学历是否影响满意度？", "年龄与满意度是否相关？", "年龄、收入是否影响满意度？"]
    recommendations = [assistant.recommend(question=item, hypothesis="", dataset_id=dataset["dataset_id"], dataset_version=1) for item in questions]
    methods = [item["recommendation"]["recommended_methods"][0] for item in recommendations]
    assert [item["type"] for item in methods] == ["anova", "pearson", "regression"]
    selected = methods[2]
    output = assistant.run_confirmed(task_id=task_id, dataset_id=dataset["dataset_id"], dataset_version=1, method=selected["type"], variables={"dependent_variable": selected["variables"][0], "predictors": selected["variables"][1:]})
    result = output["result"]
    assert result["status"] == "ready" and result["result"]["method"] == "ols"
    print(json.dumps({"dataset_id": dataset["dataset_id"], "dataset_version": 1, "fingerprint": result["data_fingerprint"], "recommended_methods": [item["type"] for item in methods], "analysis_id": output["analysis"]["id"], "analysis_result_id": result["id"], "actual_result_method": result["result"]["method"], "provider": [item["provider"] for item in recommendations]}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
