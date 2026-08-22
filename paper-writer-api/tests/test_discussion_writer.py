from pathlib import Path
from zipfile import ZipFile

import pytest
from unittest import mock

from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.discussion_writer_service import DiscussionWriterService
from app.services.hypothesis_service import HypothesisService
from app.services.literature_service import LiteratureService

TASK = "w" * 32


def settings_for(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "history.db", output_dir=tmp_path / "outputs", upload_dir=tmp_path / "uploads", log_dir=tmp_path / "logs")


def paper(settings: Settings) -> DraftService:
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({"title":"讨论写作测试","meta":{"major":"测试","paper_type":"课程论文","word_count":100,"reference_style":"gb7714","keywords":[]},"abstract":{"zh":"摘要","en":""},"keywords":{"zh":[],"en":[]},"acknowledgement":"","references":[],"sections":[{"id":"1-1","number":"1.1","title":"讨论","level":3,"gist":"","paragraphs":[]}]})
    return service


def chain(tmp_path: Path, *, user_note: bool = False):
    settings=settings_for(tmp_path); paper(settings); datasets=DatasetService(settings); analyses=AnalysisService(settings); hypotheses=HypothesisService(settings); literature=LiteratureService(settings)
    dataset=datasets.import_data(filename="source.csv",raw=b"x,y\n1,2\n2,4\n3,6\n4,8\n5,10\n6,12\n",name="讨论数据",task_id=TASK)
    analysis=analyses.create(task_id=TASK,dataset_id=dataset["dataset_id"],dataset_version=1,analysis_type="pearson",variables={"x":"x","y":"y"},name="X 与 Y")
    result=analyses.run(analysis["id"])
    hypothesis=hypotheses.create(task_id=TASK,title="H1",statement="X 与 Y 呈正向关联。",direction="positive",analysis_ids=[analysis["id"]])
    evaluation=hypotheses.evaluate(hypothesis_id=hypothesis["id"],analysis_id=analysis["id"],analysis_result_id=result["id"])
    metadata={"title":"Supporting learning association","authors":["Zhang Wei","Li Na","Wang Yu"],"year":2024,"journal":"Open Education","doi":"10.9999/test.1","url":"https://doi.org/10.9999/test.1","abstract":"The abstract reports a positive association between learning engagement and satisfaction.","source":"crossref","source_id":"x","external_id":"10.9999/test.1","user_note":"用户记录：该研究与本研究背景相关。" if user_note else ""}
    item=literature.save(task_id=TASK,metadata=metadata)
    source="user_note" if user_note else "abstract"; excerpt=metadata["user_note"] if user_note else "positive association between learning engagement and satisfaction"
    evidence=literature.add_evidence(literature_id=item["id"],claim="学习参与和满意度存在相关证据",evidence=excerpt,source_location=source)
    literature.link_hypothesis(task_id=TASK,hypothesis_id=hypothesis["id"],literature_id=item["id"],relation="supporting")
    framework=hypotheses.create_framework(task_id=TASK,hypothesis_ids=[hypothesis["id"]],evaluation_ids=[evaluation["id"]])
    return settings,datasets,analyses,hypotheses,literature,analysis,result,hypothesis,evaluation,item,evidence,framework


def generate(tmp_path: Path, section: str, **kwargs):
    *values, framework = chain(tmp_path)
    settings=values[0]; writer=DiscussionWriterService(settings)
    return writer, writer.generate(task_id=TASK,framework_id=framework["id"],section_type=section,**kwargs), values, framework


@pytest.mark.parametrize("section",["main_findings","hypothesis_discussion","literature_comparison","possible_explanations","theoretical_implications","practical_implications","limitations"])
def test_all_discussion_sections_generate(tmp_path,section):
    writer,draft,_,_=generate(tmp_path,section,research_context="学习环境可能不同",practical_context="教学支持设计")
    assert draft["status"] == "ready" and draft["sections"][section]["paragraphs"] and writer.get(draft["id"])["id"]==draft["id"]


def test_fact_package_has_required_snapshot_and_no_unselected_literature(tmp_path):
    settings,*_,hypothesis,evaluation,item,evidence,framework=chain(tmp_path)
    package=DiscussionWriterService(settings).build_fact_package(task_id=TASK,framework_id=framework["id"],hypothesis_ids=[hypothesis["id"]],literature_evidence_ids=[evidence["id"]])
    assert package["source_snapshot"]["analysis_result_ids"] and package["source_snapshot"]["data_fingerprints"] and package["source_snapshot"]["literature_evidence_ids"]==[evidence["id"]]
    with pytest.raises(ValueError,match="不能引用"):
        DiscussionWriterService(settings).build_fact_package(task_id=TASK,framework_id=framework["id"],literature_evidence_ids=["le_"+"a"*16])


def test_numeric_tampering_rejected(tmp_path):
    writer,draft,_,_=generate(tmp_path,"main_findings")
    with pytest.raises(ValueError,match="数字"):
        writer._validate_model([{"text":"相关系数为 999。","evidence_refs":[]}],draft["fact_package"])


def test_wrong_hypothesis_decision_rejected_from_model(tmp_path):
    writer,draft,_,_=generate(tmp_path,"hypothesis_discussion")
    ref=draft["sections"]["hypothesis_discussion"]["paragraphs"][0]["evidence_refs"]
    with pytest.raises(ValueError,match="决策"):
        writer._validate_model([{"text":"该假设获得统计支持。","evidence_refs":ref}],draft["fact_package"])


def test_causal_model_phrase_rejected(tmp_path):
    writer,draft,_,_=generate(tmp_path,"possible_explanations")
    with pytest.raises(ValueError,match="因果"):
        writer._validate_model([{"text":"学习参与导致满意度提升。","evidence_refs":[]}],draft["fact_package"])


def test_abstract_source_level_is_disclosed(tmp_path):
    _,draft,_,_=generate(tmp_path,"literature_comparison")
    text=draft["sections"]["literature_comparison"]["paragraphs"][0]["text"]
    assert "摘要显示" in text and "阅读全文" in text


def test_metadata_source_level_is_not_claimed_as_finding(tmp_path):
    settings,*values,framework=chain(tmp_path)
    writer=DiscussionWriterService(settings); package=writer.build_fact_package(task_id=TASK,framework_id=framework["id"])
    package["literature_evidence"][0]["evidence"]["source_location"]="metadata"
    text=writer._rule_paragraphs("literature_comparison",package,"standard")[0]["text"]
    assert "公开元数据表明" in text and "研究发现" not in text


def test_user_note_source_level_is_disclosed(tmp_path):
    settings,*values,framework=chain(tmp_path,user_note=True)
    draft=DiscussionWriterService(settings).generate(task_id=TASK,framework_id=framework["id"],section_type="literature_comparison")
    assert "根据用户记录" in draft["sections"]["literature_comparison"]["paragraphs"][0]["text"]


def test_model_unavailable_uses_rule_fallback(tmp_path):
    # Test semantics must not depend on a developer machine's configured default model.
    with mock.patch("app.services.discussion_writer_service.resolve_model", return_value=None):
        _,draft,_,_=generate(tmp_path,"hypothesis_discussion",model_id=None)
    assert draft["provider"]=="rule_based_fallback" and draft["sections"]["hypothesis_discussion"]["paragraphs"]


def test_multiple_drafts_do_not_overwrite_versions(tmp_path):
    writer,one,values,framework=generate(tmp_path,"main_findings")
    two=writer.generate(task_id=TASK,framework_id=framework["id"],section_type="main_findings",style={"length":"detailed"})
    assert one["id"]!=two["id"] and len(writer.list(TASK,framework["id"]))==2


def test_evidence_refs_are_real_and_task_scoped(tmp_path):
    _,draft,_,_=generate(tmp_path,"hypothesis_discussion")
    refs=draft["sections"]["hypothesis_discussion"]["paragraphs"][0]["evidence_refs"]
    assert any(item.startswith("hypothesis_evaluation:") for item in refs) and any(item.startswith("analysis_result:") for item in refs)


def test_discussion_block_requires_explicit_insert_and_has_snapshot(tmp_path):
    writer,draft,values,_=generate(tmp_path,"literature_comparison")
    settings=values[0]; blocks=writer.insert(draft_id=draft["id"],section_id="1-1")
    block=blocks[0]; assert block["type"]=="discussion" and block["discussion"]["discussion_draft_id"]==draft["id"] and block["discussion"]["source_snapshot"]==draft["source_snapshot"]
    assert any(item.get("type")=="discussion" for item in DraftService(TASK,settings.output_dir/TASK).load()["sections"][0]["paragraphs"])


def test_discussion_block_docx_dynamic_citation(tmp_path):
    writer,draft,values,_=generate(tmp_path,"literature_comparison")
    settings=values[0]; writer.insert(draft_id=draft["id"],section_id="1-1")
    files=DraftService(TASK,settings.output_dir/TASK).export(); docx=next(Path(item) for item in files if item.endswith(".docx")); docx=docx if docx.is_absolute() else settings.output_dir/TASK/docx
    with ZipFile(docx) as archive: xml=archive.read("word/document.xml").decode("utf-8")
    assert "Zhang" in xml and "Supporting learning association" in xml


def test_stale_after_dataset_update(tmp_path):
    writer,draft,values,_=generate(tmp_path,"main_findings")
    settings,datasets,*_=values
    old=draft["fact_package"]["analysis_results"][0]
    datasets.import_data(filename="source-v2.csv",raw=b"x,y\n1,3\n2,5\n3,7\n4,9\n5,11\n6,13\n",name="讨论数据",task_id=TASK,dataset_id=old["dataset_id"])
    assert writer.get(draft["id"])["status"]=="stale"


def test_missing_literature_becomes_stale_not_rewritten(tmp_path):
    writer,draft,values,_=generate(tmp_path,"literature_comparison")
    literature=values[4]; literature.delete(draft["fact_package"]["literature_evidence"][0]["literature"]["id"])
    assert writer.get(draft["id"])["status"]=="stale" and writer._raw(draft["id"])["id"]==draft["id"]


def test_dependency_graph_links_discussion_draft(tmp_path):
    writer,draft,values,_=generate(tmp_path,"hypothesis_discussion")
    links=DependencyGraphService(values[0]).rebuild_task(TASK)
    assert any(item["source_type"]=="discussion_framework" and item["target_type"]=="discussion_draft" and item["target_id"]==draft["id"] for item in links)
    assert any(item["source_type"]=="discussion_draft" and item["target_type"]=="analysis_result" for item in links)


def test_unselected_finding_is_rejected(tmp_path):
    settings,*_,framework=chain(tmp_path)
    with pytest.raises(ValueError,match="ResearchFinding"):
        DiscussionWriterService(settings).build_fact_package(task_id=TASK,framework_id=framework["id"],finding_ids=["rf_"+"a"*16])
