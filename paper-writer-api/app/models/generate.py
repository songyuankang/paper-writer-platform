"""Request and response models for paper generation APIs."""
from typing import Literal
from pydantic import BaseModel, Field

PaperType = Literal["\u8bfe\u7a0b\u8bba\u6587", "\u6bd5\u4e1a\u8bba\u6587", "\u671f\u520a\u8bba\u6587", "\u5b9e\u8bc1\u7814\u7a76", "\u6587\u732e\u7efc\u8ff0", "\u5f00\u9898\u62a5\u544a"]
ReferenceStyle = Literal["gb7714", "apa", "mla", "chicago"]
GenerationMode = Literal["auto", "outline"]
GenerationStrategy = Literal["section", "single"]

class ChartConfig(BaseModel):
    enabled: bool = Field(True)
    count: int = Field(1, ge=1, le=20)
    types: list[str] = Field(default_factory=list)

class MaterialFile(BaseModel):
    kind: str = Field("other")
    filename: str = Field(...)
    path: str = Field("")
    text: str = Field("")

class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: PaperType = Field("course")
    word_count: int = Field(3000, ge=500, le=100000)
    chart_enabled: bool = Field(False)
    reference_style: ReferenceStyle = Field("gb7714")
    outline: str | None = Field(None)
    generation_mode: GenerationMode = Field("auto")
    chart_config: ChartConfig | None = Field(None)
    special_requirements: str | None = Field(None, max_length=10000)
    materials: list[MaterialFile] = Field(default_factory=list)
    abstract: str | None = Field(None, max_length=20000)
    keywords: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    draft_mode: bool = Field(False)
    generation_strategy: GenerationStrategy = Field("section")
    template_id: str = Field("", max_length=100)
    model_id: str | None = Field(None)

class OutlineRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: PaperType = Field("course")
    word_count: int = Field(3000, ge=500, le=100000)
    special_requirements: str | None = Field(None, max_length=10000)
    references: list[str] = Field(default_factory=list)
    model_id: str | None = Field(None)

class AbstractRequest(BaseModel):
    """创建向导第②步的摘要生成请求。

    摘要在大纲生成之前执行，因此 outline 只能是可选上下文；
    前端会传递 special_requirements，必须在此模型中明确保留。
    """

    title: str = Field(..., min_length=1, max_length=200)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: PaperType = Field("course")
    word_count: int = Field(3000, ge=500, le=100000)
    outline: str = Field("", max_length=20000)
    keywords: list[str] = Field(default_factory=list)
    special_requirements: str | None = Field(None, max_length=2000)
    model_id: str | None = Field(None)

class ReferenceSearchRequest(BaseModel):
    """创建向导第③步的真实参考文献检索请求。"""

    query: str | None = Field(None, max_length=500)
    title: str | None = Field(None, max_length=500)
    keywords: list[str] = Field(default_factory=list)
    limit: int = Field(12, ge=1, le=20)

class OutlineChapter(BaseModel):
    title: str = Field("", max_length=200)
    level: int = Field(1, ge=1, le=3)
    word_count: int = Field(0, ge=0)

class OutlineResponse(BaseModel):
    outline: str
    chapters: list[OutlineChapter]
