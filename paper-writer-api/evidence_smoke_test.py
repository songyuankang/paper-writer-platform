"""No-LLM smoke test for the auditable evidence chain."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.models.evidence import EvidencePlanRequest, EvidenceSelection
from app.services.data_chart_service import generate_real_charts
from app.services.evidence_fetch_service import fetch_confirmed_evidence
from app.services.evidence_planner import plan_evidence


OUTPUT = Path("outputs") / "evidence_smoke_test"


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    request = EvidencePlanRequest(
        title="数字化转型与企业创新研究",
        abstract="研究数字化转型与创新投入环境之间的关系。",
        keywords=["数字化", "创新"],
        references=["示例参考文献：数字化转型研究"],
        major="工商管理",
        country_code="CHN",
        start_year=2019,
        end_year=2024,
    )
    plan = plan_evidence(request)
    assert plan.planner_mode == "rules_fallback"
    assert len(plan.candidates) >= 2, "数字化与创新主题应获得两个白名单候选"

    result = fetch_confirmed_evidence(OUTPUT, EvidenceSelection(candidate=plan.candidates[0]))
    raw = OUTPUT / result.raw_path
    csv = OUTPUT / result.normalized_path
    audit = OUTPUT / "evidence" / "evidence_audit.json"
    confirmed = OUTPUT / "evidence" / "confirmed_sources.json"
    confirmed.write_text(json.dumps({"candidate": plan.candidates[0].model_dump()}, ensure_ascii=False, indent=2), encoding="utf-8")

    assert raw.is_file(), "应保存世界银行原始响应"
    assert csv.is_file(), "应写出标准化 CSV"
    assert audit.is_file(), "应写出审计记录"
    rows = csv.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "year,value" and len(rows) >= 3, "CSV 必须包含至少两条真实观测值"
    audit_data = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_data[-1]["validation"]["passed"] is True
    assert result.chart_config["data_origin"] == "real"
    assert result.chart_config["data_file"] == result.normalized_path
    charts = generate_real_charts(OUTPUT, "管理学", result.chart_config)
    assert charts and all((OUTPUT / "charts" / chart["file"]).is_file() for chart in charts), "真实 CSV 应生成图表文件"
    print(json.dumps({
        "planner_mode": plan.planner_mode,
        "candidate_count": len(plan.candidates),
        "selected_indicator": result.candidate.indicator_code,
        "row_count": result.row_count,
        "chart_count": len(charts),
        "normalized_path": result.normalized_path,
        "audit_path": "evidence/evidence_audit.json",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
