from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.draft.service import DraftService


def test_draft_export_forwards_english_abstract_and_keywords_to_renderer() -> None:
    with TemporaryDirectory() as temp_dir:
        task_dir = Path(temp_dir) / "export-en"
        service = DraftService("export-en", task_dir)
        service.save({
            "title": "测试论文",
            "meta": {
                "major": "工学",
                "paper_type": "毕业论文",
                "word_count": 3000,
                "reference_style": "gb7714",
            },
            "abstract": {"zh": "中文摘要", "en": "English abstract body."},
            "keywords": {"zh": ["中文关键词"], "en": ["English keyword", "second keyword"]},
            "acknowledgement": "",
            "references": [],
            "sections": [],
        })
        captured: dict = {}

        def fake_format(task_id, output_dir, paper, spec, **kwargs):
            captured["spec"] = spec
            return []

        with mock.patch("app.draft.service.formatter_service.format_paper", side_effect=fake_format):
            service.export()

        meta = captured["spec"]["meta"]
        assert meta["abstract_en"] == "English abstract body."
        assert meta["keywords_en"] == ["English keyword", "second keyword"]
