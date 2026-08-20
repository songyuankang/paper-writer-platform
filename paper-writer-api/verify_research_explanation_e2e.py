from __future__ import annotations
import json, shutil
from pathlib import Path
from openpyxl import Workbook
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.analysis_service import AnalysisService
from app.services.research_explanation_service import ResearchExplanationService

def main():
 root=Path(__file__).resolve().parent/"verification_research_explanation_e2e"
 if root.exists(): shutil.rmtree(root)
 s=Settings(db_path=root/"data"/"history.db",output_dir=root/"outputs",upload_dir=root/"uploads",log_dir=root/"logs")
 wb=Workbook(); ws=wb.active; ws.title="调查数据"; ws.append(["学历","年龄","收入","满意度"])
 for row in [["本科",22,3,51],["本科",24,5,55],["硕士",29,7,72],["硕士",31,8,75],["博士",35,11,88],["博士",39,13,92]]: ws.append(row)
 source=root/"source.xlsx"; source.parent.mkdir(parents=True); wb.save(source)
 datasets=DatasetService(s); staged=datasets.stage_upload(filename="source.xlsx",raw=source.read_bytes()); dataset=datasets.import_staged(staged["import_token"],filename=staged["filename"],sheet="调查数据",name="解释验收样本",task_id="d"*32)
 analyses=AnalysisService(s); explain=ResearchExplanationService(s); out=[]
 for typ,variables in [("anova",{"group_column":"学历","value_column":"满意度"}),("regression",{"dependent_variable":"满意度","predictors":["年龄","收入"]})]:
  analysis=analyses.create(task_id="d"*32,dataset_id=dataset["dataset_id"],dataset_version=1,analysis_type=typ,variables=variables); result=analyses.run(analysis["id"]); explanation=explain.explain(analysis_id=analysis["id"],analysis_result_id=result["id"])
  facts=" ".join(item["text"] for item in explanation["statistical_facts"])
  assert result["data_fingerprint"]==explanation["data_fingerprint"] and facts
  out.append({"analysis_type":typ,"analysis_id":analysis["id"],"result_id":result["id"],"explanation_id":explanation["id"],"provider":explanation["provider"],"facts":explanation["statistical_facts"]})
 print(json.dumps({"dataset_id":dataset["dataset_id"],"dataset_version":1,"explanations":out},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
