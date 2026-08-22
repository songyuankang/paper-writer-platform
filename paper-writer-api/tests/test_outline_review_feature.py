from unittest import mock

import pytest

from app.draft.outline import _extract_json
from app.draft.service import DraftService


def _paper_info() -> dict:
    return {
        "title": "轻量化目标检测模型剪枝与量化联合优化研究",
        "major": "工学·计算机类",
        "paper_type": "毕业论文",
        "word_count": 5000,
        "abstract": "研究面向边缘部署的目标检测模型剪枝和量化联合优化。",
        "keywords": ["目标检测", "模型剪枝", "量化", "嵌入式部署"],
        "special_requirements": "比较剪枝率、精度和推理延迟。",
        "references": ["[1] Lightweight Object Detection for Edge Devices"],
    }


def test_extract_json_accepts_first_object_before_trailing_json():
    data, error = _extract_json(
        '{"sections":[{"title":"定制绪论","level":1,"children":[]}]}'
        '\n{"diagnostic":"ignored trailing object"}'
    )
    assert error is None
    assert data is not None
    assert data["sections"][0]["title"] == "定制绪论"


def test_outline_review_metadata_confirmation_and_structure_edit(tmp_path):
    service = DraftService("outline-review-test", tmp_path)
    with mock.patch("app.draft.outline.deepseek.is_enabled", return_value=False):
        draft = service.build(_paper_info(), require_confirmation=True)

    meta = draft["outline_meta"]
    assert meta["source"] == "fallback"
    assert meta["template_risk"] == "high"
    assert meta["research_type"] == "technical"
    assert meta["confirmation_required"] is True
    assert meta["confirmed"] is False

    assert meta["is_generation_ready"] is False
    assert meta["outline_quality"] == "blocked"
    with pytest.raises(ValueError, match="质量未通过"):
        service.ensure_outline_confirmed()
    with pytest.raises(ValueError, match="不能确认"):
        service.confirm_outline()
    with pytest.raises(ValueError, match="质量未通过"):
        service.oneclick()

    # 回退结构仍然只是可编辑预览，供用户检查和重新生成前参考。
    added = service.add_outline_section("部署约束与工程实现")
    updated = service.load()
    assert any(section["title"] == "部署约束与工程实现" for section in updated["sections"])
    service.delete_outline_section(added["id"])
    assert all(section["title"] != "部署约束与工程实现" for section in service.load()["sections"])
