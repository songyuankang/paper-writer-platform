from pathlib import Path

from app.models.generate import GenerateRequest
from app.services.quality_service import write_quality_report


def _request() -> GenerateRequest:
    return GenerateRequest(
        title="质量报告测试",
        major="计算机科学",
        paper_type="课程论文",
        references=["A verified-looking reference"],
    )


def test_quality_report_is_written_and_marks_citations_pending(tmp_path: Path):
    (tmp_path / "paper_content").mkdir()
    (tmp_path / "paper_content" / "references.json").write_text(
        '["Ref A", "Ref B"]', encoding="utf-8"
    )
    report = write_quality_report(tmp_path, _request())
    assert report["citations"]["generated_reference_count"] == 2
    assert report["citations"]["verification_status"] == "pending_manual_review"
    assert (tmp_path / "quality_report.json").exists()
    assert (tmp_path / "QualityReport.md").exists()
