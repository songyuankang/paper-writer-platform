"""模板系统单元测试（unittest，stdlib，无第三方依赖）。

覆盖：
- Loader：JSON 缺字段 / JSON 非法 / 顶层非对象 / schema_version 不一致 /
         cover.docx 存在与缺失
- Repository：内置扫描 / 读取 / CRUD / 内置只读 / 非法 id / 模板 id 唯一 /
             默认唯一性
- Service：默认回退链 / resolve 别名与缺失回退 / legacy 识别 / 复制溯源

运行：``python -m unittest tests.test_template_system -v``（在 paper-writer-api 目录）
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 保证可独立运行：把项目根加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.db import get_conn, init_db  # noqa: E402
from app.formatter.template import (  # noqa: E402
    Template,
    TemplateBlock,
    TemplateLoadError,
    TemplateMeta,
    TemplateMigrator,
    TemplateService,
    TemplateStyle,
    TemplateType,
    TemplateValidator,
    ValidationResult,
    build_services,
)


def make_style(**overrides) -> dict:
    """生成标准 TextBlock dict，可用 overrides 覆盖。"""
    style = {
        "font_family": {"east_asia": "宋体", "latin": "Times New Roman"},
        "font_size_pt": 12,
        "bold": False,
        "italic": False,
        "underline": False,
        "alignment": "justify",
        "line_spacing": {"mode": "multiple", "value": 1.5},
        "space_before_pt": 0,
        "space_after_pt": 0,
        "first_line_indent": {"unit": "chars", "value": 2},
        "keep_with_next": False,
        "page_break_before": False,
    }
    style.update(overrides)
    return style


def make_template_dict(name: str = "测试模板", template_id: str = "",
                       ttype: str = "basic", schema_version: int = 2,
                       blocks: list | None = None,
                       major: str = "") -> dict:
    """生成完整模板 JSON dict。"""
    return {
        "schema_version": schema_version,
        "meta": {
            "id": template_id,
            "name": name,
            "type": ttype,
            "school": "测试大学" if ttype == "school" else "",
            "major": major,
            "category": "学位论文",
            "description": "测试用",
            "version": 1,
            "builtin": ttype != "mine",
        },
        "page": {
            "size": "A4",
            "orientation": "portrait",
            "margins": {"top_mm": 25, "bottom_mm": 25,
                        "left_mm": 30, "right_mm": 25},
            "header_distance_mm": 15,
            "footer_distance_mm": 17.5,
        },
        "header": {"content": "", "style": make_style(alignment="center")},
        "footer": {"content": "{page}", "style": make_style(alignment="center")},
        "numbering": {
            "enabled": True,
            "h1": "第{chinese}章",
            "h2": "{h1}.{n}",
            "h3": "{h1}.{h2}.{n}",
            "h4": "{h1}.{h2}.{h3}.{n}",
        },
        "blocks": blocks if blocks is not None else [
            {"key": "title_zh", "kind": "title_zh", "label": "标题",
             "enabled": True,
             "styles": {"self": make_style(font_size_pt=22)}},
            {"key": "abstract", "kind": "abstract", "label": "摘要",
             "enabled": True,
             "styles": {"title": make_style(), "content": make_style()}},
            {"key": "heading1", "kind": "heading", "label": "一级标题",
             "level": 1, "enabled": True,
             "styles": {"self": make_style()}},
            {"key": "body", "kind": "paragraph", "label": "正文",
             "enabled": True, "styles": {"self": make_style()}},
            {"key": "references", "kind": "references", "label": "参考文献",
             "enabled": True,
             "styles": {"title": make_style(), "item": make_style()},
             "settings": {"style": "gb7714"}},
        ],
    }


def make_old_rules(**overrides) -> dict:
    """旧 rules.json 格式（与 formatter/templates/default/rules.json 一致）。"""
    rules = {
        "toc": {"auto": True, "page_numbers": True, "title_numbering": True},
        "page": {"margins": {"top_cm": 3.0, "bottom_cm": 2.5,
                               "left_cm": 3.0, "right_cm": 2.5}},
        "reference": {"style": "gb7714", "auto_sort": True,
                       "auto_number": True},
        "chart": {"numbering": "chapter", "position": "auto",
                   "title_format": "图{chapter}-{index} {title}"},
        "fonts": {"east_asia": "宋体", "latin": "Times New Roman"},
    }
    rules.update(overrides)
    return rules


def make_old_meta(**overrides) -> dict:
    """旧 template.json 元数据格式。"""
    meta = {
        "name": "学校模板",
        "school_name": "测试大学",
        "major": "计算机科学与技术",
        "paper_type": "毕业论文",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    meta.update(overrides)
    return meta


def make_old_config(**overrides) -> dict:
    """旧 template_config.json 格式（外部引擎 parse_template 输出）。"""
    config = {
        "page": {
            "page_width_cm": 21.0, "page_height_cm": 29.7,
            "top_margin_cm": 3.0, "bottom_margin_cm": 2.5,
            "left_margin_cm": 3.0, "right_margin_cm": 2.5,
            "header_distance_cm": 1.5, "footer_distance_cm": 1.75,
            "page_number_format": "decimal",
            "header": {"has_content": False},
            "footer": {"has_content": True},
        },
        "fonts": {"default": {"east_asia": "宋体", "ascii": "Times New Roman",
                                "size_pt": 12}},
        "styles": {
            "heading1": {"name": "标题 1",
                          "font": {"name": "标题 1", "east_asia": "黑体",
                                    "ascii": "Times New Roman",
                                    "size_pt": 16, "bold": True},
                          "paragraph": {"alignment": "CENTER (1)",
                                         "line_spacing": 1.5,
                                         "space_before_pt": 12,
                                         "space_after_pt": 6,
                                         "first_line_indent_pt": None}},
            "heading2": {"name": "标题 2",
                          "font": {"east_asia": "黑体", "size_pt": 14},
                          "paragraph": {"alignment": "LEFT (0)",
                                         "line_spacing": 1.5}},
            "heading3": {"name": "标题 3",
                          "font": {"east_asia": "黑体", "size_pt": 13},
                          "paragraph": {"alignment": "LEFT (0)",
                                         "line_spacing": 1.5}},
            "body": {"name": "正文",
                      "font": {"east_asia": "宋体", "ascii": "Times New Roman",
                                "size_pt": 12},
                      "paragraph": {"alignment": "JUSTIFY (3)",
                                     "line_spacing": 1.5,
                                     "space_before_pt": 0, "space_after_pt": 0,
                                     "first_line_indent_pt": 24}},
            "caption": {"name": "题注",
                         "font": {"east_asia": "宋体", "size_pt": 10.5},
                         "paragraph": {"alignment": "CENTER (1)",
                                        "line_spacing": 1.0}},
            "reference": {"name": "参考文献",
                           "font": {"east_asia": "宋体", "size_pt": 10.5},
                           "paragraph": {"alignment": "LEFT (0)",
                                          "line_spacing": 1.25}},
        },
        "toc": {"detected": True, "field_paragraphs": [5]},
        "cover": {"detected": True,
                   "fields": [{"keyword": "论文题目", "key": "title"}]},
    }
    config.update(overrides)
    return config


def make_legacy_bundle(**overrides) -> dict:
    """旧模板三件套打包（带 schema_version=1）。"""
    bundle = {"schema_version": 1, "meta": make_old_meta(),
              "rules": make_old_rules(), "config": make_old_config()}
    bundle.update(overrides)
    return bundle


class TemplateSystemTestCase(unittest.TestCase):
    """基类：隔离的临时模板库 + 临时 DB。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tpltest_")
        self.root = Path(self._tmp) / "templates"
        (self.root / "basic").mkdir(parents=True)
        (self.root / "school").mkdir(parents=True)
        self._orig_db = settings.db_path
        settings.db_path = Path(self._tmp) / "test.db"
        init_db()
        self.repo, self.loader, self.service = build_services(self.root)

    def tearDown(self):
        settings.db_path = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- helpers ----
    def write_basic(self, stem: str, data: dict):
        (self.root / "basic" / f"{stem}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_school(self, slug: str, data: dict):
        d = self.root / "school" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "template.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def add_mine_record(self, template_id: str, name: str,
                        content: str | None = None,
                        legacy: bool = False,
                        major: str = "") -> None:
        """直接向 DB 插入我的模板记录（构造边界场景）。"""
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO format_templates
                    (id, name, school_name, major, paper_type, type, category,
                     description, version, schema_version, source, content,
                     parent_id, is_favorite, is_default, sort_order, dir,
                     created_at, updated_at, legacy)
                VALUES (?, ?, '', ?, '', 'mine', ?, ?, 1, 2, 'db', ?, NULL,
                        0, 0, 0, NULL, ?, ?, ?)
                """,
                (template_id, name, major, "测试", "测试描述", content,
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                 1 if legacy else 0),
            )


# =====================================================================
# Loader 测试
# =====================================================================
class TestLoader(TemplateSystemTestCase):

    def test_load_valid_template(self):
        self.write_basic("gen", make_template_dict("完整模板",
                                                   major="计算机科学与技术"))
        tpl = self.loader.load_template(self.root / "basic" / "gen.json")
        self.assertIsInstance(tpl, Template)
        self.assertEqual(tpl.meta.name, "完整模板")
        self.assertEqual(tpl.meta.type, TemplateType.BASIC)
        self.assertEqual(tpl.meta.major, "计算机科学与技术")
        self.assertEqual(len(tpl.blocks), 5)
        self.assertEqual(tpl.page["size"], "A4")
        # 样式对象化
        self.assertIsInstance(tpl.blocks[0].styles["self"], TemplateStyle)
        self.assertAlmostEqual(tpl.blocks[0].styles["self"].font_size_pt, 22)

    def test_major_missing_defaults_empty(self):
        # 旧模板没有 major 字段 → 默认为空串
        self.write_basic("old", make_template_dict("旧模板"))
        tpl = self.loader.load_template(self.root / "basic" / "old.json")
        self.assertEqual(tpl.meta.major, "")
        meta = self.loader.load_meta(self.root / "basic" / "old.json")
        self.assertEqual(meta.major, "")

    def test_major_roundtrip_to_dict(self):
        self.write_basic("gen", make_template_dict("模板", major="软件工程"))
        tpl = self.loader.load_template(self.root / "basic" / "gen.json")
        d = tpl.meta.to_dict()
        self.assertEqual(d["major"], "软件工程")
        # 经 Template.from_dict 往返一致
        meta2 = Template.from_dict(
            {"schema_version": 2, "meta": d, "blocks": []},
            template_id="basic-gen").meta
        self.assertEqual(meta2.major, "软件工程")

    def test_json_missing_fields(self):
        # 只有 meta.name，其余全部缺失 → 默认填充不抛异常
        self.write_basic("min", {"meta": {"name": "最简"}})
        tpl = self.loader.load_template(self.root / "basic" / "min.json")
        self.assertEqual(tpl.meta.name, "最简")
        self.assertEqual(tpl.meta.type, TemplateType.MINE)  # 缺失默认 mine
        self.assertEqual(tpl.schema_version, 2)
        self.assertEqual(tpl.blocks, [])
        self.assertEqual(tpl.page, {})
        # style 兜底
        style = TemplateStyle.from_dict(None)
        self.assertAlmostEqual(style.font_size_pt, 12)
        self.assertEqual(style.alignment.value, "justify")

    def test_json_invalid(self):
        (self.root / "basic" / "bad.json").write_text(
            "{ not valid json !!!", encoding="utf-8")
        with self.assertRaises(TemplateLoadError):
            self.loader.read_json(self.root / "basic" / "bad.json")
        # Repository.get 内置损坏 → None（不抛）
        self.write_basic("gen", make_template_dict())
        self.assertIsNotNone(self.repo.get("basic-gen"))
        (self.root / "basic" / "gen.json").write_text(
            "###broken###", encoding="utf-8")
        self.assertIsNone(self.repo.get("basic-gen"))

    def test_json_top_level_not_object(self):
        (self.root / "basic" / "arr.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8")
        with self.assertRaises(TemplateLoadError):
            self.loader.read_json(self.root / "basic" / "arr.json")

    def test_schema_version_mismatch(self):
        # schema_version 与当前不一致：加载层保留原值（迁移归 Migrator）
        self.write_basic("old", make_template_dict("旧模板", schema_version=1))
        tpl = self.loader.load_template(self.root / "basic" / "old.json")
        self.assertEqual(tpl.schema_version, 1)
        meta = self.loader.load_meta(self.root / "basic" / "old.json")
        self.assertEqual(meta.schema_version, 1)

    def test_cover_docx_missing(self):
        self.write_basic("gen", make_template_dict())
        d = self.root / "basic"
        self.assertIsNone(self.loader.cover_docx_path(d))
        self.assertFalse(self.loader.has_cover(d))

    def test_cover_docx_exists(self):
        self.write_basic("gen", make_template_dict())
        cover = self.root / "basic" / "cover.docx"
        cover.write_bytes(b"PK\x03\x04 fake docx")
        self.assertEqual(self.loader.cover_docx_path(self.root / "basic"),
                         cover)
        self.assertTrue(self.loader.has_cover(self.root / "basic"))


# =====================================================================
# Repository 测试
# =====================================================================
class TestRepository(TemplateSystemTestCase):

    def test_scan_and_list(self):
        self.write_basic("a", make_template_dict("A"))
        self.write_basic("b", make_template_dict("B"))
        self.write_school("pku", make_template_dict("北大", ttype="school"))
        metas = self.repo.list_meta()
        ids = [m.id for m in metas]
        self.assertIn("basic-a", ids)
        self.assertIn("basic-b", ids)
        self.assertIn("school-pku", ids)
        # basic 排前
        self.assertTrue(ids.index("basic-a") < ids.index("school-pku"))
        # type 过滤
        school_only = self.repo.list_meta(type="school")
        self.assertEqual([m.id for m in school_only], ["school-pku"])

    def test_template_id_unique(self):
        # 同 slug 的 school 与 basic 前缀不同不冲突；同目录内不重复
        self.write_basic("x", make_template_dict())
        self.write_school("x", make_template_dict("校", ttype="school"))
        idx = self.repo.builtin_files()
        self.assertEqual(len(idx), len(set(idx)))
        self.assertIn("basic-x", idx)
        self.assertIn("school-x", idx)
        # mine 每次生成唯一 uuid
        t = self.service.create("唯一测试")
        t2 = self.service.create("唯一测试2")
        self.assertNotEqual(t.meta.id, t2.meta.id)

    def test_get_builtin(self):
        self.write_basic("gen", make_template_dict("完整"))
        tpl = self.repo.get("basic-gen")
        self.assertIsInstance(tpl, Template)
        self.assertEqual(tpl.meta.type, TemplateType.BASIC)
        self.assertTrue(tpl.meta.builtin)

    def test_invalid_id(self):
        self.write_basic("gen", make_template_dict())
        self.assertIsNone(self.repo.get(""))
        self.assertIsNone(self.repo.get(None))
        self.assertIsNone(self.repo.get("not-exist"))
        self.assertIsNone(self.repo.get_meta("not-exist"))
        self.assertIsNone(self.repo.template_dir("not-exist"))

    def test_mine_crud(self):
        self.write_basic("gen", make_template_dict("基础"))
        tpl = self.service.create("我的模板", category="毕业论文")
        mid = tpl.meta.id
        self.assertEqual(tpl.meta.type, TemplateType.MINE)
        # 读取
        got = self.repo.get(mid)
        self.assertIsNotNone(got)
        self.assertEqual(got.meta.name, "我的模板")
        # 更新（version+1，样式生效）
        got.blocks[0].styles["self"].font_size_pt = 24
        updated = self.service.update(mid, got)
        self.assertEqual(updated.meta.version, 2)
        self.assertAlmostEqual(
            updated.blocks[0].styles["self"].font_size_pt, 24)
        # 删除
        self.assertTrue(self.service.delete(mid))
        self.assertIsNone(self.repo.get(mid))
        self.assertFalse(self.service.delete(mid))

    def test_row_to_meta_maps_major(self):
        # DB 中 major 列有值 → _row_to_meta 正确映射
        self.add_mine_record("mine-major", "我的模板", major="自动化")
        meta = self.repo.get_meta("mine-major")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.major, "自动化")
        # 旧记录 major 为空 → 回退空串
        self.add_mine_record("mine-old", "旧记录")
        self.assertEqual(self.repo.get_meta("mine-old").major, "")

    def test_builtin_readonly(self):
        self.write_basic("gen", make_template_dict())
        tpl = self.repo.get("basic-gen")
        with self.assertRaises(PermissionError):
            self.service.update("basic-gen", tpl)
        self.assertFalse(self.service.delete("basic-gen"))

    def test_default_unique(self):
        self.write_basic("a", make_template_dict("A"))
        self.write_basic("b", make_template_dict("B"))
        self.assertTrue(self.repo.set_default("basic-a"))
        self.assertEqual(self.repo.default_id(), "basic-a")
        self.assertTrue(self.repo.set_default("basic-b"))
        self.assertEqual(self.repo.default_id(), "basic-b")
        # 唯一性：只有一个 is_default=1
        with get_conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM format_templates "
                "WHERE is_default = 1").fetchone()["c"]
        self.assertEqual(n, 1)
        # 非法 id
        self.assertFalse(self.repo.set_default("not-exist"))

    def test_set_favorite(self):
        self.write_basic("a", make_template_dict("A"))
        self.assertTrue(self.repo.set_favorite("basic-a", True))
        meta = self.repo.get_meta("basic-a")
        self.assertTrue(meta.is_favorite)
        self.assertTrue(self.repo.set_favorite("basic-a", False))
        self.assertFalse(self.repo.get_meta("basic-a").is_favorite)
        self.assertFalse(self.repo.set_favorite("not-exist", True))


# =====================================================================
# Service 测试（业务规则）
# =====================================================================
class TestService(TemplateSystemTestCase):

    def test_default_fallback_chain(self):
        # 无 is_default → 回退 basic 第一个（按文件名排序 a < z）
        self.write_basic("z", make_template_dict("Z"))
        self.write_basic("a", make_template_dict("A"))
        tpl = self.service.default_template()
        self.assertEqual(tpl.meta.id, "basic-a")  # 排序第一个
        # 设置默认后跟随
        self.repo.set_default("basic-z")
        self.assertEqual(self.service.default_template().meta.id, "basic-z")

    def test_resolve_aliases(self):
        self.write_basic("a", make_template_dict("A"))
        for alias in (None, "", "default", "default_template"):
            tpl = self.service.resolve(alias)
            self.assertIsInstance(tpl, Template)

    def test_resolve_missing_fallback(self):
        self.write_basic("a", make_template_dict("A"))
        tpl = self.service.resolve("not-exist")
        self.assertEqual(tpl.meta.id, "basic-a")  # 回退默认

    def test_legacy_detection(self):
        self.add_mine_record("legacy-1", "旧版模板", content=None, legacy=True)
        self.assertIsNone(self.service.get("legacy-1"))  # 不可加载
        self.assertTrue(self.service.is_legacy("legacy-1"))
        meta = self.service.get_meta("legacy-1")
        self.assertTrue(meta.legacy)

    def test_duplicate_trace(self):
        self.write_basic("a", make_template_dict("学位模板"))
        dup = self.service.duplicate("basic-a")
        self.assertEqual(dup.meta.type, TemplateType.MINE)
        self.assertEqual(dup.meta.parent_id, "basic-a")
        self.assertIn("副本", dup.meta.name)
        # 副本可独立更新
        dup.blocks[0].styles["self"].bold = True
        upd = self.service.update(dup.meta.id, dup)
        self.assertTrue(upd.blocks[0].styles["self"].bold)

    def test_duplicate_missing(self):
        with self.assertRaises(KeyError):
            self.service.duplicate("not-exist")


# =====================================================================
# Validator 测试
# =====================================================================
class TestValidator(unittest.TestCase):
    """模板结构校验器（无 DB / 无文件依赖）。"""

    def setUp(self):
        self.v = TemplateValidator()

    def validate(self, **overrides) -> "ValidationResult":
        data = make_template_dict()
        data.update(overrides)
        return self.v.validate(data)

    # ---- 顶层 / schema_version ----
    def test_valid_template(self):
        result = self.v.validate(make_template_dict())
        self.assertTrue(result.valid)
        self.assertEqual(result.errors(), [])
        self.assertEqual(result.warnings(), [])
        self.assertEqual(result.issues, [])

    def test_top_level_not_object(self):
        result = self.v.validate([1, 2, 3])
        self.assertFalse(result.valid)
        self.assertEqual(result.errors()[0].code, "not_object")

    def test_schema_version_missing(self):
        data = make_template_dict()
        del data["schema_version"]
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.schema_version")[0].code,
                         "missing_field")

    def test_schema_version_wrong_type(self):
        result = self.validate(schema_version="2")
        self.assertEqual(result.by_path("$.schema_version")[0].code,
                         "wrong_type")

    def test_schema_version_mismatch(self):
        result = self.validate(schema_version=1)
        self.assertEqual(result.by_path("$.schema_version")[0].code,
                         "schema_version_mismatch")
        self.assertFalse(result.valid)

    def test_unknown_top_level_field_info(self):
        result = self.validate(extra_top="x")
        info = [i for i in result.issues if i.code == "unknown_field"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0].severity, "info")
        self.assertEqual(info[0].path, "$.extra_top")
        self.assertTrue(result.valid)  # info 不影响 valid

    # ---- meta ----
    def test_meta_missing(self):
        data = make_template_dict()
        del data["meta"]
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.meta")[0].code, "missing_field")

    def test_meta_name_required(self):
        data = make_template_dict()
        del data["meta"]["name"]
        self.assertEqual(self.v.validate(data).by_path("$.meta.name")[0].code,
                         "missing_field")
        data = make_template_dict()
        data["meta"]["name"] = "   "
        self.assertEqual(self.v.validate(data).by_path("$.meta.name")[0].code,
                         "invalid_value")

    def test_meta_type_enum(self):
        data = make_template_dict()
        del data["meta"]["type"]
        self.assertEqual(self.v.validate(data).by_path("$.meta.type")[0].code,
                         "missing_field")
        data = make_template_dict()
        data["meta"]["type"] = "unknown"
        self.assertEqual(self.v.validate(data).by_path("$.meta.type")[0].code,
                         "invalid_enum")

    def test_meta_field_types(self):
        data = make_template_dict()
        data["meta"]["version"] = "1"      # 应为 int
        data["meta"]["builtin"] = 1         # 应为 bool（1 是 int）
        data["meta"]["major"] = 123         # 应为 str
        result = self.v.validate(data)
        codes = {i.path: i.code for i in result.issues}
        self.assertEqual(codes["$.meta.version"], "wrong_type")
        self.assertEqual(codes["$.meta.builtin"], "wrong_type")
        self.assertEqual(codes["$.meta.major"], "wrong_type")

    # ---- blocks ----
    def test_blocks_not_list(self):
        result = self.validate(blocks={"key": "x"})
        self.assertEqual(result.by_path("$.blocks")[0].code, "wrong_type")

    def test_block_required_fields(self):
        data = make_template_dict()
        data["blocks"][0] = {"label": "无key无kind"}
        result = self.v.validate(data)
        codes = {i.path: i.code for i in result.issues}
        self.assertEqual(codes["$.blocks[0].key"], "missing_field")
        self.assertEqual(codes["$.blocks[0].kind"], "missing_field")

    def test_duplicate_key(self):
        data = make_template_dict()
        data["blocks"].append(dict(data["blocks"][0]))  # 复制第一个
        result = self.v.validate(data)
        dup = [i for i in result.issues if i.code == "duplicate_key"]
        self.assertEqual(len(dup), 1)
        self.assertIn("$.blocks[0]", dup[0].message)  # 可定位到首次出现

    def test_unknown_kind_warning(self):
        data = make_template_dict()
        data["blocks"][0]["kind"] = "custom_chart"
        result = self.v.validate(data)
        warn = [i for i in result.issues if i.code == "unknown_kind"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0].severity, "warning")
        self.assertTrue(result.valid)  # warning 不阻断

    def test_heading_missing_level_warning(self):
        data = make_template_dict()
        heading = [b for b in data["blocks"] if b["kind"] == "heading"][0]
        del heading["level"]
        result = self.v.validate(data)
        warn = [i for i in result.issues if i.code == "missing_field"
                and i.path == "$.blocks[2].level"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0].severity, "warning")

    def test_block_unknown_field_info(self):
        data = make_template_dict()
        data["blocks"][0]["custom_prop"] = {"a": 1}
        result = self.v.validate(data)
        info = [i for i in result.issues if i.code == "unknown_field"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0].path, "$.blocks[0].custom_prop")
        self.assertEqual(info[0].severity, "info")
        self.assertTrue(result.valid)

    # ---- styles ----
    def test_style_wrong_type(self):
        data = make_template_dict()
        data["blocks"][0]["styles"] = "not-a-dict"
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.blocks[0].styles")[0].code,
                         "wrong_type")

    def test_style_font_size(self):
        data = make_template_dict()
        data["blocks"][0]["styles"]["self"]["font_size_pt"] = 0
        self.assertEqual(self.v.validate(data).by_path(
            "$.blocks[0].styles.self.font_size_pt")[0].code,
            "out_of_range")
        data = make_template_dict()
        data["blocks"][0]["styles"]["self"]["font_size_pt"] = "22"
        self.assertEqual(self.v.validate(data).by_path(
            "$.blocks[0].styles.self.font_size_pt")[0].code,
            "wrong_type")

    def test_style_enums(self):
        data = make_template_dict()
        s = data["blocks"][0]["styles"]["self"]
        s["alignment"] = "middle"
        s["line_spacing"]["mode"] = "fixed"
        s["first_line_indent"]["unit"] = "em"
        result = self.v.validate(data)
        codes = {i.path: i.code for i in result.issues}
        self.assertEqual(codes["$.blocks[0].styles.self.alignment"],
                         "invalid_enum")
        self.assertEqual(
            codes["$.blocks[0].styles.self.line_spacing.mode"],
            "invalid_enum")
        self.assertEqual(
            codes["$.blocks[0].styles.self.first_line_indent.unit"],
            "invalid_enum")

    def test_style_bool_type(self):
        data = make_template_dict()
        data["blocks"][0]["styles"]["self"]["bold"] = 1  # int 不是 bool
        result = self.v.validate(data)
        self.assertEqual(result.by_path(
            "$.blocks[0].styles.self.bold")[0].code, "wrong_type")

    def test_style_negative_space(self):
        data = make_template_dict()
        data["blocks"][0]["styles"]["self"]["space_before_pt"] = -5
        result = self.v.validate(data)
        self.assertEqual(result.by_path(
            "$.blocks[0].styles.self.space_before_pt")[0].code,
            "out_of_range")

    def test_style_unknown_field_info(self):
        data = make_template_dict()
        data["blocks"][0]["styles"]["self"]["char_spacing"] = 1.1
        result = self.v.validate(data)
        info = [i for i in result.issues if i.code == "unknown_field"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0].path,
                         "$.blocks[0].styles.self.char_spacing")

    # ---- page / header / footer / numbering ----
    def test_page_orientation(self):
        data = make_template_dict()
        data["page"]["orientation"] = "diagonal"
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.page.orientation")[0].code,
                         "invalid_enum")

    def test_page_margins_negative(self):
        data = make_template_dict()
        data["page"]["margins"]["left_mm"] = -1
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.page.margins.left_mm")[0].code,
                         "out_of_range")

    def test_page_unknown_size_warning(self):
        data = make_template_dict()
        data["page"]["size"] = "XXL"
        result = self.v.validate(data)
        warn = [i for i in result.issues if i.code == "unknown_value"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0].severity, "warning")

    def test_header_style_validated(self):
        data = make_template_dict()
        data["header"]["style"]["alignment"] = "middle"
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.header.style.alignment")[0].code,
                         "invalid_enum")

    def test_numbering_enabled_type(self):
        data = make_template_dict()
        data["numbering"]["enabled"] = "yes"
        result = self.v.validate(data)
        self.assertEqual(result.by_path("$.numbering.enabled")[0].code,
                         "wrong_type")

    # ---- Template 对象 / 结果 API ----
    def test_validate_template_object(self):
        tpl = Template.from_dict(make_template_dict(), template_id="basic-x")
        result = self.v.validate_template(tpl)
        self.assertTrue(result.valid)
        self.assertEqual(result.issues, [])

    def test_result_as_dict(self):
        result = self.validate(schema_version=1)
        d = result.as_dict()
        self.assertFalse(d["valid"])
        self.assertEqual(d["error_count"], 1)
        self.assertEqual(d["issues"][0]["path"], "$.schema_version")
        self.assertIn("code", d["issues"][0])
        self.assertIn("severity", d["issues"][0])

    def test_builtin_templates_all_valid(self):
        """真实内置模板应全部通过校验（0 error / 0 warning）。"""
        from app.formatter.template import DEFAULT_TEMPLATES_ROOT
        from app.formatter.template.loader import TemplateLoader
        loader = TemplateLoader(DEFAULT_TEMPLATES_ROOT)
        for path in loader.basic_files():
            result = self.v.validate(loader.read_json(path))
            self.assertTrue(
                result.valid, f"{path.name} 校验失败: "
                f"{[i.as_dict() for i in result.errors()]}")
            self.assertEqual(
                result.warnings(), [], f"{path.name} 出现 warning")


# =====================================================================
# Migrator 测试
# =====================================================================
class TestMigrator(unittest.TestCase):
    """模板迁移器（无 DB / 无文件依赖；migrate_file 用临时目录）。"""

    def setUp(self):
        self.m = TemplateMigrator()

    # ---- 已是 v2 → 不重复迁移 ----
    def test_v2_noop(self):
        report = self.m.migrate(make_template_dict())
        self.assertTrue(report.success)
        self.assertFalse(report.migrated)      # 未重复迁移
        self.assertEqual(report.source_version, 2)
        self.assertIsNotNone(report.template)
        self.assertEqual(report.template.schema_version, 2)
        self.assertEqual(len(report.template.blocks), 5)  # 原样保留

    def test_v2_missing_schema_structure(self):
        # 无 schema_version 但结构是 v2 → 按 v2 处理，校验会报缺 schema_version
        data = make_template_dict()
        del data["schema_version"]
        report = self.m.migrate(data)
        self.assertFalse(report.migrated)
        self.assertFalse(report.success)  # 校验失败（缺 schema_version）
        self.assertTrue(report.validation.by_path("$.schema_version"))

    # ---- v1 三件套 → v2 ----
    def test_v1_bundle_to_v2(self):
        report = self.m.migrate(make_legacy_bundle())
        self.assertTrue(report.success)
        self.assertTrue(report.migrated)
        self.assertEqual(report.source_version, 1)
        tpl = report.template
        self.assertEqual(tpl.schema_version, 2)
        # meta 映射
        self.assertEqual(tpl.meta.name, "学校模板")
        self.assertEqual(tpl.meta.school_name, "测试大学")
        self.assertEqual(tpl.meta.major, "计算机科学与技术")
        self.assertEqual(tpl.meta.category, "毕业论文")  # paper_type → category
        self.assertEqual(tpl.meta.type, TemplateType.MINE)
        self.assertEqual(tpl.meta.source, "migrated")
        # page：cm→mm 精确换算 + A4 + portrait
        self.assertEqual(tpl.page["margins"]["top_mm"], 30.0)
        self.assertEqual(tpl.page["margins"]["left_mm"], 30.0)
        self.assertEqual(tpl.page["margins"]["bottom_mm"], 25.0)
        self.assertEqual(tpl.page["size"], "A4")
        self.assertEqual(tpl.page["orientation"], "portrait")
        self.assertEqual(tpl.page["header_distance_mm"], 15.0)
        self.assertEqual(tpl.page["footer_distance_mm"], 17.5)
        # footer 有内容 → 页码占位
        self.assertEqual(tpl.footer["content"], "{page}")
        # numbering
        self.assertTrue(tpl.numbering["enabled"])
        # blocks：heading1 / body / figure+table_caption / references / toc
        keys = [b.key for b in tpl.blocks]
        self.assertIn("heading1", keys)
        self.assertIn("heading2", keys)
        self.assertIn("heading3", keys)
        self.assertIn("body", keys)
        self.assertIn("figure_caption", keys)
        self.assertIn("table_caption", keys)
        self.assertIn("references", keys)
        self.assertIn("toc", keys)
        # 迁移后必须通过 Validator
        self.assertTrue(report.validation.valid)

    def test_v1_style_mapping(self):
        report = self.m.migrate(make_legacy_bundle())
        tpl = report.template
        h1 = tpl.get_block("heading1")
        self.assertIsNotNone(h1)
        self.assertEqual(h1.level, 1)
        s = h1.styles["self"]
        self.assertEqual(s.font_family_east_asia, "黑体")
        self.assertEqual(s.font_size_pt, 16)
        self.assertTrue(s.bold)
        self.assertEqual(s.alignment.value, "center")   # 'CENTER (1)' → center
        self.assertEqual(s.space_before_pt, 12)
        self.assertEqual(s.space_after_pt, 6)
        # 正文首行缩进 pt
        body = tpl.get_block("body")
        bi = body.styles["self"].first_line_indent_unit.value
        self.assertEqual(bi, "pt")
        self.assertEqual(body.styles["self"].first_line_indent_value, 24)
        # 行距倍数
        self.assertEqual(s.line_spacing_mode.value, "multiple")
        self.assertEqual(s.line_spacing_value, 1.5)
        # 旧样式整体保留（无损）
        self.assertEqual(h1.settings["legacy_style"]["font"]["east_asia"],
                         "黑体")

    # ---- 缺失 schema_version 的旧模板 ----
    def test_missing_schema_rules_flat(self):
        # 扁平 rules.json（顶层带旧 template.json 字段）
        data = dict(make_old_rules())
        data.update(make_old_meta())
        report = self.m.migrate(data)
        self.assertTrue(report.success)
        self.assertTrue(report.migrated)
        tpl = report.template
        self.assertEqual(tpl.meta.name, "学校模板")
        self.assertEqual(tpl.meta.category, "毕业论文")
        self.assertEqual(tpl.page["margins"]["top_mm"], 30.0)

    def test_missing_schema_old_meta_only(self):
        # 只有旧 template.json（无 rules/config）
        report = self.m.migrate(make_old_meta())
        self.assertTrue(report.success)
        self.assertTrue(report.migrated)
        tpl = report.template
        self.assertEqual(tpl.meta.name, "学校模板")
        self.assertEqual(tpl.meta.major, "计算机科学与技术")
        self.assertEqual(tpl.meta.category, "毕业论文")
        self.assertEqual(tpl.blocks, [])  # 无样式信息 → 无 blocks
        self.assertIn("未提供样式信息", " | ".join(report.notes))

    # ---- 不支持的版本 ----
    def test_unsupported_version(self):
        report = self.m.migrate({"schema_version": 99})
        self.assertFalse(report.success)
        self.assertEqual(report.source_version, 99)
        self.assertTrue(any("unsupported" in n for n in report.notes))
        self.assertIsNone(report.template)

    def test_invalid_version_type(self):
        report = self.m.migrate({"schema_version": "2"})
        self.assertFalse(report.success)
        self.assertTrue(any("invalid_version" in n for n in report.notes))

    # ---- 非法 / 无法识别的旧模板 ----
    def test_not_object(self):
        self.assertFalse(self.m.migrate([1, 2, 3]).success)
        self.assertFalse(self.m.migrate("abc").success)
        self.assertFalse(self.m.migrate(None).success)

    def test_unrecognized_format(self):
        report = self.m.migrate({"foo": "bar", "hello": 1})
        self.assertFalse(report.success)
        self.assertTrue(any("unrecognized" in n for n in report.notes))

    # ---- 未知字段保留（无损） ----
    def test_unknown_fields_preserved(self):
        data = make_legacy_bundle()
        data["custom_top_field"] = {"a": 1}
        data["meta"]["custom_meta"] = "keep-me"
        report = self.m.migrate(data)
        self.assertTrue(report.success)
        out = report.template.to_dict()
        # 顶层未知字段 → 整体保留到 legacy.extra（无损）
        self.assertEqual(out["legacy"]["extra"]["custom_top_field"],
                         {"a": 1})
        # legacy 段整体保留旧内容
        self.assertEqual(out["legacy"]["meta"]["name"], "学校模板")
        self.assertEqual(out["legacy"]["rules"]["toc"]["auto"], True)
        # 旧 meta 未知字段保留在 legacy.meta（v2 meta 模型不保留未知键）
        self.assertEqual(out["legacy"]["meta"]["custom_meta"], "keep-me")

    def test_v1_with_blocks_preserved(self):
        # 自相矛盾的 v1：带 blocks → blocks 原样保留到 legacy.extra
        data = make_legacy_bundle()
        data["blocks"] = [{"key": "x", "kind": "custom"}]
        report = self.m.migrate(data)
        self.assertTrue(report.success)
        out = report.template.to_dict()
        self.assertEqual(out["legacy"]["extra"]["blocks"],
                         [{"key": "x", "kind": "custom"}])

    # ---- 迁移后 Validator 通过（所有成功路径） ----
    def test_all_success_paths_validated(self):
        for data in (make_legacy_bundle(),
                     {**make_old_rules(), **make_old_meta()},
                     make_old_meta()):
            report = self.m.migrate(data)
            self.assertTrue(report.success)
            self.assertTrue(report.validation.valid)
            self.assertIsNotNone(report.template)
            self.assertEqual(report.template.schema_version, 2)

    def test_bundle_without_config(self):
        # 只有 meta + rules（无 config）→ 成功，page 用 rules 边距
        report = self.m.migrate({"schema_version": 1,
                                 "meta": make_old_meta(),
                                 "rules": make_old_rules()})
        self.assertTrue(report.success)
        self.assertEqual(report.template.page["margins"]["top_mm"], 30.0)
        # 无 config → 无 styles → 无 blocks
        self.assertEqual(report.template.blocks, [])

    # ---- migrate_file：迁移失败不覆盖原文件 ----
    def test_migrate_file_writes_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "old.json"
            p.write_text(json.dumps(make_legacy_bundle(), ensure_ascii=False),
                         encoding="utf-8")
            report = self.m.migrate_file(p)
            self.assertTrue(report.success)
            self.assertTrue(report.migrated)
            content = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(content["schema_version"], 2)
            # 写回结果可通过 Validator
            self.assertTrue(TemplateValidator().validate(content).valid)

    def test_migrate_file_failure_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 不支持版本 → 不写回
            p = Path(tmp) / "bad.json"
            original = {"schema_version": 99, "name": "原样"}
            p.write_text(json.dumps(original), encoding="utf-8")
            report = self.m.migrate_file(p)
            self.assertFalse(report.success)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                             original)  # 未被覆盖
            # 非法 JSON → 不写回
            p.write_text("{ broken json", encoding="utf-8")
            report = self.m.migrate_file(p)
            self.assertFalse(report.success)
            self.assertEqual(p.read_text(encoding="utf-8"), "{ broken json")
            # v2 文件 → 不重复迁移、不写回
            p.write_text(json.dumps(make_template_dict()), encoding="utf-8")
            report = self.m.migrate_file(p)
            self.assertTrue(report.success)
            self.assertFalse(report.migrated)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))[
                "schema_version"], 2)

    def test_migrate_file_unrecognized_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            original = {"foo": "bar"}
            p.write_text(json.dumps(original), encoding="utf-8")
            report = self.m.migrate_file(p)
            self.assertFalse(report.success)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")),
                             original)

    # ---- 旧字段无法自动迁移 → 明确报告 ----
    def test_unmappable_fields_reported(self):
        report = self.m.migrate(make_legacy_bundle())
        joined = " | ".join(report.notes)
        self.assertIn("页脚文本无法从解析结果恢复", joined)
        self.assertIn("封面", joined)

    def test_missing_title_numbering_reported(self):
        data = make_legacy_bundle()
        del data["rules"]["toc"]["title_numbering"]
        report = self.m.migrate(data)
        self.assertTrue(report.success)
        self.assertTrue(any("title_numbering" in n for n in report.notes))
        self.assertTrue(report.template.numbering["enabled"])  # 默认启用

    def test_migrate_bundle_helper(self):
        report = self.m.migrate_bundle(meta=make_old_meta(),
                                       rules=make_old_rules(),
                                       config=make_old_config())
        self.assertTrue(report.success)
        self.assertTrue(report.migrated)
        self.assertEqual(report.template.meta.name, "学校模板")

    def test_migrate_report_as_dict(self):
        report = self.m.migrate(make_legacy_bundle())
        d = report.as_dict()
        self.assertTrue(d["success"])
        self.assertTrue(d["migrated"])
        self.assertEqual(d["source_version"], 1)
        self.assertTrue(d["validation"]["valid"])
        self.assertIsInstance(d["notes"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
