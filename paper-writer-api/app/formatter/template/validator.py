"""模板结构校验器（TemplateValidator）。

对模板 JSON / Template 对象做**结构化、可定位**的校验，与模型 ``from_dict``
的"宽容解析"互补：

- 解析层（Loader / models.from_dict）：缺字段用默认值兜底，保证系统能跑起来；
- 校验层（本模块）：严格检查结构，输出 ``path`` 精确定位到出错的字段，
  供 API 层返回给前端、供 Migrator 判断是否可迁移、供 Renderer 提前发现风险。

设计要点：
- 输出 :class:`ValidationIssue`（path / code / message / severity），
  不抛异常、不中断，一次调用收集全部问题；
- ``severity`` 三级：``error``（结构错误，渲染会出问题）、``warning``
  （可降级渲染，如未知 kind）、``info``（仅提示，如未知字段已保留到 extra）；
- 未知字段一律不报错：保留到 ``extra``，体现"新增区块/字段不改 Schema"；
- 枚举值用 models 里的 :class:`TextAlign` / :class:`LineSpacingMode` /
  :class:`IndentUnit` / :class:`TemplateType` 校验，单一事实来源；
- 不修改 Renderer / Migrator / Exporter（本模块只读校验）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.formatter.template.models import (
    CURRENT_SCHEMA_VERSION,
    IndentUnit,
    LineSpacingMode,
    Template,
    TemplateType,
    TextAlign,
)

#: 严重级别
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


#: 已知区块语义类型（渲染器有对应 handler 的 kind）
KNOWN_KINDS = {
    "title_zh", "title_en", "abstract", "keywords", "abstract_en",
    "keywords_en", "heading", "paragraph", "figure_caption",
    "table_caption", "toc", "references", "acknowledgement", "appendix",
}

#: 常见纸张规格（未知规格仅 warning，不阻断）
KNOWN_PAGE_SIZES = {"A3", "A4", "A5", "B4", "B5", "Letter", "Legal", "Tabloid"}

#: 页面方向
ORIENTATIONS = {"portrait", "landscape"}

#: 页码编号占位格式 h1~h4
NUMBERING_KEYS = ("h1", "h2", "h3", "h4")

#: 输入长度 / 数值安全边界
MAX_NAME_LEN = 100
MAX_DESCRIPTION_LEN = 2000
MAX_SHORT_TEXT_LEN = 200
MAX_FONT_NAME_LEN = 100
MAX_FONT_SIZE_PT = 96
MAX_SPACE_PT = 500
MAX_LINE_SPACING_MULTIPLE = 10.0
MAX_LINE_SPACING_PT = 100
MAX_INDENT_CHARS = 20
MAX_INDENT_PT = 500
MAX_MARGIN_MM = 100
MAX_DISTANCE_MM = 50


# =====================================================================
# 结构化校验输出
# =====================================================================
@dataclass
class ValidationIssue:
    """一条校验问题，path 精确定位到出错字段。"""

    path: str
    code: str
    message: str
    severity: str = SEVERITY_ERROR

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    """一次校验的完整结果（问题列表 + 快捷判断）。"""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """无任何 error 级别问题。"""
        return not any(i.severity == SEVERITY_ERROR for i in self.issues)

    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]

    def by_path(self, path: str) -> list[ValidationIssue]:
        return [i for i in self.issues if i.path == path]

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "error_count": len(self.errors()),
            "warning_count": len(self.warnings()),
            "issues": [i.as_dict() for i in self.issues],
        }


class TemplateValidationError(ValueError):
    """模板校验未通过（携带结构化 ValidationResult，供 API 返回）。"""

    def __init__(self, result: ValidationResult):
        self.result = result
        messages = "; ".join(
            f"{i.path}: {i.message}" for i in result.errors())
        super().__init__(f"模板校验失败: {messages}")


# =====================================================================
# 类型判定工具（bool 是 int 子类，需严格区分）
# =====================================================================
def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


# =====================================================================
# 校验器
# =====================================================================
class TemplateValidator:
    """模板结构校验器（无状态，可复用）。"""

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def validate(self, content: Any) -> ValidationResult:
        """校验模板原始 JSON（dict）。返回结构化结果，不抛异常。"""
        result = ValidationResult()
        self._validate_content(content, result)
        return result

    def validate_template(self, tpl: Template) -> ValidationResult:
        """校验 Template 模型对象（序列化后走同一套校验口径）。"""
        return self.validate(tpl.to_dict())

    # ------------------------------------------------------------------
    # 顶层
    # ------------------------------------------------------------------
    def _validate_content(self, content: Any, result: ValidationResult) -> None:
        if not isinstance(content, dict):
            result.issues.append(ValidationIssue(
                path="$", code="not_object",
                message="模板顶层必须是对象（JSON Object）",
                severity=SEVERITY_ERROR))
            return

        # 未知顶层字段：保留到 extra，仅 info 提示
        for key in content:
            if key not in ("schema_version", "meta", "page", "header",
                           "footer", "numbering", "blocks"):
                result.issues.append(ValidationIssue(
                    path=f"$.{key}", code="unknown_field",
                    message="未知顶层字段，将原样保留到 extra",
                    severity=SEVERITY_INFO))

        self._validate_schema_version(content, result)
        self._validate_meta(content.get("meta"), result)
        self._validate_page(content.get("page"), result)
        self._validate_header_footer("header", content.get("header"), result)
        self._validate_header_footer("footer", content.get("footer"), result)
        self._validate_numbering(content.get("numbering"), result)
        self._validate_blocks(content.get("blocks"), result)

    def _validate_schema_version(self, content: dict,
                                 result: ValidationResult) -> None:
        value = content.get("schema_version")
        if value is None:
            result.issues.append(ValidationIssue(
                path="$.schema_version", code="missing_field",
                message="缺少 schema_version 字段",
                severity=SEVERITY_ERROR))
            return
        if not _is_int(value):
            result.issues.append(ValidationIssue(
                path="$.schema_version", code="wrong_type",
                message=f"schema_version 必须是整数，实际为 {type(value).__name__}",
                severity=SEVERITY_ERROR))
            return
        if value != CURRENT_SCHEMA_VERSION:
            result.issues.append(ValidationIssue(
                path="$.schema_version", code="schema_version_mismatch",
                message=(f"模板版本 {value} 与当前版本 {CURRENT_SCHEMA_VERSION} "
                         f"不一致，需先经 TemplateMigrator 迁移"),
                severity=SEVERITY_ERROR))

    # ------------------------------------------------------------------
    # meta
    # ------------------------------------------------------------------
    def _validate_meta(self, meta: Any, result: ValidationResult) -> None:
        if not isinstance(meta, dict):
            result.issues.append(ValidationIssue(
                path="$.meta", code="missing_field",
                message="缺少 meta 段（对象）",
                severity=SEVERITY_ERROR))
            return

        # 必填：name
        name = meta.get("name")
        if name is None:
            result.issues.append(ValidationIssue(
                path="$.meta.name", code="missing_field",
                message="meta 缺少必填字段 name",
                severity=SEVERITY_ERROR))
        elif not _is_non_empty_str(name):
            result.issues.append(ValidationIssue(
                path="$.meta.name", code="invalid_value",
                message="meta.name 必须是非空字符串",
                severity=SEVERITY_ERROR))
        elif len(name) > MAX_NAME_LEN:
            result.issues.append(ValidationIssue(
                path="$.meta.name", code="too_long",
                message=f"meta.name 长度不能超过 {MAX_NAME_LEN}",
                severity=SEVERITY_ERROR))

        # 必填：type（枚举 TemplateType）
        ttype = meta.get("type")
        if ttype is None:
            result.issues.append(ValidationIssue(
                path="$.meta.type", code="missing_field",
                message="meta 缺少必填字段 type",
                severity=SEVERITY_ERROR))
        elif not _is_str(ttype) or ttype not in TemplateType._value2member_map_:
            valid = ", ".join(m.value for m in TemplateType)
            result.issues.append(ValidationIssue(
                path="$.meta.type", code="invalid_enum",
                message=f"meta.type 必须是枚举值之一（{valid}），"
                        f"实际为 {ttype!r}",
                severity=SEVERITY_ERROR))

        # 可选字段类型检查（缺失不报，宽容）
        self._check_optional_int(meta, "version", "$.meta.version", result,
                                 minimum=1)
        self._check_optional_int(meta, "schema_version",
                                 "$.meta.schema_version", result)
        self._check_optional_str(meta, "id", "$.meta.id", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "school", "$.meta.school", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "school_name", "$.meta.school_name",
                                 result, max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "major", "$.meta.major", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "paper_type", "$.meta.paper_type",
                                 result, max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "category", "$.meta.category", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_str(meta, "description", "$.meta.description",
                                 result, max_length=MAX_DESCRIPTION_LEN)
        self._check_optional_str(meta, "source", "$.meta.source", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._check_optional_bool(meta, "builtin", "$.meta.builtin", result)
        self._check_optional_bool(meta, "is_favorite", "$.meta.is_favorite",
                                  result)
        self._check_optional_bool(meta, "is_default", "$.meta.is_default",
                                  result)
        self._check_optional_bool(meta, "legacy", "$.meta.legacy", result)
        self._check_optional_bool(meta, "has_cover", "$.meta.has_cover",
                                  result)

        # meta 未知字段：info 提示（保留）
        known = {"id", "name", "type", "school", "school_name", "major",
                 "paper_type", "category", "description", "version",
                 "schema_version", "builtin", "source", "parent_id",
                 "is_favorite", "is_default", "sort_order", "has_cover",
                 "legacy", "created_at", "updated_at"}
        for key in meta:
            if key not in known:
                result.issues.append(ValidationIssue(
                    path=f"$.meta.{key}", code="unknown_field",
                    message="meta 未知字段，将原样保留",
                    severity=SEVERITY_INFO))

    # ------------------------------------------------------------------
    # blocks
    # ------------------------------------------------------------------
    def _validate_blocks(self, blocks: Any, result: ValidationResult) -> None:
        if blocks is None:
            result.issues.append(ValidationIssue(
                path="$.blocks", code="missing_field",
                message="缺少 blocks 段（数组，可为空）",
                severity=SEVERITY_ERROR))
            return
        if not isinstance(blocks, list):
            result.issues.append(ValidationIssue(
                path="$.blocks", code="wrong_type",
                message="blocks 必须是数组",
                severity=SEVERITY_ERROR))
            return

        seen_keys: dict[str, int] = {}
        for idx, block in enumerate(blocks):
            self._validate_block(block, idx, seen_keys, result)

    def _validate_block(self, block: Any, idx: int,
                        seen_keys: dict[str, int],
                        result: ValidationResult) -> None:
        base = f"$.blocks[{idx}]"
        if not isinstance(block, dict):
            result.issues.append(ValidationIssue(
                path=base, code="wrong_type",
                message="block 必须是对象",
                severity=SEVERITY_ERROR))
            return

        # 必填：key / kind
        key = block.get("key")
        if key is None:
            result.issues.append(ValidationIssue(
                path=f"{base}.key", code="missing_field",
                message="block 缺少必填字段 key",
                severity=SEVERITY_ERROR))
        elif not _is_non_empty_str(key):
            result.issues.append(ValidationIssue(
                path=f"{base}.key", code="invalid_value",
                message="block.key 必须是非空字符串",
                severity=SEVERITY_ERROR))
        else:
            if key in seen_keys:
                result.issues.append(ValidationIssue(
                    path=f"{base}.key", code="duplicate_key",
                    message=f"block.key 重复：{key!r}（第一次出现在 "
                            f"$.blocks[{seen_keys[key]}]）",
                    severity=SEVERITY_ERROR))
            else:
                seen_keys[key] = idx

        kind = block.get("kind")
        if kind is None:
            result.issues.append(ValidationIssue(
                path=f"{base}.kind", code="missing_field",
                message="block 缺少必填字段 kind",
                severity=SEVERITY_ERROR))
        elif not _is_non_empty_str(kind):
            result.issues.append(ValidationIssue(
                path=f"{base}.kind", code="invalid_value",
                message="block.kind 必须是非空字符串",
                severity=SEVERITY_ERROR))
        elif kind not in KNOWN_KINDS:
            result.issues.append(ValidationIssue(
                path=f"{base}.kind", code="unknown_kind",
                message=(f"未知区块类型 {kind!r}，渲染器可能没有对应 handler，"
                         f"将按通用段落处理或跳过"),
                severity=SEVERITY_WARNING))

        # 可选字段
        self._check_optional_str(block, "label", f"{base}.label", result)
        self._check_optional_bool(block, "enabled", f"{base}.enabled", result)
        self._check_optional_int(block, "level", f"{base}.level", result,
                                 minimum=1, maximum=4)

        # heading 必须带 level（缺失给 warning，渲染时回退默认层级）
        if kind == "heading" and block.get("level") is None:
            result.issues.append(ValidationIssue(
                path=f"{base}.level", code="missing_field",
                message="heading 区块缺少 level（1-4）",
                severity=SEVERITY_WARNING))

        # styles
        self._validate_styles(block.get("styles"), f"{base}.styles", result)

        # settings
        settings = block.get("settings")
        if settings is not None and not isinstance(settings, dict):
            result.issues.append(ValidationIssue(
                path=f"{base}.settings", code="wrong_type",
                message="block.settings 必须是对象",
                severity=SEVERITY_ERROR))

        # 未知字段：info 提示（保留到 extra）
        known = {"key", "kind", "label", "enabled", "level", "styles",
                 "settings"}
        for k in block:
            if k not in known:
                result.issues.append(ValidationIssue(
                    path=f"{base}.{k}", code="unknown_field",
                    message="block 未知字段，将原样保留到 extra",
                    severity=SEVERITY_INFO))

    # ------------------------------------------------------------------
    # styles（TextBlock 12 字段）
    # ------------------------------------------------------------------
    def _validate_styles(self, styles: Any, path: str,
                         result: ValidationResult) -> None:
        if styles is None:
            return
        if not isinstance(styles, dict):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message="styles 必须是对象（role → style）",
                severity=SEVERITY_ERROR))
            return
        for role, style in styles.items():
            self._validate_style(style, f"{path}.{role}", result)

    def _validate_style(self, style: Any, path: str,
                        result: ValidationResult) -> None:
        if not isinstance(style, dict):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message="style 必须是对象",
                severity=SEVERITY_ERROR))
            return

        # font_family
        font = style.get("font_family")
        if font is not None:
            if not isinstance(font, dict):
                result.issues.append(ValidationIssue(
                    path=f"{path}.font_family", code="wrong_type",
                    message="font_family 必须是对象",
                    severity=SEVERITY_ERROR))
            else:
                self._check_optional_str(font, "east_asia",
                                         f"{path}.font_family.east_asia",
                                         result,
                                         max_length=MAX_FONT_NAME_LEN)
                self._check_optional_str(font, "latin",
                                         f"{path}.font_family.latin", result,
                                         max_length=MAX_FONT_NAME_LEN)
                self._check_font_name(font, "east_asia",
                                      f"{path}.font_family.east_asia", result)
                self._check_font_name(font, "latin",
                                      f"{path}.font_family.latin", result)

        # 数值/布尔字段
        self._check_optional_number(style, "font_size_pt",
                                    f"{path}.font_size_pt", result,
                                    minimum=1, maximum=MAX_FONT_SIZE_PT)
        self._check_optional_bool(style, "bold", f"{path}.bold", result)
        self._check_optional_bool(style, "italic", f"{path}.italic", result)
        self._check_optional_bool(style, "underline", f"{path}.underline",
                                  result)
        self._check_optional_bool(style, "keep_with_next",
                                  f"{path}.keep_with_next", result)
        self._check_optional_bool(style, "page_break_before",
                                  f"{path}.page_break_before", result)
        self._check_optional_number(style, "space_before_pt",
                                    f"{path}.space_before_pt", result,
                                    minimum=0, maximum=MAX_SPACE_PT)
        self._check_optional_number(style, "space_after_pt",
                                    f"{path}.space_after_pt", result,
                                    minimum=0, maximum=MAX_SPACE_PT)

        # alignment 枚举
        self._check_optional_enum(style, "alignment", TextAlign,
                                  f"{path}.alignment", result)

        # line_spacing
        line = style.get("line_spacing")
        if line is not None:
            if not isinstance(line, dict):
                result.issues.append(ValidationIssue(
                    path=f"{path}.line_spacing", code="wrong_type",
                    message="line_spacing 必须是对象",
                    severity=SEVERITY_ERROR))
            else:
                self._check_optional_enum(line, "mode", LineSpacingMode,
                                          f"{path}.line_spacing.mode", result)
                mode = line.get("mode")
                if mode == LineSpacingMode.MULTIPLE.value:
                    self._check_optional_number(
                        line, "value", f"{path}.line_spacing.value", result,
                        minimum=0.5, maximum=MAX_LINE_SPACING_MULTIPLE)
                else:
                    self._check_optional_number(
                        line, "value", f"{path}.line_spacing.value", result,
                        minimum=1, maximum=MAX_LINE_SPACING_PT)

        # first_line_indent
        indent = style.get("first_line_indent")
        if indent is not None:
            if not isinstance(indent, dict):
                result.issues.append(ValidationIssue(
                    path=f"{path}.first_line_indent", code="wrong_type",
                    message="first_line_indent 必须是对象",
                    severity=SEVERITY_ERROR))
            else:
                self._check_optional_enum(indent, "unit", IndentUnit,
                                          f"{path}.first_line_indent.unit",
                                          result)
                unit = indent.get("unit")
                maximum = (MAX_INDENT_CHARS
                           if unit == IndentUnit.CHARS.value
                           else MAX_INDENT_PT)
                self._check_optional_number(
                    indent, "value", f"{path}.first_line_indent.value",
                    result, minimum=0, maximum=maximum)

        # 未知样式字段：info 提示（保留）
        known = {"font_family", "font_size_pt", "bold", "italic", "underline",
                 "alignment", "line_spacing", "space_before_pt",
                 "space_after_pt", "first_line_indent", "keep_with_next",
                 "page_break_before"}
        for k in style:
            if k not in known:
                result.issues.append(ValidationIssue(
                    path=f"{path}.{k}", code="unknown_field",
                    message="style 未知字段，将原样保留",
                    severity=SEVERITY_INFO))

    # ------------------------------------------------------------------
    # page / header / footer / numbering
    # ------------------------------------------------------------------
    def _validate_page(self, page: Any, result: ValidationResult) -> None:
        if page is None:
            return
        if not isinstance(page, dict):
            result.issues.append(ValidationIssue(
                path="$.page", code="wrong_type",
                message="page 必须是对象",
                severity=SEVERITY_ERROR))
            return

        size = page.get("size")
        if size is not None:
            if not _is_str(size):
                result.issues.append(ValidationIssue(
                    path="$.page.size", code="wrong_type",
                    message="page.size 必须是字符串",
                    severity=SEVERITY_ERROR))
            elif size not in KNOWN_PAGE_SIZES:
                result.issues.append(ValidationIssue(
                    path="$.page.size", code="unknown_value",
                    message=f"未知纸张规格 {size!r}（已知："
                            f"{', '.join(sorted(KNOWN_PAGE_SIZES))}），"
                            f"渲染时按自定义尺寸处理",
                    severity=SEVERITY_WARNING))

        orientation = page.get("orientation")
        if orientation is not None:
            if not _is_str(orientation) or orientation not in ORIENTATIONS:
                result.issues.append(ValidationIssue(
                    path="$.page.orientation", code="invalid_enum",
                    message=f"page.orientation 必须是 portrait 或 landscape，"
                            f"实际为 {orientation!r}",
                    severity=SEVERITY_ERROR))

        margins = page.get("margins")
        if margins is not None:
            if not isinstance(margins, dict):
                result.issues.append(ValidationIssue(
                    path="$.page.margins", code="wrong_type",
                    message="page.margins 必须是对象",
                    severity=SEVERITY_ERROR))
            else:
                for side in ("top_mm", "bottom_mm", "left_mm", "right_mm"):
                    self._check_optional_number(
                        margins, side, f"$.page.margins.{side}", result,
                        minimum=0, maximum=MAX_MARGIN_MM)

        self._check_optional_number(page, "header_distance_mm",
                                    "$.page.header_distance_mm", result,
                                    minimum=0, maximum=MAX_DISTANCE_MM)
        self._check_optional_number(page, "footer_distance_mm",
                                    "$.page.footer_distance_mm", result,
                                    minimum=0, maximum=MAX_DISTANCE_MM)

    def _validate_header_footer(self, section: str, value: Any,
                                result: ValidationResult) -> None:
        if value is None:
            return
        path = f"$.{section}"
        if not isinstance(value, dict):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message=f"{section} 必须是对象",
                severity=SEVERITY_ERROR))
            return
        self._check_optional_str(value, "content", f"{path}.content", result,
                                 max_length=MAX_SHORT_TEXT_LEN)
        self._validate_style(value.get("style"), f"{path}.style", result)

    def _validate_numbering(self, numbering: Any,
                            result: ValidationResult) -> None:
        if numbering is None:
            return
        if not isinstance(numbering, dict):
            result.issues.append(ValidationIssue(
                path="$.numbering", code="wrong_type",
                message="numbering 必须是对象",
                severity=SEVERITY_ERROR))
            return
        self._check_optional_bool(numbering, "enabled", "$.numbering.enabled",
                                  result)
        for key in NUMBERING_KEYS:
            self._check_optional_str(numbering, key,
                                     f"$.numbering.{key}", result,
                                     max_length=MAX_SHORT_TEXT_LEN)

    # ------------------------------------------------------------------
    # 通用可选字段检查
    # ------------------------------------------------------------------
    @staticmethod
    def _check_optional_str(data: dict, key: str, path: str,
                            result: ValidationResult,
                            max_length: int | None = None) -> None:
        value = data.get(key)
        if value is not None and not _is_str(value):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message=f"{path} 必须是字符串，实际为 {type(value).__name__}",
                severity=SEVERITY_ERROR))
        elif value is not None and max_length is not None \
                and len(value) > max_length:
            result.issues.append(ValidationIssue(
                path=path, code="too_long",
                message=f"{path} 长度不能超过 {max_length}",
                severity=SEVERITY_ERROR))

    @staticmethod
    def _check_optional_bool(data: dict, key: str, path: str,
                             result: ValidationResult) -> None:
        value = data.get(key)
        if value is not None and not _is_bool(value):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message=f"{path} 必须是布尔值，实际为 {type(value).__name__}",
                severity=SEVERITY_ERROR))

    @staticmethod
    def _check_optional_number(data: dict, key: str, path: str,
                               result: ValidationResult,
                               minimum: float | None = None,
                               maximum: float | None = None) -> None:
        value = data.get(key)
        if value is None:
            return
        if not _is_number(value) or not math.isfinite(float(value)):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message=f"{path} 必须是数值，实际为 {type(value).__name__}",
                severity=SEVERITY_ERROR))
            return
        if minimum is not None and value < minimum:
            result.issues.append(ValidationIssue(
                path=path, code="out_of_range",
                message=f"{path} 必须 >= {minimum}，实际为 {value}",
                severity=SEVERITY_ERROR))
        if maximum is not None and value > maximum:
            result.issues.append(ValidationIssue(
                path=path, code="out_of_range",
                message=f"{path} 必须 <= {maximum}，实际为 {value}",
                severity=SEVERITY_ERROR))

    @staticmethod
    def _check_optional_int(data: dict, key: str, path: str,
                            result: ValidationResult,
                            minimum: int | None = None,
                            maximum: int | None = None) -> None:
        value = data.get(key)
        if value is None:
            return
        if not _is_int(value):
            result.issues.append(ValidationIssue(
                path=path, code="wrong_type",
                message=f"{path} 必须是整数，实际为 {type(value).__name__}",
                severity=SEVERITY_ERROR))
            return
        if minimum is not None and value < minimum:
            result.issues.append(ValidationIssue(
                path=path, code="out_of_range",
                message=f"{path} 必须 >= {minimum}，实际为 {value}",
                severity=SEVERITY_ERROR))
        if maximum is not None and value > maximum:
            result.issues.append(ValidationIssue(
                path=path, code="out_of_range",
                message=f"{path} 必须 <= {maximum}，实际为 {value}",
                severity=SEVERITY_ERROR))

    @staticmethod
    def _check_optional_enum(data: dict, key: str, enum_cls: type,
                             path: str, result: ValidationResult) -> None:
        value = data.get(key)
        if value is None:
            return
        valid = ", ".join(m.value for m in enum_cls)
        if not _is_str(value) or value not in enum_cls._value2member_map_:
            result.issues.append(ValidationIssue(
                path=path, code="invalid_enum",
                message=f"{path} 必须是枚举值之一（{valid}），实际为 {value!r}",
                severity=SEVERITY_ERROR))

    @staticmethod
    def _check_font_name(data: dict, key: str, path: str,
                         result: ValidationResult) -> None:
        """字体名不能包含路径分隔符或控制字符。"""
        value = data.get(key)
        if not _is_str(value):
            return
        if any(ch in value for ch in ("/", "\\", "\x00", "\n", "\r")):
            result.issues.append(ValidationIssue(
                path=path, code="invalid_font",
                message=f"{path} 不能包含路径分隔符或控制字符",
                severity=SEVERITY_ERROR))
