"""AI 分段式论文生成编排（第一阶段）。

流程：planning → outline_generating → abstract → chapter_generating（逐章）→
summary_generating → conclusion_generating → checking → completed。
只输出 paper_content/（outline.json / abstract.md / chapterN.md /
conclusion.md / references.json / chapter_summary.json / generation_state.json）。
状态保存在 generation_state.json，支持失败恢复（断点续传）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.generation import (
    chapter_generator,
    context_manager,
    planner,
    quality_check,
)
from app.services import history_service


class ContentGenerator:
    def __init__(self, task_id: str, paper_info: dict, content_dir: Path,
                 task_manager):
        self.task_id = task_id
        self.paper_info = paper_info
        self.ctx = context_manager.GenerationContext(content_dir)
        self.task_manager = task_manager

    def _update(self, stage: str, progress: int, message: str,
                chapter: str | None = None, count: int | None = None) -> None:
        self.task_manager.update(
            self.task_id, progress=progress, message=message,
            current_stage=stage, current_chapter=chapter, chapter_count=count)
        history_service.update_record_progress(
            self.task_id, current_stage=stage, progress=progress,
            current_chapter=chapter, chapter_count=count)

    def _write(self, name: str, content: str) -> None:
        self.ctx.ensure()
        (self.ctx.dir / name).write_text(content, encoding="utf-8")

    def _write_json(self, name: str, data) -> None:
        self.ctx.ensure()
        (self.ctx.dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self) -> dict:
        """执行内容生成，返回清单（manifest）。失败可再次调用以续传。"""
        state = self.ctx.load_state()

        # 阶段1-2：规划 + 大纲
        if not state["outline_done"]:
            self._update("planning", 8, "正在生成论文计划...")
            plan = planner.generate_plan(self.paper_info)
            self.ctx.save_outline(plan)
            state["outline_done"] = True
            state["stage"] = "outline_generating"
            state["progress"] = 12
            self.ctx.save_state(state)
            self._update("outline_generating", 12, "论文大纲生成完成")
        outline = self.ctx.load_outline() or {"chapters": [], "outline_text": ""}

        # 阶段3：摘要（支持用户自定义摘要覆盖自动生成）
        if not state["abstract_done"]:
            self._update("outline_generating", 15, "正在生成摘要...")
            user_abstract = (self.paper_info.get("abstract") or "").strip()
            if user_abstract:
                # 用户在创作向导第②步定稿的摘要
                abstract = user_abstract
                keywords = self.paper_info.get("keywords") or []
                self._update("outline_generating", 18, "摘要已使用用户自定义内容")
            else:
                abstract, keywords = chapter_generator.generate_abstract(self.paper_info)
            self._write("abstract.md", abstract)
            self._write_json("keywords.json", keywords)
            state["abstract_done"] = True
            state["stage"] = "outline_generating"
            self.ctx.save_state(state)
            self._update("outline_generating", 18, "摘要生成完成")

        # 阶段4：逐章生成（断点：跳过已生成章节）
        chapters = outline.get("chapters", [])
        outline_text = outline.get("outline_text", "")
        done = set(state.get("completed_chapters", []))
        total = len(chapters)
        for i, ch in enumerate(chapters):
            title = ch["title"]
            if title in done:
                continue
            self._update(
                "chapter_generating",
                20 + int(40 * (i + 1) / max(1, total)),
                f"正在生成第{i + 1}章：{title}...", title, total)
            requirements = {
                "outline": outline_text,
                "special_requirements": self.paper_info.get("special_requirements"),
            }
            previous = self.ctx.previous_summary_text()
            text = chapter_generator.generate_section(
                self.paper_info, ch, previous, requirements)
            blocks = chapter_generator.parse_section_markdown(text)
            self._write(f"chapter{i + 1}.md", text)
            self._write_json(f"chapter{i + 1}.json",
                             {"title": title, "blocks": blocks})
            self._update("summary_generating",
                         22 + int(38 * (i + 1) / max(1, total)),
                         f"已保存第{i + 1}章：{title}")
            self.ctx.save_summary(f"第{i + 1}章",
                                  text.strip().replace("\n", "")[:200])
            state.setdefault("completed_chapters", []).append(title)
            state["current_chapter"] = title
            state["stage"] = "chapter_generating"
            self.ctx.save_state(state)

        # 阶段5：结论
        if not state["conclusion_done"]:
            last_title = chapters[-1]["title"] if chapters else ""
            if any(k in last_title for k in ("结论", "总结", "展望")):
                # 结论已包含在末章：仍写出 conclusion.md（满足输出契约，不重复入 spec）
                last_md = self.ctx.dir / f"chapter{len(chapters)}.md"
                if last_md.exists():
                    self._write("conclusion.md", last_md.read_text(encoding="utf-8"))
                self._update("conclusion_generating", 66, "结论章节已包含在正文中")
            else:
                self._update("conclusion_generating", 66, "正在生成结论...")
                text = chapter_generator.generate_conclusion(
                    self.paper_info, self.ctx.previous_summary_text())
                self._write("conclusion.md", text)
                self._write_json("conclusion.json",
                                 {"title": "结论",
                                  "blocks": chapter_generator.parse_section_markdown(text)})
            state["conclusion_done"] = True
            state["stage"] = "conclusion_generating"
            state["progress"] = 70
            self.ctx.save_state(state)
            self._update("conclusion_generating", 70, "结论生成完成")

        # 阶段6：参考文献（支持用户在第③步选择的真实文献覆盖）
        user_refs = self.paper_info.get("references") or []
        if user_refs:
            refs = list(user_refs)
        else:
            style = self.paper_info.get("reference_style", "gb7714")
            try:
                refs = chapter_generator.generate_references(self.paper_info, style)
            except Exception:
                refs = [f"[示例] 示例作者. 与《{self.paper_info.get('title', '')}》相关的示例文献."]
        self._write_json("references.json", refs)

        # 阶段7：全文检查
        chapters_out = self._collect_chapters()
        self._update("checking", 88, "正在检查论文...")
        try:
            result = quality_check.check_paper(
                self.paper_info, quality_check.collect_full_text(chapters_out))
        except Exception:
            result = {"problems": ["全文检查调用失败"], "suggestions": []}
        self._write_json("paper_check_result.json", result)

        # 完成
        state["stage"] = "completed"
        state["progress"] = 95
        self.ctx.save_state(state)
        self._update("completed", 95, "论文内容生成完成")
        return self.manifest()

    def _collect_chapters(self) -> list[dict]:
        outline = self.ctx.load_outline() or {"chapters": []}
        chapters = []
        for i, ch in enumerate(outline.get("chapters", [])):
            path = self.ctx.dir / f"chapter{i + 1}.json"
            data = {"title": ch["title"], "blocks": []}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            chapters.append(data)
        conclusion_path = self.ctx.dir / "conclusion.json"
        if conclusion_path.exists():
            try:
                chapters.append(json.loads(conclusion_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return chapters

    def manifest(self) -> dict:
        """返回内容清单（供前端内容预览 / 格式处理）。"""
        outline = self.ctx.load_outline() or {"chapters": []}
        abstract = ""
        abstract_path = self.ctx.dir / "abstract.md"
        if abstract_path.exists():
            abstract = abstract_path.read_text(encoding="utf-8")
        keywords = []
        kw_path = self.ctx.dir / "keywords.json"
        if kw_path.exists():
            try:
                keywords = json.loads(kw_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        chapters = []
        for i, ch in enumerate(outline.get("chapters", [])):
            text = ""
            md = self.ctx.dir / f"chapter{i + 1}.md"
            if md.exists():
                text = md.read_text(encoding="utf-8")
            chapters.append({"title": ch["title"], "text": text})
        conclusion = ""
        cp = self.ctx.dir / "conclusion.md"
        if cp.exists():
            conclusion = cp.read_text(encoding="utf-8")
        refs = []
        rp = self.ctx.dir / "references.json"
        if rp.exists():
            try:
                refs = json.loads(rp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {
            "outline": outline,
            "abstract": abstract,
            "keywords": keywords,
            "chapters": chapters,
            "conclusion": conclusion,
            "references": refs,
        }
