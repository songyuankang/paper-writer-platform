from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.config import settings
from app.services.research_finding_service import ResearchFindingService
router=APIRouter(prefix="/api/research-findings",tags=["research-findings"])
class Generate(BaseModel):
 task_id:str=Field(...,min_length=32,max_length=32); analysis_id:str; analysis_result_id:str; explanation_id:str; style:dict=Field(default_factory=dict)
class Insert(BaseModel): section_id:str=Field(...,min_length=1)
def svc(): return ResearchFindingService(settings)
@router.get("")
def list_findings(task_id:str):
 try: return {"findings":svc().list(task_id)}
 except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
@router.post("")
def generate(body:Generate):
 try: return svc().generate(task_id=body.task_id,analysis_id=body.analysis_id,analysis_result_id=body.analysis_result_id,explanation_id=body.explanation_id,style=body.style)
 except (ValueError,FileNotFoundError) as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
@router.get("/{finding_id}")
def get(finding_id:str):
 try: return svc().get(finding_id)
 except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
@router.post("/{finding_id}/insert")
def insert(finding_id:str,body:Insert):
 try: return {"block":svc().insert(finding_id=finding_id,section_id=body.section_id)}
 except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
