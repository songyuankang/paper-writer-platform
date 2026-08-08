"""模板系统（v2）子包：模型 / 加载 / 存储 / 业务。

分层依赖（单向，无环）：:

    Service ──▶ Repository ──▶ Loader ──▶ models
        │            └─────────▶ models
        └──────────────────────▶ models

后续模块（Validator / Migrator / Renderer / Exporter）在本包内扩展。
"""

from __future__ import annotations

from pathlib import Path

#: 模板库根目录（basic/ school/ mine/）
DEFAULT_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"

from app.formatter.template.models import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    DEFAULT_EAST_ASIA_FONT,
    DEFAULT_LATIN_FONT,
    IndentUnit,
    LineSpacingMode,
    Template,
    TemplateBlock,
    TemplateMeta,
    TemplateStyle,
    TemplateType,
    TextAlign,
)
from app.formatter.template.loader import (  # noqa: E402
    BASIC_PREFIX,
    SCHOOL_PREFIX,
    TemplateLoadError,
    TemplateLoader,
)
from app.formatter.template.repository import TemplateRepository  # noqa: E402
from app.formatter.template.service import (  # noqa: E402
    TemplateService,
    build_services,
    get_service,
)
from app.formatter.template.validator import (  # noqa: E402
    ValidationIssue,
    ValidationResult,
    TemplateValidator,
)
from app.formatter.template.migrator import (  # noqa: E402
    MigrationReport,
    TemplateMigrator,
)
from app.formatter.template.renderer import TemplateRenderer  # noqa: E402
from app.formatter.template.exporter import (  # noqa: E402
    DEFAULT_DOCX_FILENAME,
    DocxExporter,
)
from app.formatter.template.spec_converter import to_render_spec  # noqa: E402
from app.formatter.template import render_service  # noqa: E402  (模块)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_DOCX_FILENAME",
    "DEFAULT_EAST_ASIA_FONT",
    "DEFAULT_LATIN_FONT",
    "DEFAULT_TEMPLATES_ROOT",
    "DocxExporter",
    "IndentUnit",
    "LineSpacingMode",
    "BASIC_PREFIX",
    "SCHOOL_PREFIX",
    "Template",
    "TemplateBlock",
    "TemplateLoadError",
    "TemplateLoader",
    "TemplateMeta",
    "TemplateMigrator",
    "TemplateRepository",
    "TemplateRenderer",
    "TemplateService",
    "TemplateStyle",
    "TemplateType",
    "TemplateValidator",
    "TextAlign",
    "MigrationReport",
    "ValidationIssue",
    "ValidationResult",
    "build_services",
    "get_service",
    "to_render_spec",
    "render_service",
]
