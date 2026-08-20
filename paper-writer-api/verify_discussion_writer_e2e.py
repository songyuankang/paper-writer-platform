"""Phase 7C E2E: protected Discussion Writer across Pearson, ANOVA and OLS.

The verifier deliberately calls the same persistent services used by the API rather
than injecting test-only records.  It exercises an actual XLSX import, analysis,
hypothesis evaluation, externally supplied LiteratureEvidence, versioned drafts,
explicit insertion, dependency links and DOCX dynamic reference rendering.
"""
from __future__ import annotations

import html
import io
import re
import tempfile
from pathlib import Path
from zipfile import ZipFile

import openpyxl

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.discussion_writer_service import DiscussionWriterService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService

TASK = "d" * 32


def xlsx_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "数据"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def make_settings(root: Path) -> Settings:
    return Settings(
        db_path=root / "data" / "history.db",
        output_dir=root / "outputs",
        upload_dir=root / "uploads",
        log_dir=root / "logs",
    )


def make_paper(settings: Settings) -> DraftService:
    paper = DraftService(TASK, settings.output_dir / TASK)
    paper.save({
        "title": "Discussion Writer E2E",
        "meta": {"major": "教育技术", "paper_type": "课程论文", "word_count": 1500, "reference_style": "gb7714", "keywords": []},
        "abstract": {"zh": "端到端验证", "en": ""},
        "keywords": {"zh": [], "en": []},
        "acknowledgement": "",
        "references": [],
        "sections": [{"id": "4-1", "number": "4.1", "title": "讨论", "level": 3, "gist": "", "paragraphs": []}],
    })
    return paper


def evidence(literature: LiteratureService, hypothesis_id: str, *, title: str, claim: str, source_location: str, source_text: str) -> dict:
    item = literature.save(task_id=TASK, metadata={
        "title": title,
        "authors": ["Zhang Wei", "Li Na", "Wang Yu"],
        "year": 2024,
        "journal": "Open Education Research",
        "doi": f"10.9999/{title.lower().replace(' ', '-')}",
        "url": "https://example.invalid/evidence",
        "abstract": source_text if source_location == "abstract" else "",
        "source": "manual",
        "source_id": title.lower().replace(" ", "-"),
        "external_id": title.lower().replace(" ", "-"),
        "user_note": source_text if source_location == "user_note" else "",
    })
    verified_source = title if source_location == "metadata" else source_text
    card = literature.add_evidence(
        literature_id=item["id"], claim=claim, evidence=verified_source, source_location=source_location,
    )
    literature.link_hypothesis(task_id=TASK, hypothesis_id=hypothesis_id, literature_id=item["id"], relation="supporting")
    return {"item": item, "card": card}


def section_text(draft: dict, section: str) -> str:
    return "\n".join(item["text"] for item in draft["sections"][section]["paragraphs"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="discussion_writer_e2e_") as temp:
        settings = make_settings(Path(temp))
        paper = make_paper(settings)
        datasets = DatasetService(settings)
        analyses = AnalysisService(settings)
        hypotheses = HypothesisService(settings)
        literature = LiteratureService(settings)
        explanations = ResearchExplanationService(settings)
        findings = ResearchFindingService(settings)
        writer = DiscussionWriterService(settings)

        # Scenario 1: XLSX -> Dataset -> Pearson -> Evaluation -> Finding -> LiteratureEvidence
        # -> Framework -> versioned draft -> preview -> explicit insertion -> DOCX.
        pearson_dataset = datasets.import_data(
            filename="pearson.xlsx",
            raw=xlsx_bytes(["engagement", "satisfaction"], [[i, 2 * i + (i % 3)] for i in range(1, 19)]),
            name="学习参与与满意度", task_id=TASK,
        )
        pearson = analyses.create(task_id=TASK, dataset_id=pearson_dataset["dataset_id"], dataset_version=1, analysis_type="pearson", variables={"x": "engagement", "y": "satisfaction"}, name="Pearson 相关")
        pearson_result = analyses.run(pearson["id"])
        h1 = hypotheses.create(task_id=TASK, title="H1", statement="学习参与度与满意度呈正向关联。", direction="positive", analysis_ids=[pearson["id"]])
        e1 = hypotheses.evaluate(hypothesis_id=h1["id"], analysis_id=pearson["id"], analysis_result_id=pearson_result["id"])
        assert e1["decision"] == "supported", e1
        pearson_explanation = explanations.explain(analysis_id=pearson["id"], analysis_result_id=pearson_result["id"])
        pearson_finding = findings.generate(task_id=TASK, analysis_id=pearson["id"], analysis_result_id=pearson_result["id"], explanation_id=pearson_explanation["id"], style={"length": "standard"})
        pearson_lit = evidence(literature, h1["id"], title="Learning Engagement Association", claim="学习参与与满意度存在关联证据", source_location="abstract", source_text="The abstract reports an association between learning engagement and satisfaction.")
        pearson_framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[h1["id"]], finding_ids=[pearson_finding["id"]], evaluation_ids=[e1["id"]])
        assert pearson_lit["card"]["id"] in pearson_framework["literature_evidence_ids"]
        pearson_package = writer.build_fact_package(task_id=TASK, framework_id=pearson_framework["id"], hypothesis_ids=[h1["id"]], finding_ids=[pearson_finding["id"]], literature_evidence_ids=[pearson_lit["card"]["id"]])
        assert pearson_package["source_snapshot"]["analysis_result_ids"] == [pearson_result["id"]]
        pearson_draft = writer.generate(task_id=TASK, framework_id=pearson_framework["id"], section_type="main_findings", hypothesis_ids=[h1["id"]], finding_ids=[pearson_finding["id"]], literature_evidence_ids=[pearson_lit["card"]["id"]])
        pearson_hypothesis_draft = writer.generate(task_id=TASK, framework_id=pearson_framework["id"], section_type="hypothesis_discussion", hypothesis_ids=[h1["id"]], finding_ids=[pearson_finding["id"]])
        assert pearson_draft["id"] != pearson_hypothesis_draft["id"]
        assert writer.get(pearson_draft["id"])["status"] == "ready"  # Preview does not write the paper.
        assert not paper.load()["sections"][0]["paragraphs"]
        inserted_pearson = writer.insert(draft_id=pearson_draft["id"], section_id="4-1")
        assert inserted_pearson[0]["type"] == "discussion"
        assert inserted_pearson[0]["discussion"]["source_snapshot"] == pearson_draft["source_snapshot"]

        # Scenario 2: XLSX -> ANOVA -> Tukey evidence -> LiteratureEvidence -> comparison draft -> DOCX.
        anova_dataset = datasets.import_data(
            filename="anova.xlsx",
            raw=xlsx_bytes(["education", "satisfaction"], [["高中", value] for value in [40, 42, 41, 43, 39]] + [["本科", value] for value in [60, 62, 59, 61, 63]] + [["研究生", value] for value in [80, 82, 79, 81, 83]]),
            name="学历组间差异", task_id=TASK,
        )
        anova = analyses.create(task_id=TASK, dataset_id=anova_dataset["dataset_id"], dataset_version=1, analysis_type="anova", variables={"group_column": "education", "value_column": "satisfaction"}, name="ANOVA 组间差异")
        anova_result = analyses.run(anova["id"])
        h2 = hypotheses.create(task_id=TASK, title="H2", statement="不同学历群体的满意度存在差异。", direction="difference", analysis_ids=[anova["id"]])
        e2 = hypotheses.evaluate(hypothesis_id=h2["id"], analysis_id=anova["id"], analysis_result_id=anova_result["id"])
        assert e2["decision"] == "supported" and e2["evidence"]["tukey_significant_pairs"], e2
        anova_lit = evidence(literature, h2["id"], title="Education Group Difference", claim="不同教育背景的学习结果存在可比较的分组差异证据", source_location="metadata", source_text="公开题名与期刊元数据提供分组差异研究线索。")
        anova_framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[h2["id"]], evaluation_ids=[e2["id"]])
        anova_draft = writer.generate(task_id=TASK, framework_id=anova_framework["id"], section_type="literature_comparison", hypothesis_ids=[h2["id"]], literature_evidence_ids=[anova_lit["card"]["id"]])
        assert "公开元数据表明" in section_text(anova_draft, "literature_comparison")
        writer.insert(draft_id=anova_draft["id"], section_id="4-1")

        # Scenario 3: XLSX -> OLS -> Evaluation -> Discussion.  The evaluator must retain
        # model-level and individual predictor evidence separately rather than flattening them.
        regression_rows: list[list[float]] = []
        for index in range(1, 29):
            age, income, duration = float(index), float((index * 7) % 19 + 2), float((index * 5) % 11 + 1)
            satisfaction = 2.5 * age + 0.4 * income + 0.03 * duration + ((index % 3) - 1) * 0.25
            regression_rows.append([age, income, duration, satisfaction])
        regression_dataset = datasets.import_data(filename="ols.xlsx", raw=xlsx_bytes(["age", "income", "duration", "satisfaction"], regression_rows), name="满意度 OLS", task_id=TASK)
        regression = analyses.create(task_id=TASK, dataset_id=regression_dataset["dataset_id"], dataset_version=1, analysis_type="regression", variables={"dependent_variable": "satisfaction", "predictors": ["age", "income", "duration"]}, name="OLS 多元回归")
        regression_result = analyses.run(regression["id"])
        h3 = hypotheses.create(task_id=TASK, title="H3", statement="年龄、收入和使用时长与满意度预测有关。", direction="positive", variable_bindings={"predictors": ["age", "income", "duration"]}, analysis_ids=[regression["id"]])
        e3 = hypotheses.evaluate(hypothesis_id=h3["id"], analysis_id=regression["id"], analysis_result_id=regression_result["id"])
        predictor_evidence = e3["evidence"]["predictors"]
        assert "model_supported" in e3["evidence"] and len(predictor_evidence) == 3, e3
        assert "evaluated_predictors" in e3["evidence"] and isinstance(e3["evidence"]["model_supported"], bool)
        ols_lit = evidence(literature, h3["id"], title="Predictor Context", claim="用户记录了与预测变量相关的实践背景", source_location="user_note", source_text="用户记录：该实践场景可作为后续讨论背景。")
        ols_framework = hypotheses.create_framework(task_id=TASK, hypothesis_ids=[h3["id"]], evaluation_ids=[e3["id"]])
        ols_draft = writer.generate(task_id=TASK, framework_id=ols_framework["id"], section_type="hypothesis_discussion", hypothesis_ids=[h3["id"]], literature_evidence_ids=[ols_lit["card"]["id"]])
        ols_refs = ols_draft["sections"]["hypothesis_discussion"]["paragraphs"][0]["evidence_refs"]
        assert f"hypothesis_evaluation:{e3['id']}" in ols_refs and f"analysis_result:{regression_result['id']}" in ols_refs
        writer.insert(draft_id=ols_draft["id"], section_id="4-1")

        # DOCX export must render inserted DiscussionBlocks and dynamic citations from Literature IDs.
        files = paper.export()
        docx = next(Path(item) for item in files if item.endswith(".docx"))
        docx = docx if docx.is_absolute() else settings.output_dir / TASK / docx
        with ZipFile(docx) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        docx_text = html.unescape(re.sub(r"<[^>]+>", "", document_xml))
        assert "Learning Engagement Association" in docx_text
        assert "Education Group Difference" in docx_text
        assert "Predictor Context" in docx_text
        assert any(item.get("type") == "discussion" for item in paper.load()["sections"][0]["paragraphs"])
        links = DependencyGraphService(settings).rebuild_task(TASK)
        assert any(item["source_type"] == "discussion_framework" and item["target_type"] == "discussion_draft" for item in links)
        assert any(item["source_type"] == "discussion_draft" and item["target_type"] == "analysis_result" for item in links)
        print("Discussion Writer E2E passed")
        print({"pearson": pearson_draft["id"], "anova": anova_draft["id"], "ols": ols_draft["id"], "docx": str(docx), "discussion_blocks": len([item for item in paper.load()["sections"][0]["paragraphs"] if item.get("type") == "discussion"])})


if __name__ == "__main__":
    main()
