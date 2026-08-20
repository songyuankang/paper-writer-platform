from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.services.literature_service import LiteratureService

router = APIRouter(tags=["research-literature"])


def service() -> LiteratureService: return LiteratureService(settings)
def problem(exc: ValueError, status: int = 422) -> HTTPException: return HTTPException(status_code=status, detail=str(exc))


class SearchInput(BaseModel):
    query: str = ""; title: str = ""; author: str = ""; year_from: int | None = None; year_to: int | None = None; doi: str = ""
    sources: list[str] = Field(default_factory=lambda: ["crossref", "openalex"]); limit: int = 12
class SaveInput(BaseModel): task_id: str; metadata: dict[str, Any]
class LiteraturePatch(BaseModel):
    title: str | None = None; authors: list[str] | None = None; year: int | None = None; journal: str | None = None; volume: str | None = None; issue: str | None = None; pages: str | None = None; doi: str | None = None; url: str | None = None; abstract: str | None = None; publisher: str | None = None; keywords: list[str] | None = None; user_note: str | None = None
class EvidenceInput(BaseModel): claim: str; evidence: str; source_location: str; confidence: str = "user_confirmed"
class HypothesisLinkInput(BaseModel): task_id: str; literature_id: str; relation: str
class CitationInput(BaseModel): task_id: str; literature_id: str; style: str = "author_year"; section_id: str | None = None; prefix: str = ""; suffix: str = ""


@router.post("/api/research/literature/search")
def search_literature(payload: SearchInput):
    try: return service().searcher.search(**payload.model_dump())
    except ValueError as exc: raise problem(exc) from exc
@router.get("/api/research/literature")
def list_literature(task_id: str = Query(..., min_length=1)):
    try: return {"literature": service().list(task_id)}
    except ValueError as exc: raise problem(exc) from exc
@router.get("/api/research/literature/{literature_id}")
def get_literature(literature_id: str):
    try:
        item=service().get(literature_id); return {**item,"evidence":service().evidence(literature_id),"hypothesis_links":service().literature_links(item["task_id"],literature_id),"citations":service().citations(item["task_id"])}
    except ValueError as exc: raise problem(exc,404) from exc
@router.post("/api/research/literature/save")
def save_literature(payload: SaveInput):
    try: return service().save(**payload.model_dump())
    except ValueError as exc: raise problem(exc) from exc
@router.patch("/api/research/literature/{literature_id}")
def patch_literature(literature_id: str,payload: LiteraturePatch):
    try: return service().update(literature_id,{key:value for key,value in payload.model_dump().items() if value is not None})
    except ValueError as exc: raise problem(exc) from exc
@router.delete("/api/research/literature/{literature_id}")
def delete_literature(literature_id: str):
    try: return service().delete(literature_id)
    except ValueError as exc: raise problem(exc,404) from exc
@router.post("/api/research/literature/{literature_id}/evidence")
def add_literature_evidence(literature_id: str,payload: EvidenceInput):
    try: return service().add_evidence(literature_id=literature_id,**payload.model_dump())
    except ValueError as exc: raise problem(exc) from exc
@router.get("/api/research/literature/{literature_id}/evidence")
def literature_evidence(literature_id: str):
    try: return {"evidence":service().evidence(literature_id)}
    except ValueError as exc: raise problem(exc,404) from exc
@router.post("/api/research/hypotheses/{hypothesis_id}/literature")
def link_hypothesis_literature(hypothesis_id: str,payload: HypothesisLinkInput):
    try: return service().link_hypothesis(task_id=payload.task_id,hypothesis_id=hypothesis_id,literature_id=payload.literature_id,relation=payload.relation)
    except ValueError as exc: raise problem(exc) from exc
@router.delete("/api/research/hypotheses/{hypothesis_id}/literature/{literature_id}")
def unlink_hypothesis_literature(hypothesis_id: str,literature_id: str,task_id: str=Query(...)):
    try: service().unlink_hypothesis(task_id=task_id,hypothesis_id=hypothesis_id,literature_id=literature_id); return {"ok":True}
    except ValueError as exc: raise problem(exc) from exc
@router.get("/api/research/hypotheses/{hypothesis_id}/literature")
def hypothesis_literature(hypothesis_id: str,task_id: str=Query(...)):
    try: return {"items":service().hypothesis_literature(task_id,hypothesis_id)}
    except ValueError as exc: raise problem(exc) from exc
@router.post("/api/research/literature/citations")
def create_literature_citation(payload: CitationInput):
    try:
        if payload.section_id: return service().insert_citation(task_id=payload.task_id,section_id=payload.section_id,literature_id=payload.literature_id,prefix=payload.prefix,suffix=payload.suffix)
        return {"citation":service().create_citation(task_id=payload.task_id,literature_id=payload.literature_id,style=payload.style)}
    except ValueError as exc: raise problem(exc) from exc
@router.get("/api/research/literature/citations")
def list_literature_citations(task_id: str=Query(...)):
    try: return {"citations":service().citations(task_id)}
    except ValueError as exc: raise problem(exc) from exc
