"""上下文管理：outline.json / chapter_summary.json / generation_state.json。

每章只读取「论文目标 + 当前章节要求 + 前面章节摘要」，不重复发送全文，
减少 token 消耗；generation_state.json 支持失败恢复（断点续传）。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_STATE = {
    "stage": "planning",
    "current_chapter": None,
    "progress": 0,
    "outline_done": False,
    "abstract_done": False,
    "conclusion_done": False,
    "completed_chapters": [],
}


class GenerationContext:
    def __init__(self, content_dir: Path):
        self.dir = content_dir
        self.outline_path = self.dir / "outline.json"
        self.summary_path = self.dir / "chapter_summary.json"
        self.state_path = self.dir / "generation_state.json"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def save_outline(self, outline: dict) -> None:
        self.ensure()
        self.outline_path.write_text(
            json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_outline(self) -> dict | None:
        if self.outline_path.exists():
            try:
                return json.loads(self.outline_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def load_summaries(self) -> dict:
        if self.summary_path.exists():
            try:
                return json.loads(self.summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def save_summary(self, key: str, summary: str) -> None:
        summaries = self.load_summaries()
        summaries[key] = summary
        self.ensure()
        self.summary_path.write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    def previous_summary_text(self) -> str:
        summaries = self.load_summaries()
        return "\n".join(f"{k}：{v}" for k, v in summaries.items())

    def load_state(self) -> dict:
        state = dict(DEFAULT_STATE)
        if self.state_path.exists():
            try:
                state.update(json.loads(self.state_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return state

    def save_state(self, state: dict) -> None:
        self.ensure()
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
