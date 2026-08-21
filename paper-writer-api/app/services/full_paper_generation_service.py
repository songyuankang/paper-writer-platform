"""正文优先的全文生成编排服务。

该服务不创建第二套论文或图表模型。它把可恢复的运行状态保存在
``draft.json.full_paper_pipeline``，并在用户直接触发“一键全文”时，将
研究检索、证据核验、表图候选和插入动作编排到既有正文生成流程中。
所有自动入文均复用 ResearchVisualizationService.insert，因此仍然生成
真实的 TableBlock/FigureBlock、ResearchObject、CrossReference 和 DependencyGraph。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.draft.service import DraftService, _leaf_ids
from app.services.cross_reference_service import CrossReferenceService
from app.services.research_object_service import ResearchObjectService
from app.services.research_visualization_service import ResearchVisualizationService
from app.services.visualization_plan_service import VisualizationPlanService


PIPELINE_KEY = "full_paper_pipeline"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(term.lower() in lowered for term in terms)


class FullPaperGenerationService:
    """Orchestrate full-paper generation with durable, safe checkpoints."""

    def __init__(self, draft_service: DraftService):
        self.draft_service = draft_service
        self.task_id = draft_service.task_id
        self.settings = draft_service._storage_settings()
        self.research = ResearchVisualizationService(self.settings)
        self.objects = ResearchObjectService(self.settings)
        self.references = CrossReferenceService(self.settings)
        self.visualization_plan = VisualizationPlanService(self.settings)

    def _state(self, draft: dict) -> dict[str, Any]:
        state = draft.get(PIPELINE_KEY)
        return state if isinstance(state, dict) else {}

    def status(self) -> dict[str, Any]:
        draft = self.draft_service.load()
        state = dict(self._state(draft))
        return {
            "generating": bool(draft.get("generating")),
            "progress": int(draft.get("progress") or 0),
            "done": int(draft.get("done") or 0),
            "total": int(draft.get("total") or 0),
            "pipeline": state,
        }

    def _save_state(self, *, status: str, stage: str, message: str, **patch: Any) -> dict:
        with self.draft_service.lock:
            draft = self.draft_service.load()
            current = dict(self._state(draft))
            current.update({
                "version": 1,
                "status": status,
                "stage": stage,
                "message": message,
                "updated_at": _now(),
                **patch,
            })
            draft[PIPELINE_KEY] = current
            draft["generating"] = status == "running"
            self.draft_service.save(draft)
            return current

    def start(self, model_id: str | None = None, *, resume: bool = False) -> dict:
        with self.draft_service.lock:
            draft = self.draft_service.load()
            if not draft:
                raise ValueError("草稿不存在")
            self.draft_service.ensure_outline_confirmed()
            old = dict(self._state(draft))
            if draft.get("generating"):
                raise ValueError("正在生成中，请先暂停或等待当前阶段完成")
            if resume:
                if old.get("status") != "paused":
                    raise ValueError("当前没有可继续的暂停生成任务")
                old.update(status="running", stage="resuming", message="正在恢复全文生成", model_id=model_id or old.get("model_id"), resumed_at=_now(), updated_at=_now())
            else:
                leaves = sorted(_leaf_ids(draft.get("sections") or []))
                visualization_plan = self.visualization_plan.build(self.task_id, draft, replace=True)
                old = {
                    "version": 1,
                    "status": "running",
                    "stage": "planning",
                    "message": "正在分析论文结构",
                    "model_id": model_id,
                    "started_at": _now(),
                    "updated_at": _now(),
                    "completed_section_ids": [],
                    "research_section_ids": [],
                    "inserted_block_ids": [],
                    "errors": [],
                    "total_sections": len(leaves),
                    "visualization_plan": self.visualization_plan.summary(self.task_id),
                    "global_research_prepared": False,
                }
                draft["done"] = 0
                draft["total"] = len(leaves)
                draft["progress"] = 0
                draft["word_status"] = "generating"
            draft[PIPELINE_KEY] = old
            draft["generating"] = True
            self.draft_service.save(draft)
            return dict(old)

    def pause(self) -> dict:
        draft = self.draft_service.load()
        state = self._state(draft)
        if state.get("status") != "running":
            raise ValueError("当前没有可暂停的全文生成任务")
        return self._save_state(status="pause_requested", stage=state.get("stage") or "generating", message="将在当前安全检查点暂停生成")

    def _pause_requested(self) -> bool:
        state = self._state(self.draft_service.load())
        return state.get("status") in {"pause_requested", "paused"}

    def _checkpoint(self, stage: str, message: str, *, section_id: str = "", progress: int | None = None) -> bool:
        """Persist a safe boundary and return ``False`` when paused."""
        with self.draft_service.lock:
            draft = self.draft_service.load()
            state = dict(self._state(draft))
            if state.get("status") in {"pause_requested", "paused"}:
                state.update(status="paused", stage=stage, message="已暂停，可继续生成", paused_at=_now(), current_section_id=section_id or state.get("current_section_id", ""), updated_at=_now())
                draft[PIPELINE_KEY] = state
                draft["generating"] = False
                self.draft_service.save(draft)
                return False
            state.update(status="running", stage=stage, message=message, current_section_id=section_id or state.get("current_section_id", ""), updated_at=_now())
            if progress is not None:
                draft["progress"] = max(0, min(99, int(progress)))
                state["progress"] = draft["progress"]
            draft[PIPELINE_KEY] = state
            draft["generating"] = True
            self.draft_service.save(draft)
        return True

    def _mark_new_paragraphs(self, section_id: str, before_ids: set[str]) -> None:
        with self.draft_service.lock:
            draft = self.draft_service.load()
            section = next((item for item in draft.get("sections") or [] if item.get("id") == section_id), None)
            if section:
                for block in section.get("paragraphs") or []:
                    if block.get("id") not in before_ids and block.get("type", "paragraph") == "paragraph":
                        block["generation_origin"] = "full_paper_pipeline"
                self.draft_service.save(draft)

    def _section_needs_research(self, section: dict, index: int) -> bool:
        text = f"{section.get('title', '')} {section.get('gist', '')}"
        research_terms = ("文献", "综述", "现状", "背景", "理论", "相关研究", "国内外", "比较", "分析", "结果", "实证")
        return index == 0 or _contains_any(text, research_terms)

    def _insert_reference_for_block(self, section_id: str, block_id: str) -> None:
        self.objects.sync(self.task_id)
        target = next((item for item in self.references.reference_candidates(self.task_id) if item.get("source_id") == block_id), None)
        if target:
            inserted = self.references.insert(task_id=self.task_id, section_id=section_id, target_object_id=target["id"])
            reference_block_id = str((inserted.get("block") or {}).get("id") or "")
            if reference_block_id:
                with self.draft_service.lock:
                    draft = self.draft_service.load()
                    section = next((item for item in draft.get("sections") or [] if item.get("id") == section_id), None)
                    if section:
                        reference_block = next((item for item in section.get("paragraphs") or [] if item.get("id") == reference_block_id), None)
                        if reference_block:
                            reference_block["auto_full_paper"] = True
                            reference_block["generated_by"] = "full_paper_pipeline"
                            self.draft_service.save(draft)

    def _record_insert(self, section_id: str, result: dict) -> str | None:
        block = ((result.get("inserted") or {}).get("block") or {})
        block_id = str(block.get("id") or "")
        if not block_id:
            return None
        with self.draft_service.lock:
            draft = self.draft_service.load()
            section = next((item for item in draft.get("sections") or [] if item.get("id") == section_id), None)
            if section:
                target = next((item for item in section.get("paragraphs") or [] if item.get("id") == block_id), None)
                if target:
                    target["auto_full_paper"] = True
                    target["generated_by"] = "full_paper_pipeline"
                state = dict(self._state(draft))
                state["inserted_block_ids"] = list(dict.fromkeys([*(state.get("inserted_block_ids") or []), block_id]))
                draft[PIPELINE_KEY] = state
                self.draft_service.save(draft)
        self._insert_reference_for_block(section_id, block_id)
        return block_id

    def _prepare_global_research(self, model_id: str | None) -> None:
        """Search and verify task-level sources once before any section executes."""
        state = self._state(self.draft_service.load())
        if state.get("global_research_prepared"):
            return
        draft = self.draft_service.load()
        sections = draft.get("sections") or []
        research_question = "；".join(
            str(section.get("gist") or section.get("title") or "")
            for section in sections
            if section.get("id")
        )[:1200]
        if not self._checkpoint("research_planning", "正在为全文规划唯一的研究资料与证据", progress=7):
            return
        plan = self.research.create_plan(
            task_id=self.task_id,
            topic=draft.get("title") or "研究主题",
            chapter="全文级研究资料规划",
            research_question=research_question,
            model_id=model_id,
        )
        if not self._checkpoint("research_search", "正在一次性检索全文所需公开学术资料", progress=8):
            return
        search = self.research.search(task_id=self.task_id, limit=5)
        sources = list(search.get("results") or [])[:12]
        if sources:
            self.research.save_sources(task_id=self.task_id, sources=sources)
        if not self._checkpoint("evidence_verification", "正在一次性提取并核验全文证据", progress=9):
            return
        self.research.extract(task_id=self.task_id)
        self._save_state(
            status="running",
            stage="visualization_planning",
            message="全文资料与证据已准备完成，正在按章节唯一计划生成表图",
            global_research_prepared=True,
            global_research_plan_id=plan.get("id"),
            visualization_plan=self.visualization_plan.summary(self.task_id),
        )

    @staticmethod
    def _candidate_for_item(item: dict[str, Any], candidates: list[dict[str, Any]], claimed: set[str]) -> dict[str, Any] | None:
        purpose = item.get("purpose")
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id or candidate_id in claimed or candidate.get("status") != "ready":
                continue
            if candidate.get("kind") != item.get("asset_kind"):
                continue
            if purpose == "literature_review_table" and candidate.get("table_type") != "literature_review":
                continue
            if purpose == "literature_year_distribution" and candidate.get("title") != "已保存文献年度分布":
                continue
            if purpose == "technology_comparison" and candidate.get("table_type") != "technology_comparison":
                continue
            if purpose == "experimental_result":
                chart = candidate.get("chart") or {}
                dataset_ids = {str(value) for value in item.get("dataset_ids") or []}
                if not dataset_ids.intersection({str(candidate.get("dataset_id") or ""), str(chart.get("dataset_id") or "")}):
                    continue
            claimed.add(candidate_id)
            return candidate
        return None

    def _candidates_for_plan_items(self, items: list[dict[str, Any]], section_label: str) -> list[dict[str, Any]]:
        """Materialise candidates only for the unique plan items owned by one section."""
        candidates: list[dict[str, Any]] = []
        purposes = {str(item.get("purpose")) for item in items}
        if "literature_review_table" in purposes:
            candidates.extend(self.research.recommend_literature_review(task_id=self.task_id, section=section_label))
        if "literature_year_distribution" in purposes:
            candidates.extend(self.research.recommend_literature_trend(task_id=self.task_id, section=section_label))
        if "technology_comparison" in purposes:
            candidates.extend(self.research.recommend(task_id=self.task_id, section=section_label))
        for item in items:
            if item.get("purpose") != "experimental_result" or not item.get("dataset_ids"):
                continue
            candidates.extend(self.research.recommend(
                task_id=self.task_id,
                section=section_label,
                dataset_id=str(item["dataset_ids"][0]),
                dataset_version=(item.get("dataset_versions") or [None])[0],
                include_evidence_recommendations=False,
                include_literature_fallback=False,
            ))
        return candidates

    def _annotate_plan_block(self, section_id: str, block_id: str, item: dict[str, Any]) -> None:
        """Make plan provenance available to the existing dependency/duplicate chain."""
        with self.draft_service.lock:
            draft = self.draft_service.load()
            section = next((value for value in draft.get("sections") or [] if value.get("id") == section_id), None)
            block = next((value for value in (section or {}).get("paragraphs") or [] if value.get("id") == block_id), None)
            if block is None:
                return
            provenance = dict(block.get("research_visualization") or {})
            provenance.update({
                "visualization_plan_id": (self.visualization_plan.get(self.task_id) or {}).get("id"),
                "visualization_plan_item_id": item.get("id"),
                "source_signature": item.get("source_signature"),
                "target_section_id": item.get("target_section_id"),
                "purpose": item.get("purpose"),
                "insertion_anchor": item.get("insertion_anchor"),
            })
            block["research_visualization"] = provenance
            self.draft_service.save(draft)

    def _execute_visualization_plan_for_section(self, section: dict, model_id: str | None) -> None:
        """Generate and insert only this section's planned, unique formal blocks."""
        section_id = str(section["id"])
        section_label = f"{section.get('number', '')} {section.get('title', '')}".strip()
        items = self.visualization_plan.items_for_section(self.task_id, section_id)
        if not items:
            return
        if not self._checkpoint("visualization_planning", f"正在执行 {section_label} 的唯一表图计划", section_id=section_id):
            return
        candidates = self._candidates_for_plan_items(items, section_label)
        latest = self.draft_service.load()
        latest_section = next((value for value in latest.get("sections") or [] if value.get("id") == section_id), section)
        insert_index = len(latest_section.get("paragraphs") or [])
        inserted: list[dict[str, str]] = []
        failures: list[dict[str, str]] = []
        claimed: set[str] = set()
        for item in items:
            if not self._checkpoint("inserting_research", f"正在按计划插入 {section_label} 的研究表图", section_id=section_id):
                return
            candidate = self._candidate_for_item(item, candidates, claimed)
            if not candidate:
                self.visualization_plan.mark_skipped(self.task_id, str(item["id"]), "当前章节没有满足该计划项、且具有可核验来源的候选；正文将继续生成。")
                continue
            accepted, _ = self.visualization_plan.accept_candidate(self.task_id, str(item["id"]), candidate, self.draft_service.load())
            if not accepted:
                continue
            try:
                result = self.research.insert(
                    candidate_id=str(candidate["id"]),
                    section_id=section_id,
                    insert_index=insert_index,
                )
                block_id = self._record_insert(section_id, result)
                block = ((result.get("inserted") or {}).get("block") or {})
                if not block_id:
                    self.visualization_plan.mark_broken(self.task_id, str(item["id"]), "候选已生成，但未返回可插入的正式正文块。")
                    continue
                fresh_plan = self.visualization_plan.get(self.task_id) or {}
                fresh_item = next((value for value in fresh_plan.get("items") or [] if value.get("id") == item.get("id")), item)
                self._annotate_plan_block(section_id, block_id, fresh_item)
                self.visualization_plan.mark_inserted(self.task_id, str(item["id"]), block_id)
                insert_index += 1
                label = f"表{block.get('table_number')}" if block.get("type") == "table" else f"图{block.get('figure_number')}"
                inserted.append({"kind": str(block.get("type") or candidate.get("kind") or ""), "block_id": block_id, "label": label, "title": str(block.get("title") or candidate.get("title") or "")})
            except Exception as exc:  # One visualization must never abort body generation.
                failures.append({"plan_item_id": str(item.get("id") or ""), "candidate_id": str(candidate.get("id") or ""), "reason": str(exc)})
                self.visualization_plan.mark_broken(self.task_id, str(item["id"]), f"表图生成或插入失败：{exc}")
        with self.draft_service.lock:
            draft = self.draft_service.load()
            state = dict(self._state(draft))
            state["research_section_ids"] = list(dict.fromkeys([*(state.get("research_section_ids") or []), section_id]))
            state["visualization_insertions"] = inserted
            state["visualization_plan"] = self.visualization_plan.summary(self.task_id)
            if failures:
                state["visualization_failures"] = failures
            draft[PIPELINE_KEY] = state
            self.draft_service.save(draft)

    def _generate_one_section(self, section: dict, index: int, total: int, model_id: str | None, *, allow_research: bool = True) -> bool:
        section_id = str(section["id"])
        if not self._checkpoint("generating_section", f"正在生成 {section.get('number', '')} {section.get('title', '')}", section_id=section_id, progress=10 + int(index / max(1, total) * 60)):
            return False
        before = {str(item.get("id")) for item in section.get("paragraphs") or []}
        self.draft_service.generate_section(section_id, model_id)
        self._mark_new_paragraphs(section_id, before)
        if allow_research:
            self._execute_visualization_plan_for_section(section, model_id)
            if self._pause_requested():
                return False
        with self.draft_service.lock:
            draft = self.draft_service.load()
            state = dict(self._state(draft))
            completed = set(state.get("completed_section_ids") or [])
            completed.add(section_id)
            state["completed_section_ids"] = sorted(completed)
            draft["done"] = len(completed)
            draft["total"] = total
            draft["progress"] = min(85, 10 + int(len(completed) / max(1, total) * 70))
            draft[PIPELINE_KEY] = state
            self.draft_service._refresh_word_stats(draft)
            self.draft_service.save(draft)
        return True

    def _supplement(self, model_id: str | None) -> bool:
        for round_index in range(2):
            if not self._checkpoint("supplementing", f"正在补足正文篇幅（第 {round_index + 1} 轮）", progress=86 + round_index * 4):
                return False
            with self.draft_service.lock:
                draft = self.draft_service.load()
                stats = self.draft_service._refresh_word_stats(draft)
                if stats["actual"] >= stats["minimum"]:
                    self.draft_service.save(draft)
                    return True
                draft["word_status"] = "supplementing"
                draft["supplement_rounds"] = round_index + 1
                candidates = self.draft_service._deficient_leaf_sections(draft)
                self.draft_service.save(draft)
            for section in candidates:
                if not self._checkpoint("supplementing", f"正在补写 {section.get('number', '')} {section.get('title', '')}"):
                    return False
                with self.draft_service.lock:
                    latest = self.draft_service.load()
                    stats = self.draft_service._refresh_word_stats(latest)
                    if stats["actual"] >= stats["minimum"]:
                        self.draft_service.save(latest)
                        return True
                    fresh = self.draft_service._find_section(latest, section["id"])
                    deficit = max(int(fresh.get("target_chars") or 0) - self.draft_service._section_char_count(fresh), 0)
                if deficit:
                    self.draft_service._supplement_section(section["id"], min(max(deficit, 160), 1200), model_id)
        return True

    def run(self, model_id: str | None = None) -> dict:
        draft = self.draft_service.load()
        state = self._state(draft)
        if state.get("status") not in {"running", "resuming"}:
            raise ValueError("全文生成任务未处于可运行状态")
        selected_model = model_id or state.get("model_id")
        leaves = sorted([item for item in draft.get("sections") or [] if item.get("id") in _leaf_ids(draft.get("sections") or [])], key=lambda item: str(item.get("id")))
        completed = set(state.get("completed_section_ids") or [])
        if not self._checkpoint("planning", "正在分析论文结构并规划全文唯一表图任务", progress=5):
            return self.draft_service.load()
        self.visualization_plan.build(self.task_id, draft)
        self._save_state(status="running", stage="planning", message="全文可视化计划已建立，正在准备全局证据", visualization_plan=self.visualization_plan.summary(self.task_id))
        self._prepare_global_research(selected_model)
        if self._pause_requested():
            return self.draft_service.load()
        for index, section in enumerate(leaves, start=1):
            if str(section.get("id")) in completed:
                continue
            if not self._generate_one_section(section, index, len(leaves), selected_model):
                return self.draft_service.load()
        if not self._supplement(selected_model):
            return self.draft_service.load()
        if not self._checkpoint("completing", "正在生成英文摘要和致谢", progress=96):
            return self.draft_service.load()
        draft = self.draft_service.load()
        if not (draft.get("abstract") or {}).get("en"):
            self.draft_service.generate_en_abstract(selected_model)
        if not draft.get("acknowledgement"):
            self.draft_service.generate_acknowledgement(selected_model)
        with self.draft_service.lock:
            draft = self.draft_service.load()
            stats = self.draft_service._refresh_word_stats(draft)
            state = dict(self._state(draft))
            self.visualization_plan.sync_candidate_statuses(self.task_id, self.research.candidates(self.task_id))
            state.update(status="completed", stage="completed", message="全文生成完成", completed_at=_now(), progress=100, visualization_plan=self.visualization_plan.summary(self.task_id))
            draft[PIPELINE_KEY] = state
            draft.update(generating=False, progress=100 if stats["actual"] >= stats["minimum"] else 98, word_status="completed" if stats["actual"] >= stats["minimum"] else "shortfall")
            self.objects.renumber_document_references(self.task_id, draft)
            self.draft_service.save(draft)
        return self.draft_service.load()

    def regenerate_section(self, section_id: str, model_id: str | None = None) -> dict:
        """Replace only pipeline-owned content in a single section, preserving user edits."""
        with self.draft_service.lock:
            draft = self.draft_service.load()
            section = next((item for item in draft.get("sections") or [] if item.get("id") == section_id), None)
            if not section:
                raise ValueError("未找到正文小节")
            kept = [block for block in section.get("paragraphs") or [] if not (block.get("generation_origin") == "full_paper_pipeline" or block.get("auto_full_paper"))]
            section["paragraphs"] = kept
            state = dict(self._state(draft))
            state.update(status="running", stage="regenerating_section", message=f"正在重新生成 {section.get('number', '')} {section.get('title', '')}", current_section_id=section_id, updated_at=_now())
            self.visualization_plan.reset_section(self.task_id, section_id)
            completed = set(state.get("completed_section_ids") or [])
            completed.discard(section_id)
            state["completed_section_ids"] = sorted(completed)
            draft[PIPELINE_KEY] = state
            draft["generating"] = True
            self.draft_service.save(draft)
        leaves = sorted([item for item in self.draft_service.load().get("sections") or [] if item.get("id") in _leaf_ids(self.draft_service.load().get("sections") or [])], key=lambda item: str(item.get("id")))
        target = next(item for item in leaves if item.get("id") == section_id)
        self._generate_one_section(target, leaves.index(target) + 1, len(leaves), model_id, allow_research=True)
        with self.draft_service.lock:
            draft = self.draft_service.load()
            state = dict(self._state(draft))
            state.update(status="completed", stage="completed", message=f"已重新生成 {target.get('number', '')} {target.get('title', '')}", updated_at=_now())
            draft[PIPELINE_KEY] = state
            draft["generating"] = False
            self.objects.renumber_document_references(self.task_id, draft)
            self.draft_service.save(draft)
        return self.draft_service.load()
