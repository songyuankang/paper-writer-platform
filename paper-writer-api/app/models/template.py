"""模板管理 API 的结构化请求 DTO。

前端只提交结构化表单字段，完整 Template JSON 由后端
TemplateService 组装并交给 TemplateValidator 校验。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PageSize = Literal["A3", "A4", "A5", "B4", "B5", "Letter", "Legal", "Tabloid"]
Orientation = Literal["portrait", "landscape"]
Alignment = Literal["left", "center", "right", "justify"]
LineSpacingMode = Literal["multiple", "exact", "at_least"]
IndentUnit = Literal["chars", "pt"]
ReferenceStyle = Literal["gb7714", "apa", "mla", "chicago"]


class FontFamilyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    east_asia: str = Field("宋体", max_length=100)
    latin: str = Field("Times New Roman", max_length=100)


class LineSpacingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: LineSpacingMode = "multiple"
    value: float = Field(1.5, ge=0.5, le=100)


class FirstLineIndentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: IndentUnit = "chars"
    value: float = Field(0, ge=0, le=500)


class TemplateStyleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font_family: FontFamilyInput | None = None
    font_size_pt: float = Field(12, ge=1, le=96)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    alignment: Alignment = "justify"
    line_spacing: LineSpacingInput = Field(default_factory=LineSpacingInput)
    space_before_pt: float = Field(0, ge=0, le=500)
    space_after_pt: float = Field(0, ge=0, le=500)
    first_line_indent: FirstLineIndentInput = Field(
        default_factory=FirstLineIndentInput)
    keep_with_next: bool = False
    page_break_before: bool = False


class TemplateBlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., min_length=1, max_length=50)
    label: str = Field("", max_length=100)
    enabled: bool = True
    level: int | None = Field(None, ge=1, le=4)
    styles: dict[str, TemplateStyleInput] = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class TemplateHeaderFooterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field("", max_length=200)
    style: TemplateStyleInput | None = None


class TemplateMarginsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_mm: float = Field(25, ge=0, le=100)
    bottom_mm: float = Field(25, ge=0, le=100)
    left_mm: float = Field(30, ge=0, le=100)
    right_mm: float = Field(25, ge=0, le=100)


class TemplatePageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: PageSize = "A4"
    orientation: Orientation = "portrait"
    margins: TemplateMarginsInput = Field(default_factory=TemplateMarginsInput)
    header_distance_mm: float | None = Field(None, ge=0, le=50)
    footer_distance_mm: float | None = Field(None, ge=0, le=50)


class TemplateNumberingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    h1: str = Field("第{chinese}章", max_length=200)
    h2: str = Field("{h1}.{n}", max_length=200)
    h3: str = Field("{h1}.{h2}.{n}", max_length=200)
    h4: str = Field("{h1}.{h2}.{h3}.{n}", max_length=200)


class TemplateTocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    include_page_numbers: bool = True


class TemplateWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_template_id: str | None = Field(None, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    category: str | None = Field(None, max_length=100)
    paper_type: str | None = Field(None, max_length=100)
    school_name: str | None = Field(None, max_length=100)
    major: str | None = Field(None, max_length=100)
    page: TemplatePageInput | None = None
    header: TemplateHeaderFooterInput | None = None
    footer: TemplateHeaderFooterInput | None = None
    numbering: TemplateNumberingInput | None = None
    toc: TemplateTocInput | None = None
    reference_style: ReferenceStyle | None = None
    blocks: list[TemplateBlockInput] | None = None


class TemplateDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
