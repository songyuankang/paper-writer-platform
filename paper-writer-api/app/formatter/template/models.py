"""模板统一数据模型。

整个模板系统（Loader / Repository / Service / Validator / Migrator /
Renderer / Exporter / API / 前端）统一使用本模块的对象，禁止到处传裸 dict。

- :class:`TemplateStyle`  单个文本区块的 12 字段样式（TextBlock）
- :class:`TemplateBlock`  一个可扩展排版区块（key / kind / styles / settings）
- :class:`TemplateMeta`   模板元数据（含状态）
- :class:`Template`       完整模板（meta + page/header/footer/numbering + blocks）

设计要点：
- ``from_dict`` 尽量健壮：缺字段/类型错误时用默认值兜底，不抛异常
  （解析期容忍，真正的结构校验交给 TemplateValidator）
- ``to_dict`` 输出标准 JSON 结构，与 v2 模板 schema 一致
- Block 保留 ``extra`` 字段：未知区块字段原样保留，实现"新增区块不改 Schema"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: 当前模板 schema 版本（与 TemplateMigrator 目标一致）
CURRENT_SCHEMA_VERSION = 2

#: 默认字体（渲染回退与新建模板基础）
DEFAULT_EAST_ASIA_FONT = "宋体"
DEFAULT_LATIN_FONT = "Times New Roman"


class TemplateType(str, Enum):
    BASIC = "basic"
    SCHOOL = "school"
    MINE = "mine"


class TextAlign(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class LineSpacingMode(str, Enum):
    MULTIPLE = "multiple"
    EXACT = "exact"
    AT_LEAST = "at_least"


class IndentUnit(str, Enum):
    CHARS = "chars"
    PT = "pt"


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "是", "y")
    return default


def _as_enum(value: Any, enum_cls: type[Enum], default) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            return default
    return default


@dataclass
class TemplateStyle:
    """文本区块样式（TextBlock，12 字段，与 v2 schema 一致）。"""

    font_family_east_asia: str = DEFAULT_EAST_ASIA_FONT
    font_family_latin: str = DEFAULT_LATIN_FONT
    font_size_pt: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    alignment: TextAlign = TextAlign.JUSTIFY
    line_spacing_mode: LineSpacingMode = LineSpacingMode.MULTIPLE
    line_spacing_value: float = 1.5
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    first_line_indent_unit: IndentUnit = IndentUnit.CHARS
    first_line_indent_value: float = 0.0
    keep_with_next: bool = False
    page_break_before: bool = False

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any) -> "TemplateStyle":
        if not isinstance(data, dict):
            return cls()
        font = data.get("font_family")
        font = font if isinstance(font, dict) else {}
        line = data.get("line_spacing")
        line = line if isinstance(line, dict) else {}
        indent = data.get("first_line_indent")
        indent = indent if isinstance(indent, dict) else {}
        return cls(
            font_family_east_asia=_as_str(
                font.get("east_asia"), DEFAULT_EAST_ASIA_FONT),
            font_family_latin=_as_str(
                font.get("latin"), DEFAULT_LATIN_FONT),
            font_size_pt=_as_float(data.get("font_size_pt"), 12.0),
            bold=_as_bool(data.get("bold")),
            italic=_as_bool(data.get("italic")),
            underline=_as_bool(data.get("underline")),
            alignment=_as_enum(data.get("alignment"), TextAlign,
                               TextAlign.JUSTIFY),
            line_spacing_mode=_as_enum(
                line.get("mode"), LineSpacingMode, LineSpacingMode.MULTIPLE),
            line_spacing_value=_as_float(line.get("value"), 1.5),
            space_before_pt=_as_float(data.get("space_before_pt")),
            space_after_pt=_as_float(data.get("space_after_pt")),
            first_line_indent_unit=_as_enum(
                indent.get("unit"), IndentUnit, IndentUnit.CHARS),
            first_line_indent_value=_as_float(indent.get("value")),
            keep_with_next=_as_bool(data.get("keep_with_next")),
            page_break_before=_as_bool(data.get("page_break_before")),
        )

    def to_dict(self) -> dict:
        return {
            "font_family": {
                "east_asia": self.font_family_east_asia,
                "latin": self.font_family_latin,
            },
            "font_size_pt": self.font_size_pt,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "alignment": self.alignment.value,
            "line_spacing": {
                "mode": self.line_spacing_mode.value,
                "value": self.line_spacing_value,
            },
            "space_before_pt": self.space_before_pt,
            "space_after_pt": self.space_after_pt,
            "first_line_indent": {
                "unit": self.first_line_indent_unit.value,
                "value": self.first_line_indent_value,
            },
            "keep_with_next": self.keep_with_next,
            "page_break_before": self.page_break_before,
        }


@dataclass
class TemplateBlock:
    """一个可扩展排版区块。

    - ``key``   全局唯一标识（模板内）
    - ``kind``  语义类型（title_zh/abstract/heading/paragraph/...），
      渲染器据此选 handler；新增区块 = 新增 block，不改 Schema
    - ``styles``  role(如 self/title/content/h1/h2...) → 样式
    - ``settings`` 区块级附加配置（如 toc 页码、参考文献格式）
    - ``extra``   未知字段原样保留（向前兼容）
    """

    key: str
    kind: str
    label: str = ""
    enabled: bool = True
    level: int | None = None
    styles: dict[str, TemplateStyle] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any) -> "TemplateBlock":
        if not isinstance(data, dict):
            return cls(key="unknown", kind="unknown")
        known = {"key", "kind", "label", "enabled", "level", "styles",
                 "settings"}
        extra = {k: v for k, v in data.items() if k not in known}
        styles_raw = data.get("styles")
        styles = {}
        if isinstance(styles_raw, dict):
            for role, style in styles_raw.items():
                styles[str(role)] = TemplateStyle.from_dict(style)
        settings = data.get("settings")
        return cls(
            key=_as_str(data.get("key"), "unknown"),
            kind=_as_str(data.get("kind"), "unknown"),
            label=_as_str(data.get("label"), ""),
            enabled=_as_bool(data.get("enabled"), True),
            level=_as_int(data.get("level")) if data.get("level") is not None
            else None,
            styles=styles,
            settings=settings if isinstance(settings, dict) else {},
            extra=extra,
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "enabled": self.enabled,
            "styles": {role: s.to_dict() for role, s in self.styles.items()},
        }
        if self.level is not None:
            out["level"] = self.level
        if self.settings:
            out["settings"] = self.settings
        out.update(self.extra)
        return out


@dataclass
class TemplateMeta:
    """模板元数据（含 DB 状态）。"""

    id: str
    name: str
    type: TemplateType = TemplateType.MINE
    school: str = ""
    school_name: str = ""
    major: str = ""
    paper_type: str = ""
    category: str = ""
    description: str = ""
    version: int = 1
    schema_version: int = CURRENT_SCHEMA_VERSION
    builtin: bool = False
    source: str = "db"
    parent_id: str | None = None
    is_favorite: bool = False
    is_default: bool = False
    sort_order: int = 0
    has_cover: bool = False
    legacy: bool = False
    created_at: str = ""
    updated_at: str = ""

    # ------------------------------------------------------------------
    @classmethod
    def from_json(cls, data: Any, template_id: str = "") -> "TemplateMeta":
        """从模板 JSON 的 meta 段构造（字段缺失用默认兜底）。"""
        if not isinstance(data, dict):
            data = {}
        type_str = _as_str(data.get("type"), "mine")
        try:
            ttype = TemplateType(type_str)
        except ValueError:
            ttype = TemplateType.MINE
        raw_id = _as_str(data.get("id"), "")
        return cls(
            # id 空串也回退到 template_id（保证 id 必非空）
            id=raw_id or template_id,
            name=_as_str(data.get("name"), "未命名模板"),
            type=ttype,
            school=_as_str(data.get("school", "")),
            school_name=_as_str(data.get("school_name",
                                        data.get("school", ""))),
            major=_as_str(data.get("major", "")),
            paper_type=_as_str(data.get("paper_type", "")),
            category=_as_str(data.get("category", "")),
            description=_as_str(data.get("description", "")),
            version=_as_int(data.get("version"), 1),
            schema_version=_as_int(data.get("schema_version"),
                                   CURRENT_SCHEMA_VERSION),
            builtin=_as_bool(data.get("builtin"), False),
            source=_as_str(data.get("source"), "db"),
            parent_id=data.get("parent_id"),
            is_favorite=_as_bool(data.get("is_favorite")),
            is_default=_as_bool(data.get("is_default")),
            sort_order=_as_int(data.get("sort_order")),
            has_cover=_as_bool(data.get("has_cover")),
            legacy=_as_bool(data.get("legacy")),
            created_at=_as_str(data.get("created_at", "")),
            updated_at=_as_str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "school": self.school,
            "school_name": self.school_name,
            "major": self.major,
            "paper_type": self.paper_type,
            "category": self.category,
            "description": self.description,
            "version": self.version,
            "schema_version": self.schema_version,
            "builtin": self.builtin,
            "source": self.source,
            "parent_id": self.parent_id,
            "is_favorite": self.is_favorite,
            "is_default": self.is_default,
            "sort_order": self.sort_order,
            "has_cover": self.has_cover,
            "legacy": self.legacy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Template:
    """完整模板（统一对象模型）。"""

    meta: TemplateMeta
    schema_version: int = CURRENT_SCHEMA_VERSION
    page: dict[str, Any] = field(default_factory=dict)
    header: dict[str, Any] = field(default_factory=dict)
    footer: dict[str, Any] = field(default_factory=dict)
    numbering: dict[str, Any] = field(default_factory=dict)
    blocks: list[TemplateBlock] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any, template_id: str = "") -> "Template":
        """从模板 JSON 构造。缺字段兜底；未知字段保留在 extra。"""
        if not isinstance(data, dict):
            data = {}
        known = {"meta", "schema_version", "page", "header", "footer",
                 "numbering", "blocks"}
        extra = {k: v for k, v in data.items() if k not in known}
        blocks_raw = data.get("blocks")
        blocks = []
        if isinstance(blocks_raw, list):
            for b in blocks_raw:
                block = TemplateBlock.from_dict(b)
                if block.key != "unknown" or block.kind != "unknown":
                    blocks.append(block)
        return cls(
            meta=TemplateMeta.from_json(data.get("meta"), template_id),
            schema_version=_as_int(data.get("schema_version"),
                                   CURRENT_SCHEMA_VERSION),
            page=data.get("page") if isinstance(data.get("page"), dict) else {},
            header=(data.get("header")
                    if isinstance(data.get("header"), dict) else {}),
            footer=(data.get("footer")
                    if isinstance(data.get("footer"), dict) else {}),
            numbering=(data.get("numbering")
                       if isinstance(data.get("numbering"), dict) else {}),
            blocks=blocks,
            extra=extra,
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "meta": self.meta.to_dict(),
            "page": self.page,
            "header": self.header,
            "footer": self.footer,
            "numbering": self.numbering,
            "blocks": [b.to_dict() for b in self.blocks],
            **self.extra,
        }

    # ------------------------------------------------------------------
    def get_block(self, key: str) -> TemplateBlock | None:
        for b in self.blocks:
            if b.key == key:
                return b
        return None

    def blocks_by_kind(self, kind: str) -> list[TemplateBlock]:
        return [b for b in self.blocks if b.kind == kind]
