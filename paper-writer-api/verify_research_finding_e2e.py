from pathlib import Path
import shutil, zipfile
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.analysis_service import AnalysisService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_finding_service import ResearchFindingService
from app.draft.service import DraftService
root=Path(__file__).resolve().parent/"verification_research_finding_e2e"; shutil.rmtree(root,ignore_errors=True)
s=Settings(db_path=root/"data"/"history.db",output_dir=root/"outputs",upload_dir=root/"uploads",log_dir=root/"logs"); task="f"*32
d=DatasetService(s).import_data(filename="x.csv",raw="组,值\nA,1\nA,2\nB,8\nB,9\nC,15\nC,16\n".encode(),name="e2e",task_id=task); ds=DraftService(task,s.output_dir/task); doc=ds.build({"title":"验收","major":"m","paper_type":"p","word_count":100,"reference_style":"gb","abstract":"a","keywords":[],"references":[]}); sec=doc["sections"][-1]; ds.save(doc)
a=AnalysisService(s); an=a.create(task_id=task,dataset_id=d["dataset_id"],dataset_version=1,analysis_type="anova",variables={"group_column":"组","value_column":"值"}); r=a.run(an["id"]); ex=ResearchExplanationService(s).explain(analysis_id=an["id"],analysis_result_id=r["id"]); f=ResearchFindingService(s).generate(task_id=task,analysis_id=an["id"],analysis_result_id=r["id"],explanation_id=ex["id"],style={"length":"standard"}); block=ResearchFindingService(s).insert(finding_id=f["id"],section_id=sec["id"]); ds.export(); assert block["research_finding"]["data_fingerprint"]==r["data_fingerprint"]
with zipfile.ZipFile(s.output_dir/task/"论文.docx") as z: assert "word/document.xml" in z.namelist()
print({"finding_id":f["id"],"analysis_result_id":r["id"],"docx":str(s.output_dir/task/"论文.docx")})
