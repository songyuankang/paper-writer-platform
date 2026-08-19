"""Request and response models for paper generation APIs."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PaperType = Literal["课程论文", "毕业论文", "期刊论文", "实证研究", "文献综述", "开题报告"]
ReferenceStyle = Literal["gb7714", "apa", "mla", "chicago"]
GenerationMode = Literal["auto", "outline"]
GenerationStrategy = Literal["section", "single"]


class MaterialFile(BaseModel):
    kind: str = Field("other")
    filename: str = Field(...)
    path: str = Field("")
    text: str = Field("")


class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: PaperType = Field("课程论文")
    word_count: int = Field(3000, ge=500, le=100000)
    reference_style: ReferenceStyle = Field("gb7714")
    outline: str | None = Field(None)
    generation_mode: GenerationMode = Field("auto")
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
    paper_type: PaperType = Field("课程论文")
    word_count: int = Field(3000, ge=500, le=100000)
    special_requirements: str | None = Field(None, max_length=10000)
    references: list[str] = Field(default_factory=list)
    model_id: str | None = Field(None)


class AbstractRequest(BaseModel):
    """创建向导第②步的摘要生成请求。"""

    title: str = Field(..., min_length=1, max_length=200)
    major: str = Field(..., min_length=1, max_length=100)
    paper_type: PaperType = Field("课程论文")
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


ManualReferenceType = Literal[
    "journal", "thesis", "conference", "book", "report", "web", "standard"
]


class ManualReferenceRequest(BaseModel):
    """创建向导第③步手动录入文献的结构化字段。

    该模型仅负责本地校验和 GB/T 7714 格式化；不会联网补全或验证文献真实性。
    """

    reference_type: ManualReferenceType = "journal"
    authors: str = Field(..., min_length=1, max_length=500)
    title: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(..., min_length=1, max_length=500)
    year: str = Field(..., pattern=r"^\d{4}$")
    volume: str = Field("", max_length=50)
    issue: str = Field("", max_length=50)
    pages: str = Field("", max_length=100)
    doi: str = Field("", max_length=300)
    url: str = Field("", max_length=2000)

    @field_validator("authors", "title", "source", "volume", "issue", "pages", "doi", "url")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("doi")
    @classmethod
    def validate_doi(cls, value: str) -> str:
        if value and not value.lower().startswith("10."):
            raise ValueError("DOI 应以 10. 开头")
        return value


class OutlineChapter(BaseModel):
    title: str = Field("", max_length=200)
    level: int = Field(1, ge=1, le=3)
    word_count: int = Field(0, ge=0)


class OutlineResponse(BaseModel):
    outline: str
    chapters: list[OutlineChapter]
