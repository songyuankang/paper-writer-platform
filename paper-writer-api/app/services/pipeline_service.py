"""分段生成流水线（generation_strategy=section）。

阶段：规划 → 摘要 → 逐章（独立请求+上下文）→ 结论 → 参考文献 → 全文检查 → docx。
检查点文件（outline.json / chapter_summary.json / content.json）支持断点续传：
某章失败后重跑会从失败章节继续，不重复生成前面的章节。
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from pathlib import Path

from app.models.generate import GenerateRequest
from app.services import deepseek, deepseek_service, history_service, model_service
from app.services.outline_service import allocate_words
from app.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


class PaperPipeline:
    def __init__(self, task_id: str, req: GenerateRequest, task_dir: Path,
                 task_manager: TaskManager):
        self.task_id = task_id
        self.req = req
        self.task_dir = task_dir
        self.task_manager = task_manager

    # ------------------------------------------------------------------ 工具

    def _path(self, name: str) -> Path:
        return self.task_dir / name

    def _load(self, name: str) -> dict | None:
        path = self._path(name)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def _save(self, name: str, data: dict) -> None:
        self._path(name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update(self, stage: str, progress: int, message: str,
                chapter: str | None = None, count: int | None = None) -> None:
        self.task_manager.update(
            self.task_id, progress=progress, message=message,
            current_stage=stage, current_chapter=chapter,
            chapter_count=count)
        history_service.update_record_progress(
            self.task_id, current_stage=stage, progress=progress,
            current_chapter=chapter, chapter_count=count)

    # ------------------------------------------------------------------ 主流程

    def run(self) -> dict:
        """执行分段生成，返回 paper_spec.json 字典。"""
        model_cfg = model_service.resolve_model(self.req.model_id)
        ctx = deepseek.connection(model_cfg) if model_cfg else nullcontext()
        with ctx:
            outline = self._load("outline.json")
            if outline is None:
                self._stage_plan()
                outline = self._load("outline.json") or {
                    "chapters": [], "outline_text": ""}

            content = self._load("content.json") or {
                "meta": {
                    "title": self.req.title,
                    "major": self.req.major,
                    "paper_type": self.req.paper_type,
                    "word_count": self.req.word_count,
                    "special_requirements": self.req.special_requirements,
                    "reference_style": self.req.reference_style,
                    "citation_style": "numeric",
                },
                "chapters": [],
                "references": [],
            }

            if not content.get("meta", {}).get("abstract"):
                self._stage_abstract(content)

            self._stage_chapters(outline, content)
            self._stage_conclusion(outline, content)
            self._stage_references(content)
            self._stage_check(content)
            self._save("content.json", content)
            return self._to_spec(content)

    # ------------------------------------------------------------------ 各阶段

    def _stage_plan(self) -> None:
        self._update("planning", 8, "正在生成论文规划...")
        plan = deepseek_service.generate_plan(self.req)
        chapters = plan["chapters"]
        total = sum(int(c.get("words") or 0) for c in chapters)
        if total <= 0:
            allocated = allocate_words(len(chapters), self.req.word_count)
            for i, c in enumerate(chapters):
                c["words"] = allocated[i]
        self._save("outline.json", {
            "outline_text": plan["outline_text"],
            "chapters": chapters,
        })
        self._update("planning", 12, "论文规划完成")

    def _stage_abstract(self, content: dict) -> None:
        self._update("generating_abstract", 16, "正在生成摘要...")
        abstract, keywords = deepseek_service.generate_abstract(
            self.req.title, self.req.major, self.req.paper_type,
            (self.req.special_requirements or "").strip())
        content["meta"]["abstract"] = abstract
        content["meta"]["keywords"] = keywords
        self._save("content.json", content)
        self._update("generating_abstract", 18, "摘要生成完成")

    def _stage_chapters(self, outline: dict, content: dict) -> None:
        chapters = outline.get("chapters", [])
        outline_text = outline.get("outline_text", "")
        existing = {ch["title"] for ch in content.get("chapters", [])}
        summaries = self._load("chapter_summary.json") or {}
        total = len(chapters)
        for i, plan_ch in enumerate(chapters):
            title = plan_ch["title"]
            if title in existing:
                continue  # 断点续传：跳过已生成章节
            self._update(
                "generating_chapter",
                20 + int(40 * (i + 1) / max(1, total)),
                f"正在生成第{i + 1}章：{title}...", title, total)
            previous = "\n".join(f"{k}：{v}" for k, v in summaries.items())
            text = deepseek_service.generate_chapter(
                self.req, title, int(plan_ch.get("words") or 0),
                plan_ch.get("focus", ""), outline_text, previous)
            blocks = deepseek_service._parse_chapter(text)
            content.setdefault("chapters", []).append({
                "id": f"ch{len(content['chapters']) + 1}",
                "title": title, "level": 1, "blocks": blocks,
            })
            summaries[f"第{i + 1}章"] = text.strip().replace("\n", "")[:200]
            self._save("chapter_summary.json", summaries)
            self._save("content.json", content)

    def _stage_conclusion(self, outline: dict, content: dict) -> None:
        chapters = outline.get("chapters", [])
        last_title = chapters[-1].get("title", "") if chapters else ""
        if any(k in last_title for k in ("结论", "总结", "展望")):
            self._update("generating_conclusion", 66,
                         "结论章节已包含在正文中")
            return
        self._update("generating_conclusion", 66, "正在生成结论...")
        summaries = self._load("chapter_summary.json") or {}
        summary_text = "\n".join(f"{k}：{v}" for k, v in summaries.items())
        words = max(300, int(self.req.word_count * 0.1))
        text = deepseek_service.generate_conclusion(self.req, summary_text, words)
        blocks = deepseek_service._parse_chapter(text)
        content.setdefault("chapters", []).append({
            "id": f"ch{len(content['chapters']) + 1}",
            "title": "结论", "level": 1, "blocks": blocks,
        })
        self._save("content.json", content)
        self._update("generating_conclusion", 70, "结论生成完成")

    def _stage_references(self, content: dict) -> None:
        self._update("generating_reference", 78, "正在生成参考文献...")
        try:
            refs = deepseek_service.generate_references(
                self.req, self.req.reference_style)
        except deepseek.DeepSeekError:
            logger.warning("参考文献生成失败，使用示例占位", exc_info=True)
            refs = [f"[示例] 示例作者. 与《{self.req.title}》相关的示例文献."]
        content["references"] = refs
        self._save("content.json", content)
        self._update("generating_reference", 82, "参考文献生成完成")

    def _stage_check(self, content: dict) -> None:
        self._update("checking", 88, "正在检查论文...")
        parts = []
        for ch in content.get("chapters", []):
            parts.append(ch["title"])
            for b in ch.get("blocks", []):
                if b.get("type") in ("p", "h2", "h3"):
                    parts.append(b.get("text", ""))
        full_text = "\n".join(parts)
        try:
            result = deepseek_service.check_paper(self.req, full_text)
        except deepseek.DeepSeekError:
            result = {"problems": ["全文检查调用失败"], "suggestions": []}
        self._save("paper_check_result.json", result)
        self._update("checking", 92, "论文检查完成")

    # ------------------------------------------------------------------ 输出

    def _to_spec(self, content: dict) -> dict:
        meta = dict(content.get("meta", {}))
        sections: list[dict] = []
        for ch in content.get("chapters", []):
            sections.append({"type": "h1", "text": ch["title"]})
            for b in ch.get("blocks", []):
                t = b.get("type")
                if t == "p":
                    sections.append({"type": "p", "text": b.get("text", "")})
                elif t in ("h2", "h3"):
                    sections.append({"type": t, "text": b.get("text", "")})
                elif t == "table":
                    sections.append({"type": "table", "title": b.get("title", ""),
                                     "headers": b.get("headers", []),
                                     "rows": b.get("rows", [])})
                elif t == "figure":
                    sections.append({"type": "figure", "path": b.get("path", ""),
                                     "title": b.get("title", "")})
        references = content.get("references", [])
        sections.append({"type": "references", "items": references})
        return {"meta": meta, "sections": sections, "references": references}
