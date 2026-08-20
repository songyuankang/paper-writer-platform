from __future__ import annotations
import json, re, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from app.config import Settings
from app.draft.service import DraftService
from app.services.analysis_service import AnalysisService
from app.services.research_explanation_service import ResearchExplanationService
from app.services.research_object_service import ResearchObjectService

def now(): return datetime.now(timezone.utc).isoformat()
class ResearchFindingService:
 def __init__(self,settings:Settings): self.settings=settings; self.analyses=AnalysisService(settings); self.explanations=ResearchExplanationService(settings); self.objects=ResearchObjectService(settings); self.root=settings.db_path.parent/"findings"; self.root.mkdir(parents=True,exist_ok=True)
 def _path(self,fid:str):
  if not re.fullmatch(r"rf_[A-Za-z0-9]+",fid): raise ValueError("Finding ID 无效")
  return self.root/f"{fid}.json"
 def _load_explanation(self,analysis_id:str,eid:str):
  p=self.explanations._path(analysis_id,eid)
  if not p.is_file(): raise ValueError("未找到已验证的 Explanation")
  return json.loads(p.read_text(encoding="utf-8"))
 def _references(self,task_id:str,result_id:str):
  # Synchronise domain-owned numbers before a Finding captures its real table/figure references.
  self.objects.renumber_document_references(task_id)
  service=DraftService(task_id,self.settings.output_dir/task_id); draft=service.load(); tables=[]; figures=[]
  object_index={(item["type"],item["source_id"]):item["id"] for item in self.objects.list(task_id)}
  for section in draft.get("sections",[]):
   for block in section.get("paragraphs",[]):
    ref=block.get("analysis") or {}
    if ref.get("analysis_result_id")!=result_id: continue
    kind="figure" if block.get("type") in {"chart","figure"} else "table" if block.get("type")=="table" else ""
    if not kind: continue
    try: number=int(block.get("figure_number" if kind=="figure" else "table_number"))
    except (TypeError,ValueError): number=None
    prefix="图" if kind=="figure" else "表"
    title=block.get("title") or ""
    entry={"id":block.get("id"),"research_object_id":object_index.get((kind,str(block.get("id")))),"number":number,"label":f"{prefix}{number} {title}" if number else (title or block.get("id")),"title":title}
    (figures if kind=="figure" else tables).append(entry)
  return tables,figures
 def generate(self,*,task_id:str,analysis_id:str,analysis_result_id:str,explanation_id:str,style:dict[str,Any]|None=None):
  analysis=self.analyses.get(analysis_id); result=self.analyses.get_result(analysis_id,analysis_result_id); explanation=self._load_explanation(analysis_id,explanation_id)
  if result.get("analysis_id")!=analysis_id or explanation.get("analysis_result_id")!=analysis_result_id: raise ValueError("Explanation 与 AnalysisResult 不匹配")
  for key in ("dataset_id","dataset_version_id","data_fingerprint"):
   if explanation.get(key)!=result.get(key): raise ValueError("Explanation 与 AnalysisResult 数据版本不匹配")
  tables,figures=self._references(task_id,analysis_result_id); facts=[item["text"] for item in explanation.get("statistical_facts",[]) if item.get("source")=="analysis_result"]
  if not facts: raise ValueError("Explanation 没有已验证统计事实")
  style=style or {}; mode=str(style.get("length") or "standard"); intro={"concise":"结果如下。","standard":"研究结果表明，","detailed":"基于当前 DatasetVersion 的真实统计计算，研究结果表明，"}.get(mode,"研究结果表明，")
  refs=[]
  if tables: refs.append(f"如{tables[0]['label']}所示")
  if figures: refs.append(f"如{figures[0]['label']}所示")
  paragraphs=[intro+facts[0]]
  if explanation.get("interpretation"): paragraphs.append(" ".join(explanation["interpretation"]))
  if len(facts)>1 and mode!="concise": paragraphs.append(" ".join(facts[1:]))
  if refs: paragraphs.append("，".join(refs)+"。")
  if explanation.get("limitations"): paragraphs.append("结果解释需结合以下限制："+"；".join(explanation["limitations"]) + "。")
  finding={"id":f"rf_{uuid.uuid4().hex[:16]}","task_id":task_id,"analysis_id":analysis_id,"analysis_result_id":analysis_result_id,"explanation_id":explanation_id,"dataset_id":result["dataset_id"],"dataset_version":result["dataset_version"],"dataset_version_id":result["dataset_version_id"],"data_fingerprint":result["data_fingerprint"],"title":f"{analysis.get('name') or '统计分析'}结果","paragraphs":paragraphs,"table_references":tables,"figure_references":figures,"research_object_ids":[item["research_object_id"] for item in [*tables,*figures] if item.get("research_object_id")],"style":{"paper_style":style.get("paper_style") or "undergraduate","tone":style.get("tone") or "formal","length":mode},"fact_package":{"analysis":{"type":analysis["type"],"variables":analysis.get("variables"),"parameters":analysis.get("parameters")},"statistics":facts,"explanation":explanation.get("interpretation",[]),"tables":tables,"figures":figures},"provider":"controlled_rule_renderer","status":"draft","created_at":now()}
  self._path(finding["id"]).write_text(json.dumps(finding,ensure_ascii=False,indent=2),encoding="utf-8"); return finding
 def get(self,fid:str):
  p=self._path(fid)
  if not p.is_file(): raise ValueError("未找到 ResearchFinding")
  return json.loads(p.read_text(encoding="utf-8"))
 def insert(self,*,finding_id:str,section_id:str):
  finding=self.get(finding_id); service=DraftService(finding["task_id"],self.settings.output_dir/finding["task_id"])
  with service.lock:
   draft=service.load(); section=service._find_section(draft,section_id)
   block={"id":service._next_paragraph_id(section),"type":"finding","text":"\n\n".join(finding["paragraphs"]),"title":finding["title"],"research_finding":{"finding_id":finding_id,"analysis_id":finding["analysis_id"],"analysis_result_id":finding["analysis_result_id"],"explanation_id":finding["explanation_id"],"dataset_id":finding["dataset_id"],"dataset_version_id":finding["dataset_version_id"],"data_fingerprint":finding["data_fingerprint"],"research_object_ids":finding.get("research_object_ids",[])},"generated_at":now()}
   section.setdefault("paragraphs",[]).append(block); service.save(draft)
  finding["status"]="inserted"; finding["inserted_block_id"]=block["id"]; finding["inserted_at"]=now(); self._path(finding_id).write_text(json.dumps(finding,ensure_ascii=False,indent=2),encoding="utf-8"); return block
