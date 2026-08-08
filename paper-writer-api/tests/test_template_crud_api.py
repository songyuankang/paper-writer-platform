"""模板管理 CRUD API 与 Renderer 冒烟测试。

覆盖：创建/非法创建/获取/更新/内置只读/删除/duplicate/set-default/
默认唯一/路径穿越/新建与修改模板后的 Renderer 实际配置。

运行：``python -m unittest tests.test_template_crud_api -v``
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docx import Document  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.api import templates as api  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import get_conn, init_db  # noqa: E402
from app.formatter.template import (  # noqa: E402
    DEFAULT_TEMPLATES_ROOT,
    build_services,
)
from app.models.template import TemplateWriteRequest  # noqa: E402


def make_style(**overrides) -> dict:
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


def write_request(name: str = "我的模板", **overrides) -> TemplateWriteRequest:
    data = {
        "name": name,
        "description": "自定义描述",
        "category": "毕业论文",
        "paper_type": "毕业论文",
        "school_name": "测试大学",
        "major": "计算机科学与技术",
        "page": {
            "size": "A5",
            "orientation": "portrait",
            "margins": {"top_mm": 20, "bottom_mm": 20,
                        "left_mm": 25, "right_mm": 20},
            "header_distance_mm": 12,
            "footer_distance_mm": 14,
        },
        "numbering": {
            "enabled": True,
            "h1": "第{chinese}章",
            "h2": "{h1}.{n}",
            "h3": "{h1}.{h2}.{n}",
            "h4": "{h1}.{h2}.{h3}.{n}",
        },
        "toc": {"enabled": True, "include_page_numbers": True},
        "reference_style": "apa",
    }
    data.update(overrides)
    return TemplateWriteRequest(**data)


def make_spec() -> dict:
    return {
        "meta": {
            "title": "模板冒烟测试",
            "abstract": "测试摘要",
            "keywords": ["测试"],
            "reference_style": "gb7714",
        },
        "sections": [
            {"type": "h1", "text": "引言"},
            {"type": "p", "text": "正文段落"},
            {"type": "references", "items": []},
        ],
        "references": [],
    }


class TemplateCrudApiTestCase(unittest.TestCase):
    """临时 DB + 真实模板目录 + patch API / render_service 的 get_service。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tplcrud_")
        self._orig_db = settings.db_path
        settings.db_path = Path(self._tmp) / "test.db"
        init_db()
        _repo, _loader, service = build_services(DEFAULT_TEMPLATES_ROOT)
        service.set_default("basic-general-thesis")
        self.service = service
        self._api_patcher = patch("app.api.templates.get_service",
                                  return_value=service)
        self._api_patcher.start()
        self._render_patcher = patch(
            "app.formatter.template.render_service.get_service",
            return_value=service)
        self._render_patcher.start()

    def tearDown(self):
        self._api_patcher.stop()
        self._render_patcher.stop()
        settings.db_path = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)

    def create(self, **overrides) -> dict:
        return api.create_template(write_request(**overrides))


class TestTemplateCrud(TemplateCrudApiTestCase):

    def test_create_template(self):
        dto = self.create(name="新建模板")
        self.assertTrue(dto["editable"])
        self.assertEqual(dto["source"], "mine")
        self.assertEqual(dto["paper_type"], "毕业论文")
        self.assertEqual(dto["major"], "计算机科学与技术")
        self.assertEqual(dto["school_name"], "测试大学")
        self.assertEqual(dto["page"]["size"], "A5")
        self.assertEqual(dto["reference_style"], "apa")
        self.assertEqual(dto["version"], 1)
        self.assertIsNotNone(self.service.get(dto["id"]))

    def test_create_invalid_template_rejected(self):
        blocks = [
            {"key": "title_zh", "kind": "title_zh",
             "styles": {"self": make_style()}},
            {"key": "title_zh", "kind": "title_zh",
             "styles": {"self": make_style()}},
        ]
        with self.assertRaises(HTTPException) as ctx:
            self.create(name="非法模板", blocks=blocks)
        self.assertEqual(ctx.exception.status_code, 422)
        detail = ctx.exception.detail
        codes = [i["code"] for i in detail["issues"]]
        self.assertIn("duplicate_key", codes)

    def test_create_invalid_font_rejected(self):
        blocks = [{
            "key": "title_zh",
            "kind": "title_zh",
            "styles": {"self": make_style(font_family={
                "east_asia": "../evil",
                "latin": "Times New Roman",
            })},
        }]
        with self.assertRaises(HTTPException) as ctx:
            self.create(name="非法字体", blocks=blocks)
        self.assertEqual(ctx.exception.status_code, 422)
        codes = [i["code"] for i in ctx.exception.detail["issues"]]
        self.assertIn("invalid_font", codes)

    def test_get_created_template(self):
        dto = self.create()
        got = api.template_detail(dto["id"])
        self.assertEqual(got["id"], dto["id"])
        self.assertTrue(any(b["key"] == "body" for b in got["blocks"]))
        body = next(b for b in got["blocks"] if b["key"] == "body")
        self.assertIn("self", body["styles"])

    def test_update_mine_template(self):
        dto = self.create(name="初始名称")
        req = write_request(
            name="修改后名称",
            major="软件工程",
            paper_type="课程论文",
            page={"size": "A4", "orientation": "portrait",
                  "margins": {"top_mm": 25, "bottom_mm": 25,
                              "left_mm": 30, "right_mm": 25},
                  "header_distance_mm": 15,
                  "footer_distance_mm": 17.5},
        )
        updated = api.update_template(dto["id"], req)
        self.assertEqual(updated["name"], "修改后名称")
        self.assertEqual(updated["major"], "软件工程")
        self.assertEqual(updated["paper_type"], "课程论文")
        self.assertEqual(updated["page"]["size"], "A4")
        self.assertEqual(updated["version"], 2)

    def test_update_builtin_fails(self):
        with self.assertRaises(HTTPException) as ctx:
            api.update_template(
                "basic-general-thesis", write_request(name="不允许"))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_update_school_fails(self):
        # 临时模板库里没有 school，直接构造一条 school 类型记录
        from app.formatter.template.models import Template, TemplateMeta
        from app.formatter.template.repository import TemplateRepository
        school_id = "school-fake"
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO format_templates
                    (id, name, type, school_name, created_at, updated_at)
                VALUES (?, ?, 'school', '测试学校', ?, ?)
                """,
                (school_id, "学校模板",
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        # repo.get 对无文件 school 返回 None，改用 service.update 直接验证 type 保护
        tpl = Template(meta=TemplateMeta(
            id=school_id, name="学校模板", type="school"))
        repo = TemplateRepository(self.service.loader)
        with self.assertRaises(PermissionError):
            repo.update(school_id, tpl)

    def test_delete_mine_template(self):
        dto = self.create()
        result = api.delete_template(dto["id"])
        self.assertEqual(result["deleted"], dto["id"])
        with self.assertRaises(HTTPException) as ctx:
            api.template_detail(dto["id"])
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_builtin_fails(self):
        with self.assertRaises(HTTPException) as ctx:
            api.delete_template("basic-general-thesis")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_duplicate_template(self):
        dto = api.duplicate_template(
            "basic-general-thesis",
            api.TemplateDuplicateRequest(name="我的副本"))
        self.assertEqual(dto["source"], "mine")
        self.assertTrue(dto["editable"])
        self.assertEqual(dto["name"], "我的副本")
        stored = self.service.get(dto["id"])
        self.assertEqual(stored.meta.parent_id, "basic-general-thesis")

    def test_set_default_and_unique(self):
        a = self.create(name="模板A")
        b = self.create(name="模板B")
        result = api.set_default_template(a["id"])
        self.assertEqual(result["default_id"], a["id"])
        result = api.set_default_template(b["id"])
        self.assertEqual(result["default_id"], b["id"])
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM format_templates "
                "WHERE is_default = 1").fetchone()
        self.assertEqual(row["c"], 1)
        self.assertEqual(self.service.repo.default_id(), b["id"])

    def test_path_traversal_rejected(self):
        for bad_id in ("../../etc/passwd", "..\\..\\secret", "../x"):
            with self.assertRaises(HTTPException) as ctx:
                api.template_detail(bad_id)
            self.assertEqual(ctx.exception.status_code, 404)
            with self.assertRaises(HTTPException) as ctx:
                api.update_template(bad_id, write_request())
            self.assertEqual(ctx.exception.status_code, 404)


class TestRendererUsesTemplateConfig(TemplateCrudApiTestCase):
    """新建/修改模板后，TemplateRenderer 必须使用新配置。"""

    def test_created_and_updated_template_render(self):
        dto = self.create(name="渲染配置模板")
        # 修改正文样式为 20pt，并保持其它区块不变
        detail = api.template_detail(dto["id"])
        body = next(b for b in detail["blocks"] if b["key"] == "body")
        body["styles"]["self"]["font_size_pt"] = 20
        updated = api.update_template(
            dto["id"], TemplateWriteRequest(blocks=detail["blocks"]))
        self.assertEqual(updated["version"], 2)

        task_dir = Path(self._tmp) / "render-smoke"
        task_dir.mkdir(parents=True, exist_ok=True)
        from app.formatter.template import render_service
        out = render_service.render_with_template(
            dto["id"], task_dir, make_spec(), paper_info=None)
        self.assertTrue(out.is_file())
        doc = Document(str(out))
        sec = doc.sections[0]
        self.assertAlmostEqual(sec.page_width.mm, 148, places=1)
        paras = [p for p in doc.paragraphs if p.text == "正文段落"]
        self.assertTrue(paras)
        run = paras[0].runs[0]
        self.assertAlmostEqual(run.font.size.pt, 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
