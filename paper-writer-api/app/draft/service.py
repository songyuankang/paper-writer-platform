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
            draft = {
                "title": paper_info.get("title", ""),
                "meta": {
                    "major": paper_info.get("major", ""),
                    "paper_type": paper_info.get("paper_type", "课程论文"),
                    "word_count": paper_info.get("word_count", 3000),
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
            user = _prompt("section_generate.txt").format(
                title=paper["title"], major=paper["major"],
                paper_type=paper["paper_type"],
                number=section["number"], section_title=section["title"],
                gist=section.get("gist", ""),
                outline=outline_mod.outline_text(draft["sections"]),
                previous_summaries=self._previous_summaries(draft, section_id) or "（无）",
                references=self._refs_text(draft),
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
        """一键全文：以有限并发为所有叶子小节生成段落。

        每个小节仍由 generate_section 独立持久化，因此单节失败不会丢失
        其他结果；使用有限并发避免一次性打满模型接口触发限流。
        """
        with self.lock:
            draft = self.load()
            draft["generating"] = True
            draft["progress"] = 0
            draft["done"] = 0
            draft["total"] = len(_leaf_ids(draft["sections"]))
            self.save(draft)

        leaf = sorted(
            [s for s in draft["sections"]
             if s["id"] in _leaf_ids(draft["sections"])],
            key=lambda s: s["id"])
        def generate_one(section: dict) -> None:
            if not (section.get("gist") or "").strip():
                return
            self.generate_section(section["id"], model_id)

        done = 0
        # 配置值经过保护性限制，避免错误配置创建过多线程或退化为 0。
        workers = max(1, min(int(settings.draft_generation_workers), 8))
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(leaf))),
                                thread_name_prefix="draft-gen") as pool:
            futures = [pool.submit(generate_one, section) for section in leaf]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:  # noqa: BLE001
                    # 单节失败不阻塞其他小节，结果会保留失败提示，便于重试。
                    pass
                done += 1
                with self.lock:
                    d = self.load()
                    d["progress"] = int(done / max(1, len(leaf)) * 100)
                    d["done"] = done
                    d["generating"] = done < len(leaf)
                    self.save(d)
                if progress_cb:
                    progress_cb(done, len(leaf))

        # 正文全部完成后，自动生成英文摘要；失败只影响英文摘要，不影响正文。
        with self.lock:
            draft = self.load()
            draft["progress"] = 98
            draft["generating"] = True
            self.save(draft)
        self.generate_en_abstract(model_id)

        with self.lock:
            draft = self.load()
            draft["generating"] = False
            draft["progress"] = 100
            self.save(draft)
        if self.task_manager:
            self.task_manager.update(self.task_id, progress=100,
                                     status=TaskStatus.completed,
                                     message="全文生成完成")
        return self.load()

    '''
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
    '''

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
