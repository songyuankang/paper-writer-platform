"""模板管理 API 测试。

覆盖：模板列表（含三个内置）/ 默认模板标记 / 模板详情 / 404 / template_id
传递与默认值 / 生成流程不破坏旧流程。

运行：``python -m unittest discover -s tests -v``
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

from fastapi import HTTPException  # noqa: E402

from app.api import templates as api  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.formatter.template import (  # noqa: E402
    DEFAULT_TEMPLATES_ROOT,
    build_services,
)
from app.models.generate import GenerateRequest  # noqa: E402

BUILTIN_IDS = ["basic-general-thesis", "basic-graduation-thesis",
               "basic-course-paper"]


class TemplatesApiTestCase(unittest.TestCase):
    """临时 DB + 真实模板目录 + patch app.api.templates.get_service。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tplapi_")
        self._orig_db = settings.db_path
        settings.db_path = Path(self._tmp) / "test.db"
        init_db()
        _repo, _loader, service = build_services(DEFAULT_TEMPLATES_ROOT)
        # 显式指定默认模板，保证测试确定性（默认行为=DB is_default）
        service.set_default("basic-general-thesis")
        self.service = service
        self._patcher = patch("app.api.templates.get_service",
                              return_value=service)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        settings.db_path = self._orig_db
        shutil.rmtree(self._tmp, ignore_errors=True)


class TestListTemplates(TemplatesApiTestCase):
    def test_list_contains_three_builtin(self):
        data = api.list_templates()
        self.assertIn("items", data)
        ids = {item["id"] for item in data["items"]}
        for bid in BUILTIN_IDS:
            self.assertIn(bid, ids)

    def test_item_dto_fields(self):
        data = api.list_templates()
        for item in data["items"]:
            for field in ("id", "name", "description", "category", "source"):
                self.assertIn(field, item, item)
        general = next(i for i in data["items"]
                       if i["id"] == "basic-general-thesis")
        self.assertEqual(general["source"], "builtin")
        self.assertEqual(general["category"], "学位论文")

    def test_default_marked(self):
        data = api.list_templates()
        self.assertIn("default_id", data)
        self.assertIn(data["default_id"], {i["id"] for i in data["items"]})
        default_items = [i for i in data["items"] if i["is_default"]]
        self.assertEqual(len(default_items), 1)
        self.assertEqual(default_items[0]["id"], data["default_id"])


class TestTemplateDetail(TemplatesApiTestCase):
    def test_detail_general(self):
        dto = api.template_detail("basic-general-thesis")
        self.assertEqual(dto["id"], "basic-general-thesis")
        self.assertEqual(dto["source"], "builtin")
        # 页面 / 编号 / 目录 / 参考文献 / 区块 / 样式
        self.assertEqual(dto["page"]["size"], "A4")
        self.assertIn("margins", dto["page"])
        self.assertTrue(dto["numbering"]["enabled"])
        self.assertTrue(dto["toc"]["enabled"])
        self.assertEqual(dto["reference_style"], "gb7714")
        self.assertIsInstance(dto["blocks"], list)
        self.assertTrue(any(b["key"] == "heading1" for b in dto["blocks"]))
        self.assertIn("body", dto["styles"])
        self.assertIn("title", dto["styles"])

    def test_detail_graduation_and_course(self):
        for tid in ("basic-graduation-thesis", "basic-course-paper"):
            dto = api.template_detail(tid)
            self.assertEqual(dto["id"], tid)
            self.assertTrue(dto["blocks"])

    def test_detail_not_found(self):
        with self.assertRaises(HTTPException) as ctx:
            api.template_detail("basic-not-exist")
        self.assertEqual(ctx.exception.status_code, 404)


class TestTemplateIdFlow(TemplatesApiTestCase):
    """template_id 传递与默认值。"""

    def test_generate_request_accepts_template_id(self):
        req = GenerateRequest(title="T", major="M", paper_type="课程论文",
                              template_id="basic-graduation-thesis")
        self.assertEqual(req.template_id, "basic-graduation-thesis")

    def test_generate_request_default_empty(self):
        req = GenerateRequest(title="T", major="M", paper_type="课程论文")
        self.assertEqual(req.template_id, "")

    def test_empty_template_id_resolves_default(self):
        # "" → 默认模板（general-thesis）
        tpl = self.service.resolve("")
        self.assertEqual(tpl.meta.name, "学位论文通用模板")

    def test_generate_flow_keeps_old_path(self):
        # template_id=None → 旧 docx_builder 路径仍可出 docx（不破坏旧流程）
        from app.formatter.service import format_paper
        from app.services.content_generator import build_spec
        task_dir = Path(self._tmp) / "oldtask"
        task_dir.mkdir(parents=True, exist_ok=True)
        spec = build_spec(GenerateRequest(title="旧流程", major="计算机",
                                          paper_type="课程论文"))
        files = format_paper("old", task_dir, {"title": "旧流程"}, spec)
        self.assertTrue((task_dir / "论文.docx").is_file())
        self.assertIn("论文.docx", [f.split("/")[-1] for f in files])


if __name__ == "__main__":
    unittest.main(verbosity=2)
