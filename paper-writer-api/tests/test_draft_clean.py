"""DraftService AI 输出清洗/拆段单元测试。

覆盖：
- ``_clean_generated_paragraphs`` 纯函数：普通多段、Markdown 标题剔除、单段、
  引用 [1][2] 保留、粗体/斜体/列表等 Markdown 标记剔除、空段过滤、
  单换行合并、逐行句子拆段
- ``generate_section`` 真实链路（mock AI）：一个 section 拆成多个 paragraph、
  paragraph ID 唯一且符合现有规则、原 ID 保留、生成失败仍为单段

运行：``python -m unittest discover -s tests -v``
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draft.service import (  # noqa: E402
    DraftService,
    _clean_generated_paragraphs,
    _split_en_abstract,
)

PAPER_INFO = {
    "title": "测试论文",
    "major": "工学·计算机类",
    "paper_type": "毕业论文",
    "word_count": 3000,
    "special_requirements": "",
    "keywords": ["测试"],
    "reference_style": "gb7714",
    "references": [],
}


def _make_service(tmp: Path, task_id: str = "drafttest") -> DraftService:
    task_dir = tmp / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return DraftService(task_id, task_dir, task_manager=None)


def _build(service: DraftService) -> None:
    """构建草稿：确定性 fallback 大纲（不依赖真实 AI/DB）。"""
    with mock.patch.object(DraftService, "_model_ctx",
                           return_value=nullcontext()), \
         mock.patch("app.draft.service.deepseek.is_enabled",
                    return_value=False):
        service.build(PAPER_INFO)


def _leaf_section(service: DraftService) -> dict:
    draft = service.load()
    return next(s for s in draft["sections"] if s["level"] == 2)


def _leaf_paragraphs(service: DraftService) -> list[dict]:
    draft = service.load()
    sid = _leaf_section(service)["id"]
    return next(s["paragraphs"] for s in draft["sections"]
                if s["id"] == sid)


def _generate(service: DraftService, ai_text: str) -> dict:
    """mock AI 返回 ``ai_text``，调用 ``generate_section``。"""
    with mock.patch.object(DraftService, "_model_ctx",
                           return_value=nullcontext()), \
         mock.patch("app.draft.service.deepseek.chat",
                    return_value=ai_text):
        return service.generate_section(_leaf_section(service)["id"], None)


class TestCleanGeneratedParagraphs(unittest.TestCase):
    """``_clean_generated_paragraphs`` 纯函数测试。"""

    def test_multiple_paragraphs(self):
        # A. 普通多段（空行分隔）
        self.assertEqual(
            _clean_generated_paragraphs("第一段。\n\n第二段。\n\n第三段。"),
            ["第一段。", "第二段。", "第三段。"])

    def test_removes_markdown_headings(self):
        # B. Markdown 标题不能进入 paragraph
        self.assertEqual(
            _clean_generated_paragraphs(
                "## 工业质检\n\n第一段。\n\n### 数据采集\n\n第二段。"),
            ["第一段。", "第二段。"])

    def test_single_paragraph(self):
        # C. 普通单段 → 一个 paragraph
        self.assertEqual(
            _clean_generated_paragraphs("这是一个普通单段文本，内容完整。"),
            ["这是一个普通单段文本，内容完整。"])

    def test_keeps_citations(self):
        # D. [1][2] 引用必须保留
        self.assertEqual(
            _clean_generated_paragraphs(
                "制造业数字化转型受到多种因素影响[1][2]。"),
            ["制造业数字化转型受到多种因素影响[1][2]。"])

    def test_removes_bold_italic_code(self):
        # E. 粗体/斜体/代码等 Markdown 标记不原样保存
        self.assertEqual(
            _clean_generated_paragraphs("这是**重要**内容和*斜体*及`代码`。"),
            ["这是重要内容和斜体及代码。"])

    def test_removes_list_markers(self):
        self.assertEqual(
            _clean_generated_paragraphs("- 第一点\n- 第二点\n\n正文。"),
            ["第一点 第二点", "正文。"])

    def test_filters_empty_segments(self):
        # F. 连续空行不能产生空 paragraph
        self.assertEqual(
            _clean_generated_paragraphs("\n\n第一段。\n\n\n\n第二段。\n\n"),
            ["第一段。", "第二段。"])

    def test_single_newline_joins_within_paragraph(self):
        # 单个换行视为同一自然段内部换行（合并时以空格连接）
        self.assertEqual(
            _clean_generated_paragraphs("第一段第一行\n第一段第二行\n\n第二段"),
            ["第一段第一行 第一段第二行", "第二段"])

    def test_sentence_per_line_splits(self):
        # 逐行段落：每行都以句末标点结尾 → 按行拆段
        self.assertEqual(
            _clean_generated_paragraphs("第一段。\n第二段。\n第三段。"),
            ["第一段。", "第二段。", "第三段。"])

    def test_heading_only_text_returns_empty(self):
        self.assertEqual(_clean_generated_paragraphs("## 只有标题"), [])

    def test_filters_internal_generation_instructions_and_draft_labels(self):
        text = (
            "现在起草段落。\n\n"
            "需要满足约915字。让我们具体计算，每个段落约180-230字。\n\n"
            "现在写正式内容。注意不要输出标题，不要用markdown，段落间空行。\n\n"
            "让我们慢慢构思内容。\n\n"
            "第一段具体草稿：\n\n"
            "留学生群体的身份认同受到教育制度与跨文化经验的共同影响[1]。"
        )
        self.assertEqual(
            _clean_generated_paragraphs(text),
            ["留学生群体的身份认同受到教育制度与跨文化经验的共同影响[1]。"],
        )


class TestSplitEnAbstract(unittest.TestCase):
    """英文摘要 Keywords 拆分测试。"""

    def test_extracts_keywords(self):
        abstract, keywords = _split_en_abstract(
            "Abstract: This is the abstract text.\nKeywords: a, b, c")
        self.assertEqual(abstract, "This is the abstract text.")
        self.assertEqual(keywords, ["a", "b", "c"])

    def test_handles_chinese_colon_and_mixed_separators(self):
        abstract, keywords = _split_en_abstract(
            "Abstract：EN text.\nKeywords：k1，k2; k3")
        self.assertEqual(abstract, "EN text.")
        self.assertEqual(keywords, ["k1", "k2", "k3"])

    def test_no_keywords_line(self):
        abstract, keywords = _split_en_abstract("Plain abstract text.")
        self.assertEqual(abstract, "Plain abstract text.")
        self.assertEqual(keywords, [])

    def test_rejects_prompt_leak_and_placeholders(self):
        abstract, keywords = _split_en_abstract(
            "我们需要按用户要求来做：翻译摘要为英文，给出英文关键词。"
            "格式：Abstract: <英文摘要>；Keywords: <英文关键词>。"
            "注意用户给的是中文摘要内容，需要准确翻译。"
        )
        self.assertEqual(abstract, "")
        self.assertEqual(keywords, [])


class TestGenerateSectionCleaning(unittest.TestCase):
    """``generate_section`` 真实链路（mock AI）测试。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.service = _make_service(Path(self._tmp.name))
        _build(self.service)

    def tearDown(self):
        self._tmp.cleanup()

    def test_mock_ai_multiple_paragraphs(self):
        # H. mock AI 返回含标题的多段 → 拆成多个干净 paragraph
        _generate(self.service,
                  "## 测试小标题\n\n第一段正文[1]。\n\n第二段正文[2]。")
        paras = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras), 2)
        self.assertEqual(paras[0]["text"], "第一段正文[1]。")
        self.assertEqual(paras[1]["text"], "第二段正文[2]。")

    def test_no_heading_in_paragraph_text(self):
        _generate(self.service, "## 小标题\n\n正文段落内容。")
        paras = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras), 1)
        self.assertNotIn("##", paras[0]["text"])
        self.assertNotIn("小标题", paras[0]["text"])
        self.assertEqual(paras[0]["text"], "正文段落内容。")

    def test_generation_does_not_persist_internal_writing_instructions(self):
        _generate(
            self.service,
            "现在起草段落。\n\n需要满足约915字，每个段落约180-230字。\n\n"
            "现在写正式内容。注意不要输出标题，不要用markdown。\n\n"
            "第一段具体草稿：\n\n"
            "留学生在跨文化环境中会持续调整其身份认同边界[1]。",
        )
        paras = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0]["text"], "留学生在跨文化环境中会持续调整其身份认同边界[1]。")

    def test_paragraph_ids_unique_and_preserved(self):
        # G. 1 段扩展为多段：ID 唯一、原 ID 保留、新 ID 符合现有规则
        _generate(self.service, "第一段。\n\n第二段。\n\n第三段。")
        paras1 = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras1), 3)
        ids1 = [p["id"] for p in paras1]
        self.assertEqual(len(set(ids1)), 3)
        for pid in ids1:
            self.assertRegex(pid, r"^p\d+-[0-9a-f]{6}$")
        first = paras1[0]["id"]
        # 再次生成：追加新段落，原 ID 保留，全部唯一
        _generate(self.service, "第四段。")
        paras2 = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras2), 4)
        self.assertEqual(paras2[0]["id"], first)
        self.assertEqual(paras2[0]["text"], "第一段。")
        all_ids = [p["id"] for p in paras2]
        self.assertEqual(len(set(all_ids)), len(all_ids))

    def test_generation_failure_keeps_single_message(self):
        from app.services import deepseek as ds
        with mock.patch.object(DraftService, "_model_ctx",
                               return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat",
                        side_effect=ds.DeepSeekError("boom")):
            self.service.generate_section(
                _leaf_section(self.service)["id"], None)
        paras = _leaf_paragraphs(self.service)
        self.assertEqual(len(paras), 1)
        self.assertTrue(paras[0]["text"].startswith("（生成失败"))

    def test_generate_en_abstract_splits_keywords(self):
        # AI 返回 Abstract+Keywords 复合格式 → 摘要与关键词分开存储
        with mock.patch.object(DraftService, "_model_ctx",
                               return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat",
                        return_value="Abstract: EN abstract text.\n"
                                      "Keywords: k1, k2, k3"):
            result = self.service.generate_en_abstract(None)
        draft = self.service.load()
        self.assertEqual(result, "EN abstract text.")
        self.assertEqual(draft["abstract"]["en"], "EN abstract text.")
        self.assertEqual(draft["keywords"]["en"], ["k1", "k2", "k3"])

    def test_generate_en_abstract_does_not_persist_prompt_leak(self):
        with mock.patch.object(DraftService, "_model_ctx",
                               return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat",
                        return_value=(
                            "我们需要按用户要求来做：翻译摘要为英文。"
                            "格式：Abstract: <英文摘要>；Keywords: <英文关键词>。"
                        )):
            result = self.service.generate_en_abstract(None)
        draft = self.service.load()
        self.assertEqual(result, "")
        self.assertEqual(draft["abstract"]["en"], "")
        self.assertEqual(draft["keywords"]["en"], [])


class TestOneclickCompleteness(unittest.TestCase):
    """一键全文应补齐附属内容，但不得覆盖用户已有内容。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.service = _make_service(Path(self._tmp.name), "oneclick-completeness")

    def tearDown(self):
        self._tmp.cleanup()

    def _save_complete_body_draft(self, *, abstract_en: str = "", acknowledgement: str = ""):
        self.service.save({
            "title": "测试论文",
            "meta": {"word_count": 500, "completion_min_chars": 475},
            "abstract": {"zh": "中文摘要", "en": abstract_en},
            "keywords": {"zh": ["测试"], "en": []},
            "acknowledgement": acknowledgement,
            "sections": [{
                "id": "1", "number": "1.1", "title": "测试小节", "level": 2,
                "gist": "测试主旨", "children": [], "target_chars": 500,
                "min_chars": 475,
                "paragraphs": [{"id": "p1", "text": "正" * 500}],
            }],
            "generating": False, "progress": 0, "done": 0, "total": 1,
        })

    def test_oneclick_generates_missing_en_abstract_and_acknowledgement(self):
        self._save_complete_body_draft()
        with mock.patch.object(self.service, "generate_section"), \
             mock.patch.object(self.service, "generate_en_abstract", return_value="English abstract") as generate_en, \
             mock.patch.object(self.service, "generate_acknowledgement", return_value="感谢") as generate_ack:
            self.service.oneclick()
        generate_en.assert_called_once_with(None)
        generate_ack.assert_called_once_with(None)

    def test_oneclick_preserves_existing_en_abstract_and_acknowledgement(self):
        self._save_complete_body_draft(
            abstract_en="Existing English abstract", acknowledgement="Existing acknowledgement"
        )
        with mock.patch.object(self.service, "generate_section"), \
             mock.patch.object(self.service, "generate_en_abstract") as generate_en, \
             mock.patch.object(self.service, "generate_acknowledgement") as generate_ack:
            self.service.oneclick()
        generate_en.assert_not_called()
        generate_ack.assert_not_called()


if __name__ == "__main__":
    unittest.main()
