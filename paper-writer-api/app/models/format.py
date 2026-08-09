"""格式处理任务与模板请求模型。"""

from pydantic import BaseModel, Field


class FormatCreateRequest(BaseModel):
    task_id: str = Field(..., description="内容生成任务 id（对应 outputs/<task_id>/paper_content）")
    template_id: str | None = Field(None, description="学校模板 id；不传或为 default 表示默认格式")
    settings: dict = Field(default_factory=dict, description="格式设置（目录/页码/参考文献/图表等）")


class FormatTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    school_name: str = Field("", max_length=100)
    major: str = Field("", max_length=100)
    paper_type: str = Field("", max_length=100)
