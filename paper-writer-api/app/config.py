"""Application configuration.

All settings can be overridden with environment variables prefixed with
``PAPER_WRITER_`` (e.g. PAPER_WRITER_PORT=9000) or a local ``.env`` file.
DeepSeek 使用无前缀环境变量：DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPER_WRITER_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "paper-writer-api"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    project_root: Path = Path(__file__).resolve().parent.parent
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    output_dir: Path = Path(__file__).resolve().parent.parent / "outputs"
    log_dir: Path = Path(__file__).resolve().parent.parent / "logs"
    db_path: Path = Path(__file__).resolve().parent.parent / "data" / "history.db"
    prompts_dir: Path = Path(__file__).resolve().parent.parent / "prompts"

    # DeepSeek（OpenAI 兼容接口；未配置时回退到内置占位内容生成）
    deepseek_api_key: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_model: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", ""))
    deepseek_base_url: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", ""))
    deepseek_temperature: float = Field(
        default_factory=lambda: float(os.getenv("DEEPSEEK_TEMPERATURE", "0.7")))
    deepseek_max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_MAX_TOKENS", "4000")))
    deepseek_timeout: int = Field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_TIMEOUT", "300")))

    # Upload guardrails
    max_upload_mb: int = 20
    allowed_template_extensions: tuple[str, ...] = (".docx",)

    # Task queue
    task_workers: int = 2
    task_expiry_hours: int = 24

    # 正文一键生成的并发数。免费模型通常有严格频率限制，默认设为 1。
    # 付费额度充足时可通过 PAPER_WRITER_DRAFT_GENERATION_WORKERS 调高。
    draft_generation_workers: int = 1

    # paper-writer skill engine (scripts directory, imported at runtime)
    paper_writer_scripts_dir: Path = (
        Path(__file__).resolve().parent.parent / "paper_writer_scripts"
    )

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.output_dir, self.log_dir,
                  self.db_path.parent):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
