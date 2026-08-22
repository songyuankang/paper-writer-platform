from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.draft import outline as outline_mod
from app.draft.outline_role_validator import OutlineRoleValidator
from app.draft.service import DraftService
from app.services.full_paper_generation_service import FullPaperGenerationService


TASK = "7" * 32
PAPER = {
    "title": "共同富裕目标下第三次分配对居民收入差距的调节效应研究",
    "major": "经济学",
    "paper_type": "毕业论文",
    "word_count": 8000,
    "keywords": ["共同富裕", "第三次分配", "收入差距"],
    "references": ["[1] 共同富裕研究"],
}


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "history.db",
        output_dir=tmp_path / "outputs",
        upload_dir=tmp_path / "uploads",
        log_dir=tmp_path / "logs",
    )


def bad_sections() -> list[dict]:
    return [
        {"id": "1", "number": "第一章", "level": 1, "title": "绪论", "gist": "", "paragraphs": []},
        {"id": "1-1", "number": "1.1", "level": 2, "title": "研究背景", "gist": "", "paragraphs": []},
        {"id": "1-2", "number": "1.2", "level": 2, "title": "理论基础", "gist": "", "paragraphs": []},
        {"id": "1-3", "number": "1.3", "level": 2, "title": "研究假设", "gist": "", "paragraphs": []},
        {"id": "1-4", "number": "1.4", "level": 2, "title": "基准回归与稳健性检验", "gist": "", "paragraphs": []},
        {"id": "1-5", "number": "1.5", "level": 2, "title": "异质性分析", "gist": "", "paragraphs": []},
        {"id": "1-6", "number": "1.6", "level": 2, "title": "结论与政策建议", "gist": "", "paragraphs": []},
        {"id": "2", "number": "第二章", "level": 1, "title": "研究设计", "gist": "", "paragraphs": []},
    ]


def good_sections() -> list[dict]:
    return [
        {"id": "1", "number": "第一章", "level": 1, "title": "绪论", "gist": "", "paragraphs": []},
        {"id": "1-1", "number": "1.1", "level": 2, "title": "研究背景与意义", "gist": "", "paragraphs": []},
        {"id": "1-2", "number": "1.2", "level": 2, "title": "文献综述与研究内容", "gist": "", "paragraphs": []},
        {"id": "2", "number": "第二章", "level": 1, "title": "理论基础、作用机制与研究假设", "gist": "", "paragraphs": []},
        {"id": "3", "number": "第三章", "level": 1, "title": "研究设计、数据、变量与模型设定", "gist": "", "paragraphs": []},
        {"id": "4", "number": "第四章", "level": 1, "title": "基准回归、稳健性、异质性与机制检验", "gist": "", "paragraphs": []},
        {"id": "5", "number": "第五章", "level": 1, "title": "结论、政策建议与局限", "gist": "", "paragraphs": []},
    ]


def draft_service(tmp_path: Path) -> DraftService:
    settings = settings_for(tmp_path)
    service = DraftService(TASK, settings.output_dir / TASK)
    service.save({
        "title": PAPER["title"],
        "meta": {"major": PAPER["major"], "paper_type": PAPER["paper_type"], "word_count": PAPER["word_count"], "keywords": PAPER["keywords"]},
        "abstract": {"zh": "", "en": ""}, "keywords": {"zh": PAPER["keywords"], "en": []},
        "references": PAPER["references"], "sections": bad_sections(),
        "outline_meta": {"version": 1, "confirmation_required": False, "confirmed": True, "role_repair_attempts": 0},
        "generating": False, "progress": 0, "done": 0, "total": 0,
    })
    return service


def repaired_meta() -> dict:
    return {"version": 2, "source": "ai", "confirmed": False, "confirmation_required": False}


def test_empirical_economics_template_detects_overloaded_introduction():
    result = OutlineRoleValidator.validate(PAPER, bad_sections())
    assert result["profile"] == "empirical_economics"
    assert result["requires_repair"] is True
    issue = next(item for item in result["issues"] if item["code"] == "introduction_role_overload")
    assert {"理论基础", "研究假设", "基准回归", "异质", "结论"}.issubset(set(issue["roles"]))


def test_empirical_economics_template_accepts_separated_roles():
    result = OutlineRoleValidator.validate(PAPER, good_sections())
    assert result["profile"] == "empirical_economics"
    assert result["valid"] is True
    assert result["issues"] == []


def test_full_generation_repairs_bad_outline_once_before_start(tmp_path: Path, monkeypatch):
    service = draft_service(tmp_path)
    monkeypatch.setattr(outline_mod, "build_outline_with_meta", lambda *_args, **_kwargs: (good_sections(), repaired_meta()))
    state = FullPaperGenerationService(service).start()
    current = service.load()
    assert state["status"] == "running"
    assert current["outline_meta"]["role_repair_attempts"] == 1
    assert current["outline_meta"]["role_validation"]["valid"] is True
    assert [(item["id"], item["title"]) for item in current["sections"]] == [(item["id"], item["title"]) for item in good_sections()]


def test_second_bad_role_repair_blocks_until_user_confirms(tmp_path: Path, monkeypatch):
    service = draft_service(tmp_path)
    monkeypatch.setattr(outline_mod, "build_outline_with_meta", lambda *_args, **_kwargs: (bad_sections(), repaired_meta()))
    pipeline = FullPaperGenerationService(service)
    with pytest.raises(ValueError, match="连续两次未通过"):
        pipeline.start()
    blocked = service.load()["outline_meta"]
    assert blocked["role_repair_attempts"] == 1
    assert blocked["role_repair_failed"] is True
    assert blocked["confirmed"] is False

    service.confirm_outline()
    state = pipeline.start()
    assert state["status"] == "running"
    assert service.load()["outline_meta"]["role_validation"]["user_confirmed"] is True
