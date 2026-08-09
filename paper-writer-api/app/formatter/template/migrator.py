"""模板迁移器（TemplateMigrator）。

把旧版模板迁移到 ``schema_version=2``（当前 schema）。流程：

    读取旧模板 → 识别 schema_version → 执行对应迁移 → 生成 v2
        → TemplateValidator 校验 → 返回 Template（含迁移报告）

支持输入：
- 已是 v2 的 JSON/模板 → 不重复迁移（no-op，仍做校验）
- ``schema_version=1`` 的旧模板 → 迁移（旧"文件式模板"三件套格式）
- 缺失 ``schema_version`` 的旧模板 → 按实际结构判断是否可迁移：
  - 旧 ``rules.json``（toc/page.margins/reference/chart/fonts）
  - 旧 ``template.json``（name/school_name/major/paper_type/updated_at）
  - 旧 ``template_config.json``（外部引擎 parse_template 解析结果）
- 不支持的版本 / 无法识别的结构 → 返回明确失败报告（不抛异常）

无损保证：
- 旧字段全部保留：映射到 v2 字段，或原样保留（顶层 ``legacy`` 段 +
  block ``settings.legacy_style``），不无故丢弃
- 无法表达的字段（如页眉/页脚文本、旧 style.docx 封面版式、行距规则）
  明确写入 notes 报告"无法自动迁移"
- 迁移失败 / 校验不通过 → 不写回原文件（``migrate_file`` 保证）

本模块不修改 Renderer / Exporter / 前端。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.formatter.template.loader import json_load
from app.formatter.template.models import (
    CURRENT_SCHEMA_VERSION,
    DEFAULT_EAST_ASIA_FONT,
    DEFAULT_LATIN_FONT,
    Template,
)
from app.formatter.template.validator import TemplateValidator, ValidationResult

#: v2 顶层已知键（其余视为未知字段保留）
_V2_TOP_KEYS = {"schema_version", "meta", "page", "header", "footer",
                "numbering", "blocks"}
#: 旧 rules.json 扁平键
_RULES_FLAT_KEYS = ("toc", "page", "reference", "chart", "fonts")
#: 旧 template.json 扁平键
_META_FLAT_KEYS = ("id", "name", "school", "school_name", "major",
                   "paper_type", "category", "description", "version",
                   "updated_at", "created_at")
#: 已知纸张规格（宽×高 mm，容差 1mm）
_KNOWN_SIZES = {
    (210, 297): "A4",
    (297, 420): "A3",
    (148, 210): "A5",
    (176, 250): "B5",
    (250, 353): "B4",
    (216, 279): "Letter",
    (216, 356): "Legal",
}
#: 默认编号模式（v2 渲染器默认；旧 rules 只有 title_numbering 布尔）
_DEFAULT_NUMBERING = {
    "enabled": True,
    "h1": "第{chinese}章",
    "h2": "{h1}.{n}",
    "h3": "{h1}.{h2}.{n}",
    "h4": "{h1}.{h2}.{h3}.{n}",
}


# =====================================================================
# 迁移报告
# =====================================================================
@dataclass
class MigrationReport:
    """一次迁移的完整结果。

    - ``success``      迁移成功且通过 Validator 校验
    - ``migrated``     是否真的执行了迁移（False = 本就是 v2，no-op）
    - ``source_version`` 识别出的源版本（1 / 2 / None=无法识别）
    - ``template``     迁移后的 v2 :class:`Template`（失败时为 None）
    - ``validation``   最终 Validator 结果（成功时必然 valid）
    - ``notes``        人类可读说明：映射 / 保留 / 无法自动迁移的字段
    """

    success: bool
    migrated: bool
    source_version: int | None
    template: Template | None
    validation: ValidationResult = field(default_factory=ValidationResult)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "migrated": self.migrated,
            "source_version": self.source_version,
            "notes": self.notes,
            "validation": self.validation.as_dict(),
        }


# =====================================================================
# 迁移器
# =====================================================================
class TemplateMigrator:
    """旧版模板 → v2 迁移器（无状态，可复用）。"""

    def __init__(self, validator: TemplateValidator | None = None):
        self.validator = validator or TemplateValidator()

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def migrate(self, content: Any, template_id: str = "") -> MigrationReport:
        """统一迁移入口：识别版本并执行对应迁移。不抛异常。"""
        if not isinstance(content, dict):
            return self._fail("not_object",
                              "模板内容必须是 JSON 对象", None)
        sv = content.get("schema_version")
        if sv is None:
            # 缺失 schema_version → 按结构判断
            if self._looks_v2(content):
                return self._noop(content, template_id, sv=2)
            if self._looks_legacy(content):
                return self._migrate_v1(content, template_id)
            return self._fail("unrecognized_format",
                              "无法识别模板格式（既不是 v2，也不是已知旧格式）",
                              None)
        if not isinstance(sv, int) or isinstance(sv, bool):
            return self._fail("invalid_version",
                              f"schema_version 必须是整数，实际为 {sv!r}", None)
        if sv == CURRENT_SCHEMA_VERSION:
            return self._noop(content, template_id, sv=2)
        if sv == 1:
            return self._migrate_v1(content, template_id)
        return self._fail("unsupported_version",
                          f"不支持的模板版本: {sv}（仅支持 1 → "
                          f"{CURRENT_SCHEMA_VERSION}）", sv)

    def migrate_bundle(self, meta: dict | None = None,
                       rules: dict | None = None,
                       config: dict | None = None) -> MigrationReport:
        """旧模板三件套（template.json + rules.json + template_config.json）
        直接迁移（供 DB legacy 行 / 模板目录使用）。"""
        return self.migrate({
            "schema_version": 1,
            "meta": meta or {},
            "rules": rules or {},
            "config": config or {},
        })

    def migrate_file(self, path: Path | str) -> MigrationReport:
        """迁移模板 JSON 文件；**仅迁移成功且确实发生迁移时才写回**。

        迁移失败 / 校验不通过 / 本就是 v2 → 不覆盖原文件。
        """
        path = Path(path)
        try:
            content = json_load(path)
        except Exception as exc:
            return self._fail("read_error", f"读取失败: {exc}", None)
        report = self.migrate(content, template_id=path.stem)
        if report.success and report.migrated:
            path.write_text(
                json.dumps(report.template.to_dict(), ensure_ascii=False,
                           indent=2), encoding="utf-8")
            report.notes.append(f"迁移成功，已写回 {path}")
        return report

    # ------------------------------------------------------------------
    # 版本识别
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_v2(content: dict) -> bool:
        """结构上像 v2：有 meta + blocks，且不含旧三件套标记。"""
        return ("meta" in content and "blocks" in content
                and "rules" not in content and "config" not in content)

    @staticmethod
    def _looks_legacy(content: dict) -> bool:
        """结构上像旧格式：三件套标记 / 扁平 rules.json / 旧 template.json。"""
        if any(k in content for k in ("meta", "rules", "config")):
            return True
        if "toc" in content or "chart" in content:
            return True
        if isinstance(content.get("page"), dict) and \
                "margins" in content["page"]:
            return True
        if "name" in content and any(
                k in content for k in ("school_name", "major", "paper_type")):
            return True
        return False

    # ------------------------------------------------------------------
    # no-op（已是 v2）
    # ------------------------------------------------------------------
    def _noop(self, content: dict, template_id: str,
              sv: int) -> MigrationReport:
        tpl = Template.from_dict(content, template_id)
        validation = self.validator.validate(content)
        notes = []
        if not validation.valid:
            notes.append("已是 v2，但结构校验未通过（错误见 validation）")
        return MigrationReport(success=validation.valid, migrated=False,
                               source_version=sv, template=tpl,
                               validation=validation, notes=notes)

    # ------------------------------------------------------------------
    # v1 / legacy → v2
    # ------------------------------------------------------------------
    def _migrate_v1(self, content: dict, template_id: str) -> MigrationReport:
        notes: list[str] = []
        old_meta, rules, config, legacy = self._extract_parts(content)

        v2 = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "meta": self._map_meta(old_meta),
            "page": self._map_page(rules, config, notes),
            "header": self._map_header_footer("header", config, notes),
            "footer": self._map_header_footer("footer", config, notes),
            "numbering": self._map_numbering(rules, notes),
            "blocks": self._map_blocks(config, notes),
            # 无损：旧内容整体保留
            "legacy": legacy,
        }
        validation = self.validator.validate(v2)
        if not validation.valid:
            notes.append("迁移结果未通过 Validator 校验（错误见 validation）")
        tpl = Template.from_dict(v2, template_id)
        return MigrationReport(success=validation.valid, migrated=True,
                               source_version=1, template=tpl,
                               validation=validation, notes=notes)

    @staticmethod
    def _extract_parts(content: dict) -> tuple[dict, dict, dict, dict]:
        """从 v1/legacy 内容中拆分 meta / rules / config，并整体保留 legacy。"""
        old_meta = (content.get("meta")
                    if isinstance(content.get("meta"), dict) else {})
        rules = (content.get("rules")
                 if isinstance(content.get("rules"), dict) else {})
        config = (content.get("config")
                  if isinstance(content.get("config"), dict) else {})

        # 扁平旧 template.json（无 meta 段）→ 提取 meta 字段
        if not old_meta:
            old_meta = {k: content[k] for k in _META_FLAT_KEYS
                        if k in content}
        # 扁平 rules.json（无 rules 段）→ 提取规则字段
        if not rules:
            rules = {k: content[k] for k in _RULES_FLAT_KEYS if k in content}

        extra = {k: v for k, v in content.items()
                 if k not in ("schema_version", "meta", "rules", "config")}
        legacy = {
            "source": "v1",
            "meta": (content.get("meta") if isinstance(content.get("meta"),
                     dict) else {k: content.get(k) for k in _META_FLAT_KEYS
                                 if k in content}),
            "rules": (content.get("rules") if isinstance(content.get("rules"),
                      dict) else {k: content.get(k) for k in _RULES_FLAT_KEYS
                                  if k in content}),
            "config": (content.get("config") if isinstance(
                content.get("config"), dict) else {}),
            "extra": extra,
        }
        return old_meta, rules, config, legacy

    # ------------------------------------------------------------------
    # 字段映射（全部由项目实际旧格式确认，非猜测）
    # ------------------------------------------------------------------
    @staticmethod
    def _map_meta(old_meta: dict) -> dict:
        school = old_meta.get("school_name") or old_meta.get("school") or ""
        meta: dict[str, Any] = {
            "id": old_meta.get("id") or "",
            "name": str(old_meta.get("name") or "").strip() or "未命名模板",
            "type": "mine",
            "school": school,
            "school_name": school,
            "major": old_meta.get("major") or "",
            # 旧 paper_type（毕业论文等）→ v2 category
            "category": (old_meta.get("category")
                         or old_meta.get("paper_type") or ""),
            "description": old_meta.get("description") or "",
            "version": 1,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "builtin": False,
            "source": "migrated",
        }
        for k in ("updated_at", "created_at"):
            if old_meta.get(k):
                meta[k] = old_meta[k]
        # 注意：v2 meta 模型不保留未知键；旧 meta 中无法表达的字段
        # 已整体保留在顶层 legacy.meta（无损），此处不再重复注入。
        return meta

    @staticmethod
    def _map_page(rules: dict, config: dict, notes: list[str]) -> dict:
        page: dict[str, Any] = {}
        cfg_page = (config.get("page")
                    if isinstance(config.get("page"), dict) else {})
        rules_page = rules.get("page")
        rules_margins = (rules_page.get("margins")
                         if isinstance(rules_page, dict) else {})

        # 页边距：优先 config（真实解析值），回退 rules；cm→mm 精确 ×10
        margins: dict[str, float] = {}
        for out_side, cfg_key in (("top_mm", "top_margin_cm"),
                                  ("bottom_mm", "bottom_margin_cm"),
                                  ("left_mm", "left_margin_cm"),
                                  ("right_mm", "right_margin_cm")):
            cm = cfg_page.get(cfg_key)
            if not TemplateMigrator._is_num(cm):
                cm = rules_margins.get(cfg_key.replace("margin_cm", "cm"))
            if TemplateMigrator._is_num(cm):
                margins[out_side] = round(float(cm) * 10, 2)
        if margins:
            page["margins"] = margins

        for out_key, cfg_key in (("header_distance_mm", "header_distance_cm"),
                                 ("footer_distance_mm", "footer_distance_cm")):
            cm = cfg_page.get(cfg_key)
            if TemplateMigrator._is_num(cm):
                page[out_key] = round(float(cm) * 10, 2)

        # 纸张与方向（config 有解析尺寸时才判定）
        w, h = cfg_page.get("page_width_cm"), cfg_page.get("page_height_cm")
        if TemplateMigrator._is_num(w) and TemplateMigrator._is_num(h):
            wmm, hmm = round(float(w) * 10, 1), round(float(h) * 10, 1)
            page["size"] = TemplateMigrator._page_size(wmm, hmm)
            page["orientation"] = ("landscape" if wmm > hmm else "portrait")
        return page

    @staticmethod
    def _page_size(wmm: float, hmm: float) -> str:
        for (pw, ph), name in _KNOWN_SIZES.items():
            if abs(min(wmm, hmm) - min(pw, ph)) <= 1 and \
                    abs(max(wmm, hmm) - max(pw, ph)) <= 1:
                return name
        return f"{wmm:g}x{hmm:g}mm"  # 自定义尺寸（无损保留）

    @staticmethod
    def _map_header_footer(section: str, config: dict,
                           notes: list[str]) -> dict:
        cfg_page = (config.get("page")
                    if isinstance(config.get("page"), dict) else {})
        old_sec = cfg_page.get(section)
        has_content = bool(isinstance(old_sec, dict)
                           and old_sec.get("has_content"))
        default_style = TemplateMigrator._default_style(config)
        if section == "footer":
            if has_content:
                notes.append("旧页脚文本无法从解析结果恢复，"
                             "使用默认页码占位 {page}")
                return {"content": "{page}", "style": default_style}
            return {"content": "", "style": default_style}
        if has_content:
            notes.append("旧页眉文本无法从解析结果恢复"
                         "（旧解析器仅记录 has_content，不含文本）")
        return {"content": "", "style": default_style}

    @staticmethod
    def _map_numbering(rules: dict, notes: list[str]) -> dict:
        toc = rules.get("toc") if isinstance(rules.get("toc"), dict) else {}
        if "title_numbering" not in toc:
            notes.append("旧 rules 未记录 title_numbering，编号默认启用")
        numbering = dict(_DEFAULT_NUMBERING)
        numbering["enabled"] = bool(toc.get("title_numbering", True))
        return numbering

    @staticmethod
    def _map_blocks(config: dict, notes: list[str]) -> list[dict]:
        blocks: list[dict] = []
        styles = config.get("styles")
        styles = styles if isinstance(styles, dict) else {}
        default_style = TemplateMigrator._default_style(config)

        for role, level in (("heading1", 1), ("heading2", 2),
                            ("heading3", 3)):
            entry = styles.get(role)
            if isinstance(entry, dict):
                blocks.append({
                    "key": f"heading{level}", "kind": "heading",
                    "label": f"{level} 级标题", "enabled": True,
                    "level": level,
                    "styles": {"self":
                               TemplateMigrator._style_from(entry, config)},
                    "settings": {"legacy_style": entry},
                })

        entry = styles.get("body")
        if isinstance(entry, dict):
            blocks.append({
                "key": "body", "kind": "paragraph", "label": "正文",
                "enabled": True,
                "styles": {"self": TemplateMigrator._style_from(entry,
                                                                config)},
                "settings": {"legacy_style": entry},
            })

        entry = styles.get("caption")
        if isinstance(entry, dict):
            style = TemplateMigrator._style_from(entry, config)
            blocks.append({
                "key": "figure_caption", "kind": "figure_caption",
                "label": "图题注", "enabled": True,
                "styles": {"self": style},
                "settings": {"legacy_style": entry},
            })
            blocks.append({
                "key": "table_caption", "kind": "table_caption",
                "label": "表题注", "enabled": True,
                "styles": {"self": style},
                "settings": {"legacy_style": entry},
            })
            notes.append("旧题注样式同时应用于图题注与表题注")

        entry = styles.get("reference")
        if isinstance(entry, dict):
            blocks.append({
                "key": "references", "kind": "references", "label": "参考文献",
                "enabled": True,
                "styles": {"self": TemplateMigrator._style_from(entry,
                                                                config)},
                "settings": {"legacy_style": entry},
            })

        cfg_toc = config.get("toc") if isinstance(config.get("toc"), dict) \
            else {}
        if cfg_toc.get("detected"):
            blocks.append({
                "key": "toc", "kind": "toc", "label": "目录", "enabled": True,
                "styles": {"self": default_style},
            })

        cfg_cover = config.get("cover")
        if isinstance(cfg_cover, dict) and cfg_cover.get("detected"):
            notes.append("检测到旧封面结构，但封面版式在 style.docx 中，"
                         "无法迁移为 v2（建议另行提供 cover.docx 母版）")

        if not blocks:
            notes.append("旧解析未提供样式信息，未生成 blocks"
                         "（渲染时使用默认样式）")
        return blocks

    # ------------------------------------------------------------------
    # 样式映射（旧 config.styles.<role> = {name, font, paragraph}）
    # ------------------------------------------------------------------
    @staticmethod
    def _style_from(entry: dict, config: dict) -> dict:
        font = entry.get("font") if isinstance(entry.get("font"), dict) else {}
        para = (entry.get("paragraph")
                if isinstance(entry.get("paragraph"), dict) else {})
        default_font = TemplateMigrator._default_font(config)

        style = {
            "font_family": {
                "east_asia": (font.get("east_asia")
                              or default_font.get("east_asia")
                              or DEFAULT_EAST_ASIA_FONT),
                "latin": (font.get("ascii")
                          or default_font.get("ascii")
                          or DEFAULT_LATIN_FONT),
            },
            "font_size_pt": (font.get("size_pt")
                             or default_font.get("size_pt") or 12.0),
            "bold": bool(font.get("bold")),
            "italic": False,
            "underline": False,
            "alignment": TemplateMigrator._norm_alignment(
                para.get("alignment")),
            "line_spacing": TemplateMigrator._norm_line_spacing(
                para.get("line_spacing")),
            "space_before_pt": (para.get("space_before_pt")
                                if TemplateMigrator._is_num(
                                    para.get("space_before_pt")) else 0.0),
            "space_after_pt": (para.get("space_after_pt")
                               if TemplateMigrator._is_num(
                                   para.get("space_after_pt")) else 0.0),
            "first_line_indent": TemplateMigrator._norm_indent(
                para.get("first_line_indent_pt")),
            "keep_with_next": False,
            "page_break_before": False,
        }
        return style

    @staticmethod
    def _default_style(config: dict) -> dict:
        default_font = TemplateMigrator._default_font(config)
        return {
            "font_family": {
                "east_asia": default_font.get("east_asia")
                or DEFAULT_EAST_ASIA_FONT,
                "latin": default_font.get("ascii") or DEFAULT_LATIN_FONT,
            },
            "font_size_pt": default_font.get("size_pt") or 12.0,
            "bold": False, "italic": False, "underline": False,
            "alignment": "justify",
            "line_spacing": {"mode": "multiple", "value": 1.5},
            "space_before_pt": 0.0, "space_after_pt": 0.0,
            "first_line_indent": {"unit": "chars", "value": 0},
            "keep_with_next": False, "page_break_before": False,
        }

    @staticmethod
    def _default_font(config: dict) -> dict:
        fonts = config.get("fonts")
        default = (fonts.get("default")
                   if isinstance(fonts, dict)
                   and isinstance(fonts.get("default"), dict) else {})
        return default

    # ------------------------------------------------------------------
    # 旧值规范化（依据外部引擎 parse_template.py 的实际输出格式）
    # ------------------------------------------------------------------
    @staticmethod
    def _norm_alignment(value: Any) -> str:
        """旧格式 str(WD_ALIGN_PARAGRAPH.X) == 'CENTER (1)' → 'center'。"""
        if not isinstance(value, str):
            return "justify"
        name = value.split("(")[0].strip().lower()
        if name in ("left", "center", "right", "justify"):
            return name
        if name in ("distribute", "both"):
            return "justify"  # v2 无 DISTRIBUTE 枚举
        return "justify"

    @staticmethod
    def _norm_line_spacing(value: Any) -> dict:
        """旧解析器把行距折叠为数值，规则（固定/倍数）未记录 → 按倍数处理。"""
        if TemplateMigrator._is_num(value):
            return {"mode": "multiple", "value": float(value)}
        return {"mode": "multiple", "value": 1.5}

    @staticmethod
    def _norm_indent(value: Any) -> dict:
        """旧 first_line_indent_pt（pt）→ {unit: 'pt', value}。"""
        if TemplateMigrator._is_num(value) and float(value) > 0:
            return {"unit": "pt", "value": round(float(value), 2)}
        return {"unit": "chars", "value": 0}

    @staticmethod
    def _is_num(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    # ------------------------------------------------------------------
    # 失败报告
    # ------------------------------------------------------------------
    @staticmethod
    def _fail(code: str, message: str,
              source_version: int | None) -> MigrationReport:
        return MigrationReport(success=False, migrated=False,
                               source_version=source_version,
                               template=None,
                               notes=[f"{code}: {message}"])
