"""论文修改接口请求模型。"""

from typing import Literal

from pydantic import BaseModel, Field

ChapterChangeType = Literal["regenerate", "expand", "condense", "custom"]
ParagraphChangeType = Literal["polish", "expand", "rewrite", "delete"]


class ReviseChapterRequest(BaseModel):
    task_id: str
    chapter_id: str = Field(..., description="章节编号（1 起）或章节 id")
    instruction: str = Field(..., min_length=1, max_length=1000, description="修改要求")
    change_type: ChapterChangeType = Field("custom", description="操作类型")
    model_id: str | None = Field(None, description="指定使用的模型")


class ReviseParagraphRequest(BaseModel):
    task_id: str
    paragraph_id: str = Field(..., description="段落 id（如 ch1-p2）")
    instruction: str = Field(..., min_length=1, max_length=1000, description="修改要求")
    change_type: ParagraphChangeType = Field("polish", description="操作类型")
    model_id: str | None = Field(None, description="指定使用的模型")


class AnalyzeRequest(BaseModel):
    task_id: str


class RestoreRequest(BaseModel):
    task_id: str
    version_number: int = Field(..., ge=1)
