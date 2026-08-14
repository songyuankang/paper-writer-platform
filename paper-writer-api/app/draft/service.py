"""论文草稿服务：逐段生成编辑器的数据与逻辑。

草稿（draft.json）结构：
{
  title, meta{...}, abstract{zh,en}, keywords{zh,en},
  acknowledgement, references[], generating, progress,
  sections: [{id, number, title, level, gist, paragraphs:[{id,text}]}]
}
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator
from pathlib import Path

from app.config import settings
from app.draft import outline as outline_mod
from app.formatter import service as formatter_service
from app.models.task import TaskStatus
from app.services import deepseek, deepseek_service, model_service


def _prompt(name: str) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8")


def _leaf_ids(sections: list[dict]) -> set[str]:
    """叶子节点 = 不是任何其他节点的父节点（id 前缀）。"""
    ids = {s["id"] for s in sections}
    parents = {s["id"] for s in sections
               if any(o["id"].startswith(s["id"] + "-") for o in sections)}
    return ids - parents


# -- AI 输出清洗 -----------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S.*$")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s+")
_SENTENCE_END_RE = re.compile(r"[。！？；：]$")


def _clean_generated_paragraphs(text: str) -> list[str]:
    """把 AI 生成的章节文本清洗为自然段列表。

    - 丢弃 Markdown 标题行（#/##/###…，标题由 section.title 管理）与表格行
    - 去除行内 Markdown 标记（**粗体**、*斜体*、`代码`、~~删除线~~、列表前缀）
    - 以空行作为自然段边界；单个换行视为段内换行（合并时以空格连接）
    - 兼容“逐行段落”输出：段内每行都以句末标点结尾时按行拆成独立段
    - strip 并过滤空段
    """
    lines: list[str] = []
    for raw in text.splitlines():
        if _MD_HEADING_RE.match(raw) or _MD_TABLE_ROW_RE.match(raw):
            lines.append("")  # 标题/表格行丢弃，但保留自然段边界
            continue
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        line = _MD_LIST_RE.sub("", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", line)
        line = re.sub(r"~~(.+?)~~", r"\1", line)
        line = re.sub(r"`([^`\n]+)`", r"\1", line)
        line = line.strip()
        lines.append(line)

    # 以空行切分自然段
    groups: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        if line:
            buf.append(line)
        elif buf:
            groups.append(buf)
            buf = []
    if buf:
        groups.append(buf)

    result: list[str] = []
    for group in groups:
        if len(group) > 1 and all(
                _SENTENCE_END_RE.search(ln) for ln in group if ln.strip()):
            # 逐行段落：每行都是完整句子 → 按行拆成独立段
            result.extend(ln.strip() for ln in group if ln.strip())
        else:
            result.append(" ".join(ln.strip() for ln in group if ln.strip()))
    return [p for p in result if p.strip()]


def _effective_text_length(text: str) -> int:
    """按编辑器一致的非空白字符口径统计有效正文长度。"""
    return len(re.sub(r"\s+", "", text or ""))


def _body_char_count(draft: dict) -> int:
    """只统计正文叶子小节中的有效文本，不计摘要、致谢和参考文献。"""
    leaf_ids = _leaf_ids(draft.get("sections") or [])
    return sum(
        _effective_text_length(str(paragraph.get("text") or ""))
        for section in draft.get("sections") or []
        if section.get("id") in leaf_ids
        for paragraph in section.get("paragraphs") or []
    )


def _leaf_budget_weight(section: dict) -> float:
    """按章节功能进行温和加权，避免核心分析章节被平均稀释。"""
    title = str(section.get("title") or "")
    if any(word in title for word in ("引言", "绪论", "结论", "总结", "展望")):
        return 0.85
    if any(word in title for word in ("方法", "实证", "结果", "分析", "讨论", "机制", "对策")):
        return 1.15
    return 1.0


def _apply_leaf_budgets(sections: list[dict], target_chars: int) -> None:
    """向每个叶子小节写入目标字数和最低字数，预算总和带少量清洗缓冲。"""
    leaves = sorted(
        [section for section in sections if section.get("id") in _leaf_ids(sections)],
        key=lambda section: str(section.get("id") or ""),
    )
    if not leaves:
        return
    buffered_target = max(int(target_chars * 1.02), target_chars)
    weights = [_leaf_budget_weight(section) for section in leaves]
    weight_sum = sum(weights) or 1.0
    budgets = [max(180, round(buffered_target * weight / weight_sum)) for weight in weights]
    budgets[-1] += buffered_target - sum(budgets)
    for section, budget in zip(leaves, budgets):
        section["target_chars"] = int(budget)
        section["min_chars"] = max(160, int(budget * 0.88))


def _split_en_abstract(text: str) -> tuple[str, list[str]]:
    """把英文摘要生成结果拆分为（摘要, 关键词列表）。

    AI 输出格式为 ``Abstract: <英文摘要> Keywords: <关键词1, 关键词2>``：
    关键词提取到 ``keywords.en``，摘要中剥离 ``Abstract:`` 前缀与
    ``Keywords:`` 行，避免关键词混入摘要正文。
    """
    abstract = text.strip()
    keywords: list[str] = []
    m = re.search(r"Keywords?\s*[：:]\s*(.+)", abstract, flags=re.I | re.S)
    if m:
        parsed = [k.strip() for k in re.split(r"[，,;；]", m.group(1)) if k.strip()]
        keywords = parsed[:5]
    abstract = re.sub(r"Keywords?\s*[：:].*", "", abstract,
                      flags=re.I | re.S).strip()
    abstract = re.sub(r"^Abstract\s*[：:]\s*", "", abstract,
                      flags=re.I).strip()
    return abstract, keywords


class DraftService:
    def __init__(self, task_id: str, task_dir: Path, task_manager=None):
        self.task_id = task_id
        self.task_dir = task_dir
        self.task_manager = task_manager
        self.path = task_dir / "draft.json"
        self.lock = threading.Lock()

    # -- 持久化 ------------------------------------------------------------

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save(self, draft: dict) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    def body_char_count(self, draft: dict | None = None) -> int:
        """返回当前草稿正文有效字数，供生成验收和接口复用。"""
        return _body_char_count(draft if draft is not None else self.load())

    def _refresh_word_stats(self, draft: dict) -> dict:
        target = max(int((draft.get("meta") or {}).get("word_count", 3000)), 500)
        actual = _body_char_count(draft)
        stats = {
            "target": target,
            "minimum": int((draft.get("meta") or {}).get("completion_min_chars", target * 0.95)),
            "actual": actual,
            "shortfall": max(0, target - actual),
        }
        draft["word_stats"] = stats
        return stats

    def _paper_info(self, draft: dict) -> dict:
        meta = draft.get("meta", {})
        return {
            "title": draft.get("title", ""),
            "major": meta.get("major", ""),
            "paper_type": meta.get("paper_type", "课程论文"),
            "word_count": meta.get("word_count", 3000),
            "special_requirements": meta.get("special_requirements"),
            "keywords": meta.get("keywords", []),
            "reference_style": meta.get("reference_style", "gb7714"),
            "references": draft.get("references", []),
        }

    # -- 构建 --------------------------------------------------------------

    def build(self, paper_info: dict, model_id: str | None = None) -> dict:
        """根据论文信息构建草稿（生成三级大纲 + 每叶主旨）。"""
        with self.lock:
            ctx = self._model_ctx(model_id)
            if ctx:
                with ctx:
                    sections = outline_mod.build_outline(paper_info)
            else:
                sections = outline_mod.build_outline(paper_info)
            target_body_chars = max(int(paper_info.get("word_count", 3000)), 500)
            _apply_leaf_budgets(sections, target_body_chars)
            draft = {
                "title": paper_info.get("title", ""),
                "meta": {
                    "major": paper_info.get("major", ""),
                    "paper_type": paper_info.get("paper_type", "课程论文"),
                    "word_count": target_body_chars,
                    "completion_min_chars": int(target_body_chars * 0.95),
                    "special_requirements": paper_info.get("special_requirements"),
                    "keywords": paper_info.get("keywords", []),
                    "reference_style": paper_info.get("reference_style", "gb7714"),
                },
                "abstract": {"zh": paper_info.get("abstract") or "", "en": ""},
                "keywords": {"zh": paper_info.get("keywords") or [], "en": []},
                "acknowledgement": "",
                "references": list(paper_info.get("references") or []),
                "sections": sections,
                "generating": False,
                "progress": 0,
                "done": 0,
                "total": len(_leaf_ids(sections)),
                "word_stats": {
                    "target": target_body_chars,
                    "minimum": int(target_body_chars * 0.95),
                    "actual": 0,
                    "shortfall": target_body_chars,
                },
            }
            self.save(draft)
            return draft

    # -- 段落 / 小节操作 ----------------------------------------------------

    def _find_section(self, draft: dict, section_id: str) -> dict:
        for s in draft["sections"]:
            if s["id"] == section_id:
                return s
        raise ValueError(f"小节不存在: {section_id}")

    def _next_paragraph_id(self, section: dict) -> str:
        return f"p{len(section['paragraphs']) + 1}-{uuid.uuid4().hex[:6]}"

    def add_paragraph(self, section_id: str, text: str = "") -> dict:
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            para = {"id": self._next_paragraph_id(section), "text": text}
            section["paragraphs"].append(para)
            self.save(draft)
            return para

    def update_paragraph(self, pid: str, text: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                for p in s["paragraphs"]:
                    if p["id"] == pid:
                        p["text"] = text
                        self.save(draft)
                        return
            raise ValueError(f"段落不存在: {pid}")

    def delete_paragraph(self, pid: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                before = len(s["paragraphs"])
                s["paragraphs"] = [p for p in s["paragraphs"] if p["id"] != pid]
                if len(s["paragraphs"]) != before:
                    self.save(draft)
                    return
            raise ValueError(f"段落不存在: {pid}")

    def move_paragraph(self, pid: str, direction: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                paras = s["paragraphs"]
                idx = next((i for i, p in enumerate(paras) if p["id"] == pid), None)
                if idx is None:
                    continue
                target = idx - 1 if direction == "up" else idx + 1
                if target < 0 or target >= len(paras):
                    return
                paras[idx], paras[target] = paras[target], paras[idx]
                self.save(draft)
                return
            raise ValueError(f"段落不存在: {pid}")

    def update_section(self, section_id: str, title: str | None = None,
                       gist: str | None = None) -> None:
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            if title is not None:
                section["title"] = title
            if gist is not None:
                section["gist"] = gist
            self.save(draft)

    # -- AI 生成 ------------------------------------------------------------

    def _previous_summaries(self, draft: dict, section_id: str) -> str:
        """收集当前小节之前所有已生成内容的摘要（避免重复）。"""
        summaries: list[str] = []
        for s in draft["sections"]:
            for p in s["paragraphs"]:
                text = (p.get("text") or "").strip()
                if text:
                    summaries.append(f"{s['number']} {s['title']}：{text[:120]}")
            if s["id"] == section_id:
                break
        return "\n".join(summaries)

    def _refs_text(self, draft: dict) -> str:
        refs = draft.get("references") or []
        return "\n".join(f"[{i + 1}] {r}" for i, r in enumerate(refs)) or "（无）"

    def _model_ctx(self, model_id: str | None):
        model_cfg = model_service.resolve_model(model_id)
        if model_cfg:
            return deepseek.connection(model_cfg)
        return None

    def generate_section(self, section_id: str, model_id: str | None = None) -> dict:
        """按小节标题+主旨生成一个或多个段落，追加到该小节。

        AI 返回文本经 ``_clean_generated_paragraphs`` 清洗后按自然段写入
        ``paragraphs``：首段写入本次生成的段落，其余自然段追加为小节新段落。
        """
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            if not (section.get("gist") or "").strip():
                raise ValueError(f"小节「{section['title']}」没有段落主旨，请先填写主旨")
            paper = self._paper_info(draft)
            # 旧草稿没有预算字段时按当前目标补齐，确保重新生成也受长度约束。
            if not section.get("target_chars"):
                _apply_leaf_budgets(draft["sections"], int(paper["word_count"]))
                section = self._find_section(draft, section_id)
            target_chars = max(int(section.get("target_chars") or 300), 180)
            min_chars = min(
                target_chars,
                max(int(section.get("min_chars") or target_chars * 0.88), 160),
            )
            user = _prompt("section_generate.txt").format(
                title=paper["title"], major=paper["major"],
                paper_type=paper["paper_type"],
                number=section["number"], section_title=section["title"],
                gist=section.get("gist", ""),
                outline=outline_mod.outline_text(draft["sections"]),
                previous_summaries=self._previous_summaries(draft, section_id) or "（无）",
                references=self._refs_text(draft),
                target_chars=target_chars,
                min_chars=min_chars,
            )
            para = {"id": self._next_paragraph_id(section), "text": ""}
            section["paragraphs"].append(para)
            self.save(draft)

        ctx = self._model_ctx(model_id)
        try:
            if ctx:
                with ctx:
                    text = deepseek.chat(
                        [{"role": "system",
                          "content": deepseek_service.system_prompt()},
                         {"role": "user", "content": user}])
            else:
                text = f"（未配置 AI 模型）{section['title']}：请配置模型后生成。"
            if not text.strip():
                text = (f"（生成结果为空）{section['title']}："
                        "请检查模型配置后重新生成。")
            segments = _clean_generated_paragraphs(text) or [text.strip()]
        except deepseek.DeepSeekError as exc:
            segments = [f"（生成失败：{exc}）"]
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                if s["id"] == section_id:
                    for p in s["paragraphs"]:
                        if p["id"] == para["id"]:
                            p["text"] = segments[0]
                            break
                    for seg in segments[1:]:
                        s["paragraphs"].append(
                            {"id": self._next_paragraph_id(s), "text": seg})
            self.save(draft)
        return para

    def _section_char_count(self, section: dict) -> int:
        return sum(
            _effective_text_length(str(paragraph.get("text") or ""))
            for paragraph in section.get("paragraphs") or []
        )

    def _supplement_section(self, section_id: str, requested_chars: int,
                            model_id: str | None = None) -> int:
        """仅向字数不足的小节追加新论证，不覆盖既有或用户编辑的文本。"""
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            paper = self._paper_info(draft)
            current_text = "\n".join(
                str(paragraph.get("text") or "").strip()
                for paragraph in section.get("paragraphs") or []
                if str(paragraph.get("text") or "").strip()
            )
            target = max(int(section.get("target_chars") or requested_chars), requested_chars)
            requested = min(max(int(requested_chars), 160), 1200)
            user = (
                f"论文题目：{paper['title']}\n专业方向：{paper['major']}\n"
                f"当前小节：{section['number']} {section['title']}\n"
                f"小节主旨：{section.get('gist', '')}\n"
                f"当前已写正文：\n{current_text}\n\n"
                f"该小节目标约 {target} 字，目前仍需补充约 {requested} 字。"
                "请只新增 2—4 个自然段的学术论证，补足尚未覆盖的概念、机制、依据、分析或小结；"
                "不得复述当前文本，不得编造数据、表格、参考文献或实验结论，不得输出标题、列表、Markdown 或说明文字。"
            )
        ctx = self._model_ctx(model_id)
        if not ctx:
            return 0
        try:
            with ctx:
                generated = deepseek.chat(
                    [{"role": "system", "content": deepseek_service.system_prompt()},
                     {"role": "user", "content": user}]
                )
            segments = _clean_generated_paragraphs(generated)
        except deepseek.DeepSeekError:
            return 0
        if not segments:
            return 0
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            for segment in segments:
                section["paragraphs"].append(
                    {"id": self._next_paragraph_id(section), "text": segment}
                )
            self._refresh_word_stats(draft)
            self.save(draft)
        return sum(_effective_text_length(segment) for segment in segments)

    def _deficient_leaf_sections(self, draft: dict) -> list[dict]:
        leaf_ids = _leaf_ids(draft.get("sections") or [])
        rows = []
        for section in draft.get("sections") or []:
            if section.get("id") not in leaf_ids:
                continue
            target = max(int(section.get("target_chars") or 180), 180)
            rows.append((target - self._section_char_count(section), section))
        return [section for deficit, section in sorted(rows, key=lambda row: row[0], reverse=True) if deficit > 0]

    def generate_acknowledgement(self, model_id: str | None = None) -> str:
        """生成致谢。"""
        with self.lock:
            draft = self.load()
            paper = self._paper_info(draft)
            user = (f"论文题目：{paper['title']}\n专业：{paper['major']}\n"
                    "请生成 150-250 字的论文致谢（学术语体，感谢导师、同学与家人）。"
                    "只输出致谢文本。")
        ctx = self._model_ctx(model_id)
        try:
            if ctx:
                with ctx:
                    text = deepseek.chat(
                        [{"role": "system",
                          "content": deepseek_service.system_prompt()},
                         {"role": "user", "content": user}])
            else:
                text = "（未配置 AI 模型）"
            text = text.strip()
        except deepseek.DeepSeekError as exc:
            text = f"（生成失败：{exc}）"
        with self.lock:
            draft = self.load()
            draft["acknowledgement"] = text
            self.save(draft)
        return text

    def generate_en_abstract(self, model_id: str | None = None) -> str:
        """根据中文摘要生成英文摘要（自动拆分关键词到 keywords.en）。"""
        with self.lock:
            draft = self.load()
            zh = draft.get("abstract", {}).get("zh", "")
            user = (f"请将以下论文摘要翻译为英文，并给出英文关键词（逗号分隔）。\n"
                    f"格式：\nAbstract：<英文摘要>\nKeywords：<英文关键词>\n\n{zh}")
        ctx = self._model_ctx(model_id)
        try:
            if ctx:
                with ctx:
                    text = deepseek.chat(
                        [{"role": "system",
                          "content": deepseek_service.system_prompt()},
                         {"role": "user", "content": user}])
            else:
                text = "（未配置 AI 模型）"
            text = text.strip()
        except deepseek.DeepSeekError as exc:
            text = f"（生成失败：{exc}）"
        abstract_en, keywords_en = _split_en_abstract(text)
        with self.lock:
            draft = self.load()
            draft["abstract"]["en"] = abstract_en
            if keywords_en:
                draft.setdefault("keywords", {})["en"] = keywords_en
            self.save(draft)
        return abstract_en

    def oneclick(self, model_id: str | None = None,
                 progress_cb=None) -> dict:
        """一键全文：首轮生成后验收字数，并对不足小节定向补写。"""
        with self.lock:
            draft = self.load()
            target_chars = max(int((draft.get("meta") or {}).get("word_count", 3000)), 500)
            _apply_leaf_budgets(draft["sections"], target_chars)
            draft.update(generating=True, progress=0, done=0,
                         total=len(_leaf_ids(draft["sections"])),
                         word_status="generating", supplement_rounds=0)
            self._refresh_word_stats(draft)
            self.save(draft)

        leaf = sorted(
            [section for section in draft["sections"]
             if section["id"] in _leaf_ids(draft["sections"])],
            key=lambda section: section["id"],
        )
        done = 0
        for section in leaf:
            try:
                if (section.get("gist") or "").strip():
                    self.generate_section(section["id"], model_id)
            except Exception:  # noqa: BLE001
                pass
            done += 1
            with self.lock:
                current = self.load()
                current["progress"] = min(80, int(done / max(1, len(leaf)) * 80))
                current["done"] = done
                current["generating"] = True
                self._refresh_word_stats(current)
                self.save(current)
            if progress_cb:
                progress_cb(done, len(leaf))

        # 最多两轮：按小节缺口从大到小补写，避免无限扩写或覆盖已有正文。
        rounds = 0
        for round_index in range(2):
            with self.lock:
                current = self.load()
                stats = self._refresh_word_stats(current)
                if stats["actual"] >= stats["minimum"]:
                    self.save(current)
                    break
                current["word_status"] = "supplementing"
                current["supplement_rounds"] = round_index + 1
                current["progress"] = 80 + round_index * 8
                candidates = self._deficient_leaf_sections(current)
                self.save(current)
            if not candidates:
                break
            rounds = round_index + 1
            for section in candidates:
                with self.lock:
                    latest = self.load()
                    latest_stats = self._refresh_word_stats(latest)
                    if latest_stats["actual"] >= latest_stats["minimum"]:
                        self.save(latest)
                        break
                    fresh_section = self._find_section(latest, section["id"])
                    deficit = max(int(fresh_section.get("target_chars") or 0)
                                  - self._section_char_count(fresh_section), 0)
                    global_share = max(
                        160,
                        (latest_stats["minimum"] - latest_stats["actual"]
                         + max(1, len(candidates)) - 1) // max(1, len(candidates)),
                    )
                if deficit > 0:
                    self._supplement_section(
                        section["id"], min(max(deficit, global_share), 1200), model_id
                    )

        with self.lock:
            draft = self.load()
            stats = self._refresh_word_stats(draft)
            meets_minimum = stats["actual"] >= stats["minimum"]
            draft["generating"] = False
            draft["supplement_rounds"] = rounds
            draft["word_status"] = "completed" if meets_minimum else "shortfall"
            draft["progress"] = 100 if meets_minimum else 98
            self.save(draft)
        if self.task_manager:
            message = (
                "全文生成完成，字数已达标"
                if meets_minimum
                else f"正文仍差 {stats['shortfall']} 字，可继续补写"
            )
            self.task_manager.update(
                self.task_id,
                progress=100 if meets_minimum else 98,
                status=TaskStatus.completed,
                message=message,
            )
        return self.load()

    def oneclick_stream(self, model_id: str | None = None) -> Iterator[dict]:
        """按小节串行生成，并实时产出 AI 文本片段。"""
        with self.lock:
            draft = self.load()
            draft.update(generating=True, progress=0, done=0,
                         total=len(_leaf_ids(draft["sections"])))
            self.save(draft)
        leaf = [s for s in draft["sections"] if s["id"] in _leaf_ids(draft["sections"])]
        total = len(leaf)
        for index, section in enumerate(leaf):
            if not (section.get("gist") or "").strip():
                continue
            sid = section["id"]
            with self.lock:
                current = self.load()
                sec = self._find_section(current, sid)
                paper = self._paper_info(current)
                prompt = _prompt("section_generate.txt").format(
                    title=paper["title"], major=paper["major"], paper_type=paper["paper_type"],
                    number=sec["number"], section_title=sec["title"], gist=sec.get("gist", ""),
                    outline=outline_mod.outline_text(current["sections"]),
                    previous_summaries=self._previous_summaries(current, sid) or "（无）",
                    references=self._refs_text(current))
                pid = self._next_paragraph_id(sec)
                sec["paragraphs"].append({"id": pid, "text": ""})
                self.save(current)
            ctx = self._model_ctx(model_id)
            try:
                if ctx:
                    with ctx:
                        chunks = deepseek.chat_stream([
                            {"role": "system", "content": deepseek_service.system_prompt()},
                            {"role": "user", "content": prompt}])
                        for chunk in chunks:
                            with self.lock:
                                current = self.load()
                                target = self._find_section(current, sid)
                                target["paragraphs"][-1]["text"] += chunk
                                self.save(current)
                            yield {"type": "chunk", "section_id": sid, "text": chunk}
                else:
                    text = f"（未配置 AI 模型）{section['title']}：请配置模型后生成。"
                    with self.lock:
                        current = self.load()
                        self._find_section(current, sid)["paragraphs"][-1]["text"] = text
                        self.save(current)
                    yield {"type": "chunk", "section_id": sid, "text": text}
            except deepseek.DeepSeekError as exc:
                yield {"type": "error", "section_id": sid, "message": str(exc)}
            with self.lock:
                current = self.load()
                current.update(done=index + 1,
                               progress=int((index + 1) / max(1, total) * 100),
                               generating=index + 1 < total)
                self.save(current)
            yield {"type": "section_done", "done": index + 1, "total": total,
                   "progress": int((index + 1) / max(1, total) * 100)}

        # 一键全文收尾时自动补充英文摘要。
        yield {"type": "stage", "stage": "english_abstract",
               "message": "正在生成英文摘要..."}
        try:
            english_abstract = self.generate_en_abstract(model_id)
            yield {"type": "english_abstract", "text": english_abstract}
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "stage": "english_abstract",
                   "message": f"英文摘要生成失败：{exc}"}
        with self.lock:
            current = self.load()
            current.update(generating=False, progress=100)
            self.save(current)
        yield {"type": "completed", "done": total, "total": total, "progress": 100}

    # -- 导出 --------------------------------------------------------------

    def export(self, template_path: Path | None = None,
               template_id: str | None = None) -> list[str]:
        """把草稿组装为 spec 并格式化出 docx。"""
        with self.lock:
            draft = self.load()
        paper = self._paper_info(draft)
        spec_sections: list[dict] = []
        for s in draft["sections"]:
            htype = {1: "h1", 2: "h2", 3: "h3"}.get(s["level"], "h2")
            spec_sections.append({"type": htype, "text": f"{s['number']} {s['title']}"})
            for p in s["paragraphs"]:
                text = (p.get("text") or "").strip()
                if text:
                    spec_sections.append({"type": "p", "text": text})
        if (draft.get("acknowledgement") or "").strip():
            spec_sections.append({"type": "h1", "text": "致谢"})
            spec_sections.append({"type": "p", "text": draft["acknowledgement"]})
        refs = draft.get("references") or []
        spec_sections.append({"type": "references", "items": refs})

        spec = {
            "meta": {
                "title": paper["title"],
                "abstract": draft.get("abstract", {}).get("zh", ""),
                "keywords": draft.get("keywords", {}).get("zh", []),
                # 模板渲染器使用 abstract_en / keywords_en 渲染英文摘要页。
                # 这里必须从草稿传递，不能只依赖导出阶段的自动翻译回退。
                "abstract_en": draft.get("abstract", {}).get("en", ""),
                "keywords_en": draft.get("keywords", {}).get("en", []),
                "reference_style": paper.get("reference_style", "gb7714"),
                "citation_style": "numeric",
            },
            "sections": spec_sections,
            "references": refs,
        }
        files = formatter_service.format_paper(
            self.task_id, self.task_dir, paper, spec,
            charts=None, template_path=template_path, template_id=template_id)
        if self.task_manager:
            self.task_manager.update(
                self.task_id, progress=100, status=TaskStatus.completed,
                files=files, message="导出完成")
        return files
