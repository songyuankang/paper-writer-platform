"""Task status models."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskInfo(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(0, ge=0, le=100)
    message: str | None = Field(None, description="当前阶段提示（如“正在生成第一章…”）")
    current_stage: str | None = Field(
        None, description="当前阶段：planning/generating_abstract/generating_chapter/"
                         "generating_conclusion/generating_reference/checking/completed")
    current_chapter: str | None = Field(None, description="当前生成中的章节")
    chapter_count: int | None = Field(None, description="章节总数")
    error: str | None = None
    files: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GenerateResponse(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.queued
