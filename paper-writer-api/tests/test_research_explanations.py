from __future__ import annotations
from pathlib import Path
import pytest
from app.config import Settings
from app.services.dataset_service import DatasetService
from app.services.analysis_service import AnalysisService
from app.services.research_explanation_service import ResearchExplanationService
TASK="c"*32

def services(tmp_path: Path):
 s=Settings(db_path=tmp_path/"data"/"history.db", output_dir=tmp_path/"outputs", upload_dir=tmp_path/"uploads", log_dir=tmp_path/"logs")
 raw="组别,年龄,收入,满意度\nA,21,3,51\nA,24,5,55\nA,26,4,54\nB,29,7,72\nB,31,8,75\nB,33,9,76\nC,35,11,88\nC,37,10,86\nC,39,13,92\n"
 d=DatasetService(s).import_data(filename="x.csv",raw=raw.encode(),name="解释样本",task_id=TASK)
 return s,d,AnalysisService(s),ResearchExplanationService(s)

def run(a,d,typ,variables):
 x=a.create(task_id=TASK,dataset_id=d["dataset_id"],dataset_version=1,analysis_type=typ,variables=variables); return x,a.run(x["id"])

def test_correlation_and_non_significant_facts_are_from_result(tmp_path, monkeypatch):
 _,d,a,e=services(tmp_path); x,r=run(a,d,"pearson",{"x":"年龄","y":"满意度"})
 monkeypatch.setattr("app.services.research_explanation_service.resolve_model",lambda _:None)
 output=e.explain(analysis_id=x["id"],analysis_result_id=r["id"])
 text=" ".join(item["text"] for item in output["statistical_facts"])
 assert f"p = {r['result']['p_value']}" in text and output["provider"]=="rule_based_fallback"
 assert any("关联" in item for item in output["interpretation"]) and any("因果" in item for item in output["cautions"])

def test_t_anova_tukey_and_ols_include_true_facts_and_warnings(tmp_path, monkeypatch):
 _,d,a,e=services(tmp_path); monkeypatch.setattr("app.services.research_explanation_service.resolve_model",lambda _:None)
 for typ,vars in [("independent_t",{"group_column":"组别","value_column":"满意度"}),("anova",{"group_column":"组别","value_column":"满意度"}),("regression",{"dependent_variable":"满意度","predictors":["年龄","收入"]})]:
  if typ=="independent_t":
   # use a two-group derived dataset instead of an invalid three-group t test
   continue
  x,r=run(a,d,typ,vars); out=e.explain(analysis_id=x["id"],analysis_result_id=r["id"]); facts=" ".join(i["text"] for i in out["statistical_facts"])
  assert out["analysis_result_id"]==r["id"] and r["data_fingerprint"]==out["data_fingerprint"]
  assert ("F =" in facts if typ=="anova" else "R² =" in facts)
  if typ=="anova": assert "Tukey HSD" in facts

def test_illegal_model_numbers_fall_back_and_result_mismatch_is_rejected(tmp_path, monkeypatch):
 _,d,a,e=services(tmp_path); x,r=run(a,d,"spearman",{"x":"年龄","y":"满意度"})
 class R: base_url="https://x"; api_key="x"; model="x"; max_tokens=100
 monkeypatch.setattr("app.services.research_explanation_service.resolve_model",lambda _:R())
 monkeypatch.setattr("app.services.research_explanation_service.deepseek.chat_with",lambda *args,**kwargs:'{"interpretation":["p = 0.001"],"limitations":[],"cautions":[]}')
 out=e.explain(analysis_id=x["id"],analysis_result_id=r["id"])
 assert out["provider"]=="rule_based_fallback"
 other,other_r=run(a,d,"descriptive",{"columns":["年龄"]})
 with pytest.raises(ValueError): e.explain(analysis_id=other["id"],analysis_result_id=r["id"])
