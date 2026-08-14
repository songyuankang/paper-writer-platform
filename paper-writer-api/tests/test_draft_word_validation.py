from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.draft.service import DraftService


def _service_with_fallback_outline(temp_dir: str, task_id: str) -> DraftService:
    service = DraftService(task_id, Path(temp_dir) / task_id)
    paper_info = {
        "title": "测试论文",
        "major": "工学·计算机类",
        "paper_type": "毕业论文",
        "word_count": 1000,
        "keywords": ["测试"],
        "references": [],
    }
    with mock.patch("app.draft.service.deepseek.is_enabled", return_value=False):
        service.build(paper_info)
    return service


def test_oneclick_marks_completed_only_when_body_reaches_minimum() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service_with_fallback_outline(temp_dir, "enough")
        with mock.patch.object(DraftService, "_model_ctx", return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat", return_value="测" * 600):
            draft = service.oneclick()

        assert draft["word_status"] == "completed"
        assert draft["progress"] == 100
        assert draft["word_stats"]["actual"] >= draft["word_stats"]["minimum"]


def test_oneclick_exposes_shortfall_after_limited_supplement_rounds() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service_with_fallback_outline(temp_dir, "short")
        with mock.patch.object(DraftService, "_model_ctx", return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat", return_value="短"):
            draft = service.oneclick()

        assert draft["word_status"] == "shortfall"
        assert draft["progress"] == 98
        assert draft["supplement_rounds"] == 2
        assert draft["word_stats"]["shortfall"] > 0
