from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.draft.service import DraftService


def test_section_generation_prompt_includes_leaf_target_and_minimum() -> None:
    paper_info = {
        "title": "测试论文",
        "major": "工学·计算机类",
        "paper_type": "毕业论文",
        "word_count": 3000,
        "keywords": ["测试"],
        "references": [],
    }
    with TemporaryDirectory() as temp_dir:
        service = DraftService("length-test", Path(temp_dir) / "length-test")
        with mock.patch("app.draft.service.deepseek.is_enabled", return_value=False):
            draft = service.build(paper_info)
        # 本测试只验证 section prompt 的长度预算；显式提供已审核 AI 大纲状态，
        # 不再依赖被产品安全门禁禁止的 fallback → 正文生成路径。
        draft["outline_meta"] = {
            "source": "ai", "is_generation_ready": True, "outline_quality": "pass",
            "block_reasons": [], "confirmation_required": False, "confirmed": True,
        }
        service.save(draft)
        section = next(
            item for item in draft["sections"]
            if item.get("target_chars") and item.get("gist")
        )
        captured: dict[str, str] = {}

        def fake_chat(messages):
            captured["user"] = messages[-1]["content"]
            return "这是满足长度约束的测试正文。"

        with mock.patch.object(DraftService, "_model_ctx", return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat", side_effect=fake_chat):
            service.generate_section(section["id"])

        assert str(section["target_chars"]) in captured["user"]
        assert str(section["min_chars"]) in captured["user"]
