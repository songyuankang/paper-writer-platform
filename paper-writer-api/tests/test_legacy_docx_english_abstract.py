from pathlib import Path
from tempfile import TemporaryDirectory

from app.formatter.style import engine


def test_default_docx_builder_writes_english_abstract_and_keywords() -> None:
    build_docx, _, _ = engine()
    meta = {
        "title": "测试论文",
        "abstract": "中文摘要",
        "keywords": ["中文关键词"],
        "abstract_en": "English abstract body for export verification.",
        "keywords_en": ["english keyword", "second keyword"],
    }
    with TemporaryDirectory() as temp_dir:
        document = build_docx.setup_document(meta)
        build_docx.build_default(
            document,
            {"meta": meta, "sections": [], "references": []},
            meta,
            Path(temp_dir),
        )

    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert "Abstract" in paragraphs
    assert "English abstract body for export verification." in paragraphs
    assert any(text.startswith("Keywords: english keyword; second keyword") for text in paragraphs)
