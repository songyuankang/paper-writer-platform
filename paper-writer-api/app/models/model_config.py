"""AI 模型配置请求模型。"""

from pydantic import BaseModel, Field


class ModelConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="模型名称（显示名）")
    provider: str = Field("OpenAI Compatible", max_length=50)
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, max_length=1000)
    model: str = Field(..., min_length=1, max_length=200)
    is_default: bool = False
    enabled: bool = True


class ModelConfigUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    provider: str | None = Field(None, max_length=50)
    base_url: str | None = Field(None, min_length=1, max_length=500)
    api_key: str | None = Field(None, min_length=1, max_length=1000,
                                description="留空表示保持不变")
    model: str | None = Field(None, min_length=1, max_length=200)
    is_default: bool | None = None
    enabled: bool | None = None


class ModelTestRequest(BaseModel):
    id: str | None = Field(None, description="使用已保存模型测试")
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
