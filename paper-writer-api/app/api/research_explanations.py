from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.config import settings
from app.services.research_explanation_service import ResearchExplanationService

router = APIRouter(prefix="/api/research-assistant", tags=["research-assistant"])
class ExplainRequest(BaseModel):
    analysis_id: str = Field(..., pattern=r"^an_[A-Za-z0-9]+$")
    analysis_result_id: str = Field(..., pattern=r"^ar_[A-Za-z0-9]+$")
    model_id: str | None = Field(default=None, max_length=160)

@router.post("/explain")
def explain(body: ExplainRequest) -> dict:
    try:
        return ResearchExplanationService(settings).explain(analysis_id=body.analysis_id, analysis_result_id=body.analysis_result_id, model_id=body.model_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
