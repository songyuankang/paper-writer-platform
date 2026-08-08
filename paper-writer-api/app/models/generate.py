"""Request model for POST /api/generate."""

from typing import Literal

from pydantic import BaseModel, Field

PaperType = Literal["课程论文", "毕业论文", "期刊论文", "实证研究", "文献综述",
                    "开题报告"]
ReferenceStyle = Literal["gb7714", "apa", "mla", "chicago"]
GenerationMode = Literal["auto", "outline"]
GenerationStrategy = Literal["section", "single"]


class ChartConfig(BaseModel):
    enabled: bool = Field(True, description="是否生成图表")
    count: int = Field(1, ge=1, le=20, description="生成图表数量（1-20）")
    types: list[str] = Field(
        default_factory=list,
        description="图表类型列表（空则按专业智能推荐），如 [\"bar\",\"line\",\"pie\"]",
    )


class MaterialFile(BaseModel):
    kind: str = Field("其他资料", description="资料类型：开题报告/仿写论文/其他资料")
    filename: str = Field(..., description="文件名")
    path: str = Field("", description="相对任务目录的保存路径")
    text: str = Field("", description="提取出的文本（用于 AI 参考）")


class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="论文标题")
    major: str = Field(..., min_length=1, max_length=100, description="专业/学科方向")
    paper_type: PaperType = Field("课程论文", description="论文类型")
    word_count: int = Field(3000, ge=500, le=100_000, description="目标字数（汉字）")
    chart_enabled: bool = Field(False, description="是否生成示例数据图表")
    reference_style: ReferenceStyle = Field("gb7714", description="参考文献格式")
    generation_mode: GenerationMode = Field("auto", description="auto=自动生成；outline=按大纲生成")
    outline: str | None = Field(
        None, max_length=20_000,
        description="大纲模式下的章节文本（多行，如 第一章 绪论 / 1.1 研究背景）",
    )
    chart_config: ChartConfig | None = Field(
        None, description="图表配置（升级版）；不传时使用 chart_enabled 旧逻辑")
    special_requirements: str | None = Field(
        None, max_length=100_000,
        description="特殊要求（可选）：如增加案例分析、强化某章节、调整写作风格等；"
                    "上传的资料文本会以【参考资料】形式合并进来",
    )
    materials: list[MaterialFile] = Field(
        default_factory=list,
        description="上传的参考资料（开题报告/仿写论文/其他资料），用于 AI 参考",
    )
    abstract: str | None = Field(
        None, max_length=20_000,
        description="用户自定义摘要（创作向导第②步定稿后覆盖自动生成）",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="用户自定义关键词（与 abstract 一起覆盖）",
    )
    references: list[str] = Field(
        default_factory=list,
        description="用户选择的真实参考文献引文（GB/T 7714，覆盖自动生成）",
    )
    draft_mode: bool = Field(
        False,
        description="草稿模式：只构建大纲草稿（逐段生成编辑器用），不自动生成全文",
    )
    generation_strategy: GenerationStrategy = Field(
        "section",
        description="生成策略：section=分段生成（推荐，默认）；single=一次生成（测试用）",
    )
    model_id: str | None = Field(
        None, description="AI 模型配置 id（可选；不传使用默认模型或环境配置）")
    template_id: str = Field(
        "", max_length=100,
        description="排版模板 id（如 basic-general-thesis）；空/默认使用默认模板")


class OutlineRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="论文标题")
    major: str = Field(..., min_length=1, max_length=100, description="专业/学科方向")
    paper_type: PaperType = Field("课程论文", description="论文类型")
    word_count: int = Field(3000, ge=500, le=100_000, description="目标字数")
    model_id: str | None = Field(None, description="指定使用的模型")


class AbstractRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="论文标题")
    major: str = Field(..., min_length=1, max_length=100, description="专业/学科方向")
    paper_type: PaperType = Field("课程论文", description="论文类型")
    special_requirements: str | None = Field(
        None, max_length=10_000, description="特殊要求/参考资料（可选）")
    model_id: str | None = Field(None, description="指定使用的模型")


class ReferenceSearchRequest(BaseModel):
    title: str = Field("", max_length=200, description="论文标题")
    major: str = Field(..., min_length=1, max_length=100, description="专业/学科方向")
    keywords: list[str] = Field(default_factory=list, description="关键词（用于检索）")
    query: str | None = Field(None, max_length=500, description="自定义检索词")
    limit: int = Field(12, ge=1, le=20, description="返回条数（1-20）")


class OutlineChapter(BaseModel):
    title: str
    level: int = Field(1, ge=1, le=3)
    word_count: int = Field(0, ge=0)


class OutlineResponse(BaseModel):
    outline: str
    chapters: list[OutlineChapter]
