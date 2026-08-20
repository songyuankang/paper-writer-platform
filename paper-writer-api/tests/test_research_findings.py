from pathlib import Path
import pytest
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.analysis_service import AnalysisService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService
from app.draft.service import DraftService
TASK="e"*32
def test_finding_preview_versions_and_insert(tmp_path:Path):
 s=Settings(db_path=tmp_path/"data"/"history.db",output_dir=tmp_path/"outputs",upload_dir=tmp_path/"uploads",log_dir=tmp_path/"logs")
 d=DatasetService(s).import_data(filename="a.csv",raw=b"x,y\n1,2\n2,4\n3,7\n4,8\n",name="d",task_id=TASK); a=AnalysisService(s); an=a.create(task_id=TASK,dataset_id=d["dataset_id"],dataset_version=1,analysis_type="pearson",variables={"x":"x","y":"y"}); r=a.run(an["id"]); ex=ResearchExplanationService(s).explain(analysis_id=an["id"],analysis_result_id=r["id"])
 draft=DraftService(TASK,s.output_dir/TASK); doc=draft.build({"title":"t","major":"m","paper_type":"p","word_count":100,"reference_style":"gb","abstract":"a","keywords":[],"references":[]}); section=doc["sections"][-1]; draft.save(doc)
 f=ResearchFindingService(s); one=f.generate(task_id=TASK,analysis_id=an["id"],analysis_result_id=r["id"],explanation_id=ex["id"],style={"length":"standard"}); two=f.generate(task_id=TASK,analysis_id=an["id"],analysis_result_id=r["id"],explanation_id=ex["id"],style={"length":"concise"}); assert one["id"]!=two["id"] and any("p =" in p for p in one["paragraphs"])
 block=f.insert(finding_id=one["id"],section_id=section["id"]); assert block["type"]=="finding" and block["research_finding"]["data_fingerprint"]==r["data_fingerprint"]
 with pytest.raises(ValueError): f.generate(task_id=TASK,analysis_id=an["id"],analysis_result_id=r["id"],explanation_id="ex_missing",style={})
