from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.draft.service import DraftService


def _service_with_ready_outline(temp_dir: str, task_id: str) -> DraftService:
    """Build a deterministic AI-quality-approved outline for word-count tests."""
    service = DraftService(task_id, Path(temp_dir) / task_id)
    paper_info = {
        "title": "轻量化目标检测算法性能优化研究",
        "major": "工学·计算机类",
        "paper_type": "毕业论文",
        "word_count": 1000,
        "keywords": ["目标检测", "算法", "性能优化"],
        "references": ["目标检测性能研究"],
    }
    sections = [
        {"id": "1", "number": "第一章", "title": "目标检测研究背景", "level": 1, "gist": "说明研究问题", "paragraphs": [], "children": []},
        {"id": "2", "number": "第二章", "title": "轻量化算法设计", "level": 1, "gist": "说明算法方法", "paragraphs": [], "children": []},
        {"id": "3", "number": "第三章", "title": "实验与性能验证", "level": 1, "gist": "说明实验结果", "paragraphs": [], "children": []},
    ]
    meta = {
        "source": "ai",
        "is_generation_ready": True,
        "outline_quality": "pass",
        "block_reasons": [],
        "confirmation_required": False,
        "confirmed": True,
    }
    with mock.patch("app.draft.service.outline_mod.build_outline_with_meta", return_value=(sections, meta)):
        service.build(paper_info)
    return service


def test_oneclick_marks_completed_only_when_body_reaches_minimum() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service_with_ready_outline(temp_dir, "enough")
        with mock.patch.object(DraftService, "_model_ctx", return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat", return_value="测" * 600):
            draft = service.oneclick()

        assert draft["word_status"] == "completed"
        assert draft["progress"] == 100
        assert draft["word_stats"]["actual"] >= draft["word_stats"]["minimum"]


def test_oneclick_exposes_shortfall_after_limited_supplement_rounds() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service_with_ready_outline(temp_dir, "short")
        with mock.patch.object(DraftService, "_model_ctx", return_value=nullcontext()), \
             mock.patch("app.draft.service.deepseek.chat", return_value="短"):
            draft = service.oneclick()

        assert draft["word_status"] == "shortfall"
        assert draft["progress"] == 98
        assert draft["supplement_rounds"] == 2
        assert draft["word_stats"]["shortfall"] > 0
