"""Phase 9: verified research evidence to confirmable paper visualizations.

The service is intentionally conservative.  It stores evidence separately from
LiteratureEvidence because a numeric datum needs units, source locations and
verification state.  It never invents values, never automatically inserts a
candidate into the paper, and always materialises charts through the existing
DatasetVersion -> ChartSpec v2 -> ChartRenderer -> FigureBlock pipeline.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.draft.chart_runtime import (
    create_lab_chart_from_dataset,
    external_dataset_version,
    insert_chart_into_section,
    upsert_table_dataset,
    walk_sections,
)
from app.draft.service import DraftService
from app.services import deepseek
from app.services.dataset_service import DatasetService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.literature_service import LiteratureSearchService, LiteratureService
from app.services.model_service import resolve_model
from app.services.research_object_service import ResearchObjectService

VERIFIED = "verified"
PENDING = "pending"
CONFLICT = "conflict"
BROKEN = "broken"
STALE = "stale"
SUPPORTED_TABLES = {
    "technology_comparison", "literature_review", "application_comparison",
    "specification_comparison", "descriptive_summary", "correlation_summary",
}

_NUMBER_PATTERN = re.compile(
    r"(?P<value>-?\d+(?:[,.]\d+)?)\s*(?P<unit>V/W|dBi|dBm|mW|µW|uW|kW|GHz|MHz|kHz|Hz|dB|ms|µm|μm|um|cm|mm|m|%|℃|°C|V)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _task_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value or ""):
        raise ValueError("任务 ID 无效")
    return value


def _safe_id(value: str, prefix: str) -> str:
    if not re.fullmatch(fr"{prefix}_[A-Za-z0-9]+", value or ""):
        raise ValueError("记录 ID 无效")
    return value


def _number(value: object) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
        return parsed if parsed == parsed and abs(parsed) < 1e100 else None
    except (TypeError, ValueError):
        return None


def _unit_info(unit: str) -> tuple[str, float, str]:
    raw = _clean(unit, 20).replace("μ", "µ").lower()
    mapping = {
        "µw": ("power_w", 0.000001, "W"), "uw": ("power_w", 0.000001, "W"),
        "mw": ("power_w", 0.001, "W"), "w": ("power_w", 1.0, "W"), "kw": ("power_w", 1000.0, "W"),
        "v/w": ("responsivity_v_per_w", 1.0, "V/W"), "v": ("voltage_v", 1.0, "V"),
        "dbi": ("gain_dbi", 1.0, "dBi"),
        "hz": ("frequency_hz", 1.0, "Hz"), "khz": ("frequency_hz", 1_000.0, "Hz"),
        "mhz": ("frequency_hz", 1_000_000.0, "Hz"), "ghz": ("frequency_hz", 1_000_000_000.0, "Hz"),
        "ms": ("time_s", 0.001, "s"), "s": ("time_s", 1.0, "s"),
        "µm": ("length_m", 0.000001, "m"), "um": ("length_m", 0.000001, "m"),
        "mm": ("length_m", 0.001, "m"), "cm": ("length_m", 0.01, "m"), "m": ("length_m", 1.0, "m"),
        "%": ("percentage", 1.0, "%"), "db": ("db", 1.0, "dB"), "dbm": ("dbm", 1.0, "dBm"),
        "℃": ("temperature_c", 1.0, "°C"), "°c": ("temperature_c", 1.0, "°C"),
    }
    return mapping.get(raw, (f"unit:{raw}", 1.0, unit))


def _metric_hint(text: str) -> str:
    text = _clean(text, 500).lower()
    for key, label in [
        ("responsivity", "响应度"), ("gain", "增益"), ("power", "功耗"), ("功耗", "功耗"), ("frequency", "频率"), ("频率", "频率"),
        ("latency", "时延"), ("delay", "时延"), ("时延", "时延"), ("accuracy", "准确率"),
        ("精度", "精度"), ("range", "探测距离"), ("距离", "探测距离"),
    ]:
        if key in text:
            return label
    return "已核验指标"


class ResearchVisualizationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.db_path.parent / "research_visualizations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.datasets = DatasetService(settings)
        self.literature = LiteratureService(settings)
        self.searcher = LiteratureSearchService(settings)
        self.objects = ResearchObjectService(settings)
        self.graph = DependencyGraphService(settings)

    def _plans(self, task_id: str) -> Path:
        return self.root / "plans" / f"{_task_id(task_id)}.json"

    def _evidence_path(self, evidence_id: str) -> Path:
        return self.root / "evidence" / f"{_safe_id(evidence_id, 're')}.json"

    def _candidate_path(self, candidate_id: str) -> Path:
        return self.root / "candidates" / f"{_safe_id(candidate_id, 'rv')}.json"

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ValueError("未找到研究可视化记录")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("研究可视化记录格式无效") from exc

    def _draft_service(self, task_id: str) -> DraftService:
        service = DraftService(task_id, self.settings.output_dir / task_id)
        if not service.load():
            raise ValueError("请先生成论文草稿，再生成可进入论文的图表或表格候选")
        return service

    @staticmethod
    def _rule_queries(topic: str, chapter: str, question: str) -> list[str]:
        base = _clean(" ".join([topic, question]), 300)
        chapter_text = _clean(chapter, 180)
        queries = [base]
        if chapter_text:
            queries.append(_clean(f"{base} {chapter_text}", 360))
        queries.append(_clean(f"{base} performance comparison", 360))
        return list(dict.fromkeys(query for query in queries if query))[:3]

    def create_plan(self, *, task_id: str, topic: str, chapter: str = "", research_question: str = "", model_id: str | None = None) -> dict[str, Any]:
        task_id = _task_id(task_id)
        topic = _clean(topic, 500)
        if not topic:
            raise ValueError("论文题目或研究主题不能为空")
        chapter, research_question = _clean(chapter, 240), _clean(research_question, 1000)
        queries = self._rule_queries(topic, chapter, research_question)
        provider = "rule_fallback"
        runtime = resolve_model(model_id)
        if runtime:
            prompt = {
                "topic": topic, "chapter": chapter, "research_question": research_question,
                "instruction": "只输出 JSON 对象，键为 queries（最多3个字符串）与 rationale（字符串）。检索词必须围绕公开学术资料或公开数据；不得声明已找到证据、不得给出数字。",
            }
            try:
                output = deepseek.chat_with(runtime.base_url, runtime.api_key, runtime.model, [
                    {"role": "system", "content": "你是严谨的学术资料检索规划助手。仅制定检索词，不编造资料或数值。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ], temperature=0.1, max_tokens=min(runtime.max_tokens, 900), timeout=min(self.settings.deepseek_timeout, 90))
                payload = json.loads(output.strip().removeprefix("```json").removesuffix("```").strip())
                model_queries = [_clean(item, 300) for item in payload.get("queries") or [] if _clean(item, 300)]
                if model_queries:
                    queries = list(dict.fromkeys(model_queries))[:3]
                    provider = "configured_model"
            except Exception:
                pass
        plan = {
            "id": f"rsp_{uuid.uuid4().hex[:16]}", "task_id": task_id, "topic": topic,
            "chapter": chapter, "research_question": research_question, "queries": queries,
            "providers": ["saved_literature", "crossref", "openalex", "dataset"],
            "provider": provider, "status": "planned", "created_at": _now(), "updated_at": _now(),
        }
        self._write(self._plans(task_id), plan)
        return plan

    def plan(self, task_id: str) -> dict[str, Any]:
        return self._read(self._plans(task_id))

    def search(self, *, task_id: str, limit: int = 8) -> dict[str, Any]:
        plan = self.plan(task_id)
        results: list[dict[str, Any]] = []
        for query in plan.get("queries") or []:
            response = self.searcher.search(query=str(query), limit=max(1, min(int(limit), 12)))
            for item in response.get("results") or []:
                results.append({**item, "query": query})
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for item in results:
            key = (str(item.get("doi") or ""), str(item.get("external_id") or item.get("title") or ""))
            unique.setdefault(key, item)
        saved = self.literature.list(plan["task_id"])
        plan.update({"status": "searched", "updated_at": _now(), "search_results": list(unique.values())[:30], "saved_literature_count": len(saved)})
        self._write(self._plans(plan["task_id"]), plan)
        return {"plan": plan, "results": plan["search_results"], "saved_literature": saved}

    def save_sources(self, *, task_id: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        task_id = _task_id(task_id)
        saved: list[dict[str, Any]] = []
        for metadata in sources[:30]:
            saved.append(self.literature.save(task_id=task_id, metadata=metadata))
        self.graph.rebuild_task(task_id)
        return saved

    def _all_evidence(self, task_id: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        directory = self.root / "evidence"
        for path in directory.glob("re_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    values.append(item)
            except json.JSONDecodeError:
                continue
        return sorted(values, key=lambda item: item.get("created_at") or "", reverse=True)

    def evidence(self, task_id: str) -> list[dict[str, Any]]:
        self.refresh_status(task_id)
        return self._all_evidence(_task_id(task_id))

    def _source_text(self, literature: dict[str, Any], location: str) -> str:
        if location == "abstract":
            return _clean(literature.get("abstract"), 12000)
        if location == "metadata":
            return _clean(literature.get("title"), 12000)
        if location == "user_note":
            return _clean(literature.get("user_note"), 12000)
        return ""

    def extract(self, *, task_id: str, literature_ids: list[str] | None = None) -> list[dict[str, Any]]:
        task_id = _task_id(task_id)
        literature_values = self.literature.list(task_id)
        selected = {str(item) for item in literature_ids or []}
        if selected:
            literature_values = [item for item in literature_values if item.get("id") in selected]
        extracted: list[dict[str, Any]] = []
        for literature in literature_values:
            for location in ("abstract", "user_note"):
                source_text = self._source_text(literature, location)
                if not source_text:
                    continue
                for match in _NUMBER_PATTERN.finditer(source_text):
                    value = _number(match.group("value"))
                    if value is None:
                        continue
                    unit = _clean(match.group("unit"), 20)
                    start, end = max(0, match.start() - 160), min(len(source_text), match.end() + 160)
                    quote = _clean(source_text[start:end], 800)
                    evidence = {
                        "id": f"re_{uuid.uuid4().hex[:16]}", "task_id": task_id,
                        "value": value, "unit": unit, "metric": _metric_hint(quote),
                        "subject": _clean(literature.get("title"), 180), "source_type": "literature",
                        "source_id": literature["id"], "source_title": _clean(literature.get("title"), 1000),
                        "source_location": location, "source_quote": quote, "year": literature.get("year"),
                        "device_model": "", "test_condition": "", "verification_status": PENDING,
                        "created_at": _now(), "updated_at": _now(),
                    }
                    self._write(self._evidence_path(evidence["id"]), evidence)
                    extracted.append(evidence)
        return self.verify(task_id=task_id, evidence_ids=[item["id"] for item in extracted])

    def add_manual_evidence(self, *, task_id: str, subject: str, metric: str, value: float, unit: str, source_title: str, source_location: str, source_quote: str, source_type: str = "user_provided", source_id: str = "", year: int | None = None, device_model: str = "", test_condition: str = "") -> dict[str, Any]:
        task_id = _task_id(task_id)
        if _number(value) is None or not _clean(unit, 20):
            raise ValueError("手工证据必须提供可解析数值和单位")
        item = {
            "id": f"re_{uuid.uuid4().hex[:16]}", "task_id": task_id,
            "value": float(value), "unit": _clean(unit, 20), "metric": _clean(metric, 120) or "已核验指标",
            "subject": _clean(subject, 180) or "未命名对象", "source_type": _clean(source_type, 80) or "user_provided",
            "source_id": _clean(source_id, 160), "source_title": _clean(source_title, 1000),
            "source_location": _clean(source_location, 500), "source_quote": _clean(source_quote, 1200),
            "year": int(year) if year else None, "device_model": _clean(device_model, 240),
            "test_condition": _clean(test_condition, 500), "verification_status": PENDING,
            "created_at": _now(), "updated_at": _now(),
        }
        if not item["source_title"] or not item["source_quote"]:
            raise ValueError("手工证据必须提供来源标题和原文位置或摘录")
        self._write(self._evidence_path(item["id"]), item)
        return self.verify(task_id=task_id, evidence_ids=[item["id"]])[0]

    def _verify_item(self, item: dict[str, Any]) -> dict[str, Any]:
        item = dict(item)
        value = _number(item.get("value"))
        unit = _clean(item.get("unit"), 20)
        item["verification_issues"] = []
        if value is None or not unit:
            item["verification_issues"].append("缺少可解析的数值或单位。")
        source_type = item.get("source_type")
        if source_type == "literature":
            try:
                literature = self.literature.get(str(item.get("source_id")), include_deleted=True)
            except ValueError:
                literature = None
            if not literature or literature.get("status") == "deleted":
                item["verification_issues"].append("来源文献不存在或已删除。")
                item["verification_status"] = BROKEN
                item["updated_at"] = _now()
                return item
            text = self._source_text(literature, str(item.get("source_location")))
            quote = _clean(item.get("source_quote"), 800)
            if not quote or quote.lower() not in text.lower():
                item["verification_issues"].append("原文摘录无法在声明的文献位置中核验。")
            needle = _clean(f"{item.get('value')} {unit}").replace(".0 ", " ").lower()
            compact_needle = re.sub(r"\s+", "", needle)
            compact_quote = re.sub(r"\s+", "", quote.lower().replace(",", ""))
            if needle and compact_needle not in compact_quote:
                item["verification_issues"].append("数值与单位未同时出现在保存的原文摘录中。")
            item["source_updated_at"] = literature.get("updated_at")
        elif source_type == "user_provided":
            # User-provided material may be used only when a literal source quote
            # is retained; it is still visibly distinct from a literature source.
            quote = _clean(item.get("source_quote"), 1200)
            if not _clean(item.get("source_title")) or not quote:
                item["verification_issues"].append("用户提供数据缺少可追溯来源标题或原文摘录。")
            needle = _clean(f"{item.get('value')} {unit}").replace(".0 ", " ").lower()
            compact_needle = re.sub(r"\s+", "", needle)
            compact_quote = re.sub(r"\s+", "", quote.lower().replace(",", ""))
            if needle and compact_needle not in compact_quote:
                item["verification_issues"].append("用户提供来源摘录未包含对应数值与单位。")
        else:
            item["verification_issues"].append("未知来源类型，不能自动用于论文。")
        family, factor, canonical_unit = _unit_info(unit)
        item["unit_family"], item["canonical_unit"] = family, canonical_unit
        item["canonical_value"] = value * factor if value is not None else None
        if item.get("verification_status") != BROKEN:
            item["verification_status"] = VERIFIED if not item["verification_issues"] else PENDING
        item["updated_at"] = _now()
        return item

    def verify(self, *, task_id: str, evidence_ids: list[str] | None = None) -> list[dict[str, Any]]:
        task_id = _task_id(task_id)
        wanted = {str(item) for item in evidence_ids or []}
        output: list[dict[str, Any]] = []
        for item in self._all_evidence(task_id):
            if wanted and item.get("id") not in wanted:
                continue
            verified = self._verify_item(item)
            self._write(self._evidence_path(verified["id"]), verified)
            output.append(verified)
        self._mark_conflicts(task_id)
        return [self._read(self._evidence_path(item["id"])) for item in output]

    def _mark_conflicts(self, task_id: str) -> None:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in self._all_evidence(task_id):
            if item.get("verification_status") != VERIFIED:
                continue
            groups[(_clean(item.get("subject"), 180).lower(), _clean(item.get("metric"), 120).lower(), _clean(item.get("unit_family"), 80))].append(item)
        for values in groups.values():
            canonical = {round(float(item.get("canonical_value") or 0), 10) for item in values}
            if len(canonical) <= 1:
                continue
            for item in values:
                item["verification_status"] = CONFLICT
                item["verification_issues"] = ["不同来源对同一对象和指标给出了不一致数值；请由用户选择来源。"]
                item["updated_at"] = _now()
                self._write(self._evidence_path(item["id"]), item)

    def _all_candidates(self, task_id: str) -> list[dict[str, Any]]:
        directory = self.root / "candidates"
        values: list[dict[str, Any]] = []
        for path in directory.glob("rv_*.json") if directory.exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("task_id") == task_id:
                    values.append(item)
            except json.JSONDecodeError:
                continue
        return sorted(values, key=lambda item: item.get("created_at") or "", reverse=True)

    def candidates(self, task_id: str) -> list[dict[str, Any]]:
        self.refresh_status(task_id)
        return self._all_candidates(_task_id(task_id))

    def _candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._read(self._candidate_path(candidate_id))

    def _csv_dataset(self, *, task_id: str, title: str, headers: list[str], rows: list[list[object]], description: str) -> dict[str, Any]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        return self.datasets.import_data(filename="verified_research_evidence.csv", raw=buffer.getvalue().encode("utf-8-sig"), name=title, description=description, task_id=task_id)

    def _source_snapshot(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{
            "evidence_id": item["id"], "source_type": item.get("source_type"), "source_id": item.get("source_id"),
            "source_title": item.get("source_title"), "source_updated_at": item.get("source_updated_at"),
            "verification_status": item.get("verification_status"),
        } for item in values]

    def _build_chart_candidate(self, task_id: str, values: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
        if len(values) < 2:
            return None
        service = self._draft_service(task_id)
        dataset = self._csv_dataset(task_id=task_id, title=f"{metric}对比数据", headers=["对象", metric], rows=[[item["subject"], item["canonical_value"]] for item in values], description="由已核验研究证据生成；原始来源保存在研究可视化候选中。")
        version = self.datasets.get_version(dataset["dataset_id"], int(dataset["version"]), include_rows=True)
        draft = service.load()
        chart_id = f"chart_rv_{uuid.uuid4().hex[:12]}"
        block = create_lab_chart_from_dataset(draft, service.task_dir, chart_id, external_dataset_version(version), title_hint=f"不同对象的{metric}对比", kind="bar")
        block["research_visualization"] = {"kind": "evidence_chart", "evidence_ids": [item["id"] for item in values], "source_snapshot": self._source_snapshot(values), "dataset_id": dataset["dataset_id"], "dataset_version": dataset["version"]}
        service.save(draft)
        return {"chart_id": chart_id, "dataset_id": dataset["dataset_id"], "dataset_version": dataset["version"], "asset": block.get("asset"), "block_snapshot": copy.deepcopy(block)}

    def recommend(self, *, task_id: str, section: str = "", evidence_ids: list[str] | None = None, dataset_id: str = "", dataset_version: int | None = None, include_evidence_recommendations: bool = True, include_literature_fallback: bool = True) -> list[dict[str, Any]]:
        task_id = _task_id(task_id)
        selected = {str(item) for item in evidence_ids or []}
        evidence = [item for item in self.evidence(task_id) if item.get("verification_status") == VERIFIED and (not selected or item.get("id") in selected)] if include_evidence_recommendations else []
        candidates: list[dict[str, Any]] = []
        by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            by_metric[_clean(item.get("metric"), 120)].append(item)
        for metric, values in by_metric.items():
            if len(values) < 2:
                continue
            table = {
                "type": "table", "title": f"{metric}技术对比", "headers": ["对象", metric, "单位", "来源"],
                "rows": [[item["subject"], item["value"], item["unit"], item["source_title"]] for item in values],
            }
            candidate = {
                "id": f"rv_{uuid.uuid4().hex[:16]}", "task_id": task_id, "section_hint": _clean(section, 240),
                "kind": "table", "table_type": "technology_comparison", "title": table["title"],
                "reason": "多个已核验对象具有同类可比较数值，适合生成技术对比表。",
                "status": "ready", "requires_confirmation": True, "table_spec": table,
                "evidence_ids": [item["id"] for item in values], "source_snapshot": self._source_snapshot(values),
                "created_at": _now(), "updated_at": _now(),
            }
            self._write(self._candidate_path(candidate["id"]), candidate)
            candidates.append(candidate)
            chart = self._build_chart_candidate(task_id, values, metric)
            if chart:
                visual = {**candidate, "id": f"rv_{uuid.uuid4().hex[:16]}", "kind": "chart", "title": f"不同对象的{metric}对比", "reason": "已核验证据形成统一单位的对比序列，适合用柱状图展示。", "chart": chart, "created_at": _now(), "updated_at": _now()}
                self._write(self._candidate_path(visual["id"]), visual)
                candidates.append(visual)
        if not candidates and len(evidence) >= 2:
            table = {
                "type": "table", "title": "技术参数对比表", "headers": ["对象", "指标", "数值", "单位", "来源"],
                "rows": [[item["subject"], item["metric"], item["value"], item["unit"], item["source_title"]] for item in evidence],
            }
            candidate = {"id": f"rv_{uuid.uuid4().hex[:16]}", "task_id": task_id, "section_hint": _clean(section, 240), "kind": "table", "table_type": "technology_comparison", "title": table["title"], "reason": "不同技术具有已核验但量纲不同的参数，适合用保留单位与来源的技术对比表呈现，不能合并为数值图表。", "status": "ready", "requires_confirmation": True, "table_spec": table, "evidence_ids": [item["id"] for item in evidence], "source_snapshot": self._source_snapshot(evidence), "created_at": _now(), "updated_at": _now()}
            self._write(self._candidate_path(candidate["id"]), candidate)
            candidates.append(candidate)
        if not candidates and include_literature_fallback and len(evidence) < 2:
            literature = self.literature.list(task_id)
            if len(literature) >= 2:
                records = literature[:10]
                table = {"type": "table", "title": "文献综述表", "headers": ["文献", "年份", "来源", "摘要信息"], "rows": [[item.get("title"), item.get("year") or "", item.get("journal") or item.get("source"), _clean(item.get("abstract"), 220)] for item in records]}
                candidate = {"id": f"rv_{uuid.uuid4().hex[:16]}", "task_id": task_id, "section_hint": _clean(section, 240), "kind": "table", "table_type": "literature_review", "title": "文献综述表", "reason": "已有多篇已保存文献，适合以可追溯的文献综述表呈现。", "status": "ready", "requires_confirmation": True, "table_spec": table, "evidence_ids": [], "source_snapshot": [{"source_type": "literature", "source_id": item["id"], "source_title": item.get("title"), "source_updated_at": item.get("updated_at"), "verification_status": VERIFIED} for item in records], "created_at": _now(), "updated_at": _now()}
                self._write(self._candidate_path(candidate["id"]), candidate)
                candidates.append(candidate)
        if dataset_id:
            version = self.datasets.get_version(dataset_id, dataset_version, include_rows=True)
            numeric = [item["name"] for item in version.get("schema") or [] if item.get("type") == "numeric"]
            if len(numeric) >= 2:
                service = self._draft_service(task_id)
                draft = service.load()
                chart_id = f"chart_rv_{uuid.uuid4().hex[:12]}"
                block = create_lab_chart_from_dataset(draft, service.task_dir, chart_id, external_dataset_version(version), title_hint=f"{numeric[0]}与{numeric[1]}散点图", kind="scatter")
                snapshot = [{"source_type": "dataset", "source_id": dataset_id, "dataset_version": version["version"], "fingerprint": version.get("fingerprint"), "verification_status": VERIFIED}]
                block["research_visualization"] = {"kind": "dataset_chart", "source_snapshot": snapshot, "dataset_id": dataset_id, "dataset_version": version["version"]}
                service.save(draft)
                chart = {"chart_id": chart_id, "dataset_id": dataset_id, "dataset_version": version["version"], "asset": block.get("asset"), "block_snapshot": copy.deepcopy(block)}
                candidate = {"id": f"rv_{uuid.uuid4().hex[:16]}", "task_id": task_id, "section_hint": _clean(section, 240), "kind": "chart", "chart_kind": "scatter", "title": f"{numeric[0]}与{numeric[1]}散点图", "reason": "数据集中存在两个连续数值变量，已按现有 ChartSpec v2 与 ChartRenderer 生成散点图候选；可在确认前到 Visualization Lab 继续调整绑定。", "status": "ready", "requires_confirmation": True, "chart": chart, "dataset_id": dataset_id, "dataset_version": version["version"], "source_snapshot": snapshot, "created_at": _now(), "updated_at": _now()}
                self._write(self._candidate_path(candidate["id"]), candidate)
                candidates.append(candidate)
        if not candidates:
            return [{"status": "pending", "reason": "尚无至少两项可比较的已核验证据。请保存来源、补充原文位置，或选择已有 Dataset 后再生成候选。"}]
        self.graph.rebuild_task(task_id)
        return candidates

    def recommend_literature_review(self, *, task_id: str, section: str = "") -> list[dict[str, Any]]:
        """Create only the source-backed literature review table candidate."""
        task_id = _task_id(task_id)
        records = self.literature.list(task_id)[:10]
        if len(records) < 2:
            return []
        table = {
            "type": "table", "title": "文献综述表", "headers": ["文献", "年份", "来源", "摘要信息"],
            "rows": [[item.get("title"), item.get("year") or "", item.get("journal") or item.get("source"), _clean(item.get("abstract"), 220)] for item in records],
        }
        candidate = {
            "id": f"rv_{uuid.uuid4().hex[:16]}", "task_id": task_id, "section_hint": _clean(section, 240),
            "kind": "table", "table_type": "literature_review", "title": "文献综述表",
            "reason": "已保存文献仅在文献综述/研究现状章节中汇总为可追溯表格。",
            "status": "ready", "requires_confirmation": True, "table_spec": table, "evidence_ids": [],
            "source_snapshot": [{"source_type": "literature", "source_id": item["id"], "source_title": item.get("title"), "source_updated_at": item.get("updated_at"), "verification_status": VERIFIED} for item in records],
            "created_at": _now(), "updated_at": _now(),
        }
        self._write(self._candidate_path(candidate["id"]), candidate)
        self.graph.rebuild_task(task_id)
        return [candidate]

    def recommend_literature_trend(self, *, task_id: str, section: str = "") -> list[dict[str, Any]]:
        """Build a source-backed literature-year chart candidate.

        Counts are deterministically derived from saved literature metadata rather
        than being model-generated numeric claims.  Every plotted value retains a
        snapshot of the individual source records that contributed to it.
        """
        task_id = _task_id(task_id)
        records = []
        for item in self.literature.list(task_id):
            try:
                year = int(item.get("year"))
            except (TypeError, ValueError):
                continue
            if 1800 <= year <= 2200:
                records.append((year, item))
        buckets: dict[int, int] = defaultdict(int)
        for year, _ in records:
            buckets[year] += 1
        if len(buckets) < 2:
            return []
        ordered = sorted(buckets.items())
        sources = [item for _, item in records]
        dataset = self._csv_dataset(
            task_id=task_id,
            title="已保存文献年度分布数据",
            headers=["年份", "文献数量"],
            rows=[[year, count] for year, count in ordered],
            description="由已保存文献元数据的年份字段确定性聚合，保留来源快照。",
        )
        version = self.datasets.get_version(dataset["dataset_id"], int(dataset["version"]), include_rows=True)
        service = self._draft_service(task_id)
        draft = service.load()
        chart_id = f"chart_rv_{uuid.uuid4().hex[:12]}"
        block = create_lab_chart_from_dataset(
            draft,
            service.task_dir,
            chart_id,
            external_dataset_version(version),
            title_hint="已保存文献年度分布",
            kind="bar",
        )
        snapshot = [{
            "source_type": "literature", "source_id": item["id"],
            "source_title": item.get("title"), "source_updated_at": item.get("updated_at"),
            "verification_status": VERIFIED,
        } for item in sources]
        block["research_visualization"] = {
            "kind": "literature_metadata_chart",
            "source_snapshot": snapshot,
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["version"],
            "derivation": "按已保存文献元数据年份字段计数",
        }
        service.save(draft)
        chart = {
            "chart_id": chart_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["version"],
            "asset": block.get("asset"),
            "block_snapshot": copy.deepcopy(block),
        }
        candidate = {
            "id": f"rv_{uuid.uuid4().hex[:16]}",
            "task_id": task_id,
            "section_hint": _clean(section, 240),
            "kind": "chart",
            "chart_kind": "bar",
            "title": "已保存文献年度分布",
            "reason": "图表数值由已保存文献的年份元数据确定性统计而来，适合展示研究资料的时间分布。",
            "status": "ready",
            "requires_confirmation": False,
            "auto_insert_eligible": True,
            "chart": chart,
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["version"],
            "source_snapshot": snapshot,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._write(self._candidate_path(candidate["id"]), candidate)
        self.graph.rebuild_task(task_id)
        return [candidate]

    def preview(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        self.refresh_status(candidate["task_id"])
        candidate = self._candidate(candidate_id)
        return {"requires_confirmation": True, "candidate": candidate}

    def _source_literature_ids(self, candidate: dict[str, Any]) -> list[str]:
        return list(dict.fromkeys(str(item.get("source_id")) for item in candidate.get("source_snapshot") or [] if item.get("source_type") == "literature" and item.get("source_id")))

    def insert(self, *, candidate_id: str, section_id: str, insert_index: int | None = None) -> dict[str, Any]:
        candidate = self._candidate(candidate_id)
        self.refresh_status(candidate["task_id"])
        candidate = self._candidate(candidate_id)
        if candidate.get("status") != "ready":
            raise ValueError("候选来源已变化、缺失或待核验，不能加入论文")
        task_id = candidate["task_id"]
        service = self._draft_service(task_id)
        if candidate.get("kind") == "chart":
            with service.lock:
                draft = service.load()
                chart_id = str((candidate.get("chart") or {}).get("chart_id"))
                try:
                    block = insert_chart_into_section(draft, chart_id, section_id)
                except ValueError:
                    # A paper draft can be saved by another existing workflow after
                    # candidate generation. Restore only this persisted ChartSpec/
                    # ChartAsset snapshot into the canonical Lab library, then use
                    # the normal insert operation rather than creating a renderer.
                    snapshot = (candidate.get("chart") or {}).get("block_snapshot")
                    if not isinstance(snapshot, dict) or snapshot.get("id") != chart_id:
                        raise
                    draft.setdefault("chart_library", []).append(copy.deepcopy(snapshot))
                    block = insert_chart_into_section(draft, chart_id, section_id)
                block["research_visualization"] = {"candidate_id": candidate_id, "evidence_ids": candidate.get("evidence_ids") or [], "source_snapshot": candidate.get("source_snapshot") or [], "dataset_id": (candidate.get("chart") or {}).get("dataset_id"), "dataset_version": (candidate.get("chart") or {}).get("dataset_version"), "derivation": ((candidate.get("chart") or {}).get("block_snapshot") or {}).get("research_visualization", {}).get("derivation")}
                if insert_index is not None:
                    section = next((item for item in walk_sections(draft.get("sections") or []) if item.get("id") == section_id), None)
                    if section:
                        blocks = section.setdefault("paragraphs", [])
                        current_index = next((index for index, item in enumerate(blocks) if item.get("id") == block.get("id")), None)
                        if current_index is not None:
                            blocks.pop(current_index)
                            blocks.insert(max(0, min(int(insert_index), len(blocks))), block)
                self.objects.renumber_document_references(task_id, draft)
                service.save(draft)
            inserted = {"block": block}
        elif candidate.get("kind") == "table":
            with service.lock:
                draft = service.load()
                section = next((item for item in walk_sections(draft.get("sections") or []) if item.get("id") == section_id), None)
                if not section:
                    raise ValueError("未找到论文目标章节")
                spec = candidate.get("table_spec") or {}
                block = {"id": f"table_rv_{uuid.uuid4().hex[:12]}", "type": "table", "title": _clean(spec.get("title"), 200) or candidate["title"], "headers": list(spec.get("headers") or []), "rows": list(spec.get("rows") or []), "status": "ready", "generated_at": _now(), "provenance": "verified_research_evidence", "research_visualization": {"candidate_id": candidate_id, "evidence_ids": candidate.get("evidence_ids") or [], "source_snapshot": candidate.get("source_snapshot") or []}}
                upsert_table_dataset(draft, block)
                blocks = section.setdefault("paragraphs", [])
                if insert_index is None:
                    blocks.append(block)
                else:
                    blocks.insert(max(0, min(int(insert_index), len(blocks))), block)
                self.objects.renumber_document_references(task_id, draft)
                service.save(draft)
            inserted = {"block": block}
        else:
            raise ValueError("当前候选需要在 Visualization Lab 中完成数据绑定后再加入论文")
        citations = []
        for literature_id in self._source_literature_ids(candidate):
            citations.append(self.literature.insert_citation(task_id=task_id, section_id=section_id, literature_id=literature_id))
        candidate.update(status="inserted", inserted_block_ids=[block.get("id")], inserted_at=_now(), updated_at=_now())
        self._write(self._candidate_path(candidate_id), candidate)
        self.objects.sync(task_id)
        self.graph.rebuild_task(task_id)
        return {"candidate": candidate, "inserted": inserted, "citations": citations}

    def refresh_status(self, task_id: str) -> None:
        task_id = _task_id(task_id)
        for item in self._all_evidence(task_id):
            current = self._verify_item(item)
            self._write(self._evidence_path(current["id"]), current)
        self._mark_conflicts(task_id)
        for candidate in self._all_candidates(task_id):
            status = "ready" if candidate.get("status") not in {"inserted"} else "inserted"
            for source in candidate.get("source_snapshot") or []:
                if source.get("source_type") == "literature":
                    try:
                        literature = self.literature.get(str(source.get("source_id")), include_deleted=True)
                    except ValueError:
                        literature = None
                    if not literature or literature.get("status") == "deleted":
                        status = BROKEN
                        break
                    if source.get("source_updated_at") and literature.get("updated_at") != source.get("source_updated_at"):
                        status = STALE
                elif source.get("source_type") == "dataset":
                    try:
                        latest = self.datasets.get_dataset(str(source.get("source_id"))).get("latest_version")
                        if int(source.get("dataset_version") or 0) < int(latest or 0):
                            status = STALE
                    except ValueError:
                        status = BROKEN
            for evidence_id in candidate.get("evidence_ids") or []:
                try:
                    evidence = self._read(self._evidence_path(str(evidence_id)))
                    if evidence.get("verification_status") == BROKEN:
                        status = BROKEN
                    elif evidence.get("verification_status") in {PENDING, CONFLICT} and status not in {BROKEN}:
                        status = STALE
                except ValueError:
                    status = BROKEN
            candidate["status"] = status
            candidate["updated_at"] = _now()
            self._write(self._candidate_path(candidate["id"]), candidate)
        self._propagate_inserted_status(task_id)

    def _propagate_inserted_status(self, task_id: str) -> None:
        service = DraftService(task_id, self.settings.output_dir / task_id)
        draft = service.load()
        if not draft:
            return
        changed = False
        for section in walk_sections(draft.get("sections") or []):
            for block in section.get("paragraphs") or []:
                provenance = block.get("research_visualization") or {}
                candidate_id = provenance.get("candidate_id")
                if not candidate_id:
                    continue
                try:
                    candidate = self._candidate(str(candidate_id))
                except ValueError:
                    block["status"] = BROKEN
                    changed = True
                    continue
                expected = candidate.get("status")
                mapped = BROKEN if expected == BROKEN else STALE if expected == STALE else "ready"
                if block.get("status") != mapped:
                    block["status"] = mapped
                    block["stale_reason"] = "研究证据来源已删除。" if mapped == BROKEN else "研究证据或数据集已有更新，请复核后重新生成。" if mapped == STALE else None
                    changed = True
        if changed:
            service.save(draft)
