"""DeepSeek 内容生成编排：论文正文、大纲、章节/段落修改。

Prompt 统一放在 prompts/ 目录，不在代码中写死。未配置 API Key 时由上层回退。
"""

from __future__ import annotations

import json
import re
from typing import Callable

from app.config import settings
from app.models.generate import GenerateRequest
from app.services import deepseek, outline_service
from app.services.content_generator import OUTLINES, make_example_refs


def _prompt(name: str) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8")


def system_prompt() -> str:
    return _prompt("paper_system.txt")


def _default_keywords(title: str, major: str) -> list[str]:
    return [major, title[:8] if len(title) > 8 else title, "研究"]


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def generate_plan(request: GenerateRequest) -> dict:
    """阶段1：生成论文规划（章节/目标字数/写作重点 + 大纲文本）。"""
    user = _prompt("outline_generate.txt").format(
        title=request.title, major=request.major,
        paper_type=request.paper_type, word_count=request.word_count)
    content = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])
    data = _extract_json(content)
    if not data or not data.get("chapters") or not data.get("outline_text"):
        raise deepseek.DeepSeekModelError("论文规划输出解析失败，请重试")
    return {
        "chapters": data["chapters"],
        "outline_text": data["outline_text"],
    }


def generate_abstract(title: str, major: str, paper_type: str,
                      special_requirements: str) -> tuple[str, list[str]]:
    """阶段2：生成摘要与关键词。"""
    user = _prompt("abstract_generate.txt").format(
        title=title, major=major, paper_type=paper_type,
        special_requirements=special_requirements)
    text = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])
    return _parse_abstract(text, _default_keywords(title, major))


def generate_chapter(request: GenerateRequest, chapter_title: str,
                     chapter_words: int, focus: str, outline: str,
                     previous_summaries: str) -> str:
    """阶段3：生成单个章节（只带大纲/前章摘要/本章要求，节省 token）。"""
    user = _prompt("chapter_generate.txt").format(
        title=request.title, major=request.major,
        paper_type=request.paper_type, chapter_title=chapter_title,
        chapter_words=chapter_words,
        focus=focus or chapter_title,
        special_requirements=(request.special_requirements or "").strip() or "无",
        outline=outline,
        previous_summaries=previous_summaries or "（无）")
    return deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])


def generate_conclusion(request: GenerateRequest, chapter_summaries: str,
                        words: int) -> str:
    """阶段4：生成结论章节。"""
    user = _prompt("conclusion_generate.txt").format(
        title=request.title, major=request.major,
        chapter_summaries=chapter_summaries or "（无）",
        special_requirements=(request.special_requirements or "").strip() or "无",
        words=words)
    return deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])


def generate_references(request: GenerateRequest, style: str) -> list[str]:
    """阶段5：生成参考文献（字符串列表，标注需人工核验）。"""
    user = _prompt("reference_generate.txt").format(
        title=request.title, major=request.major, style=style)
    text = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])
    refs = []
    for line in text.splitlines():
        line = re.sub(r"^\s*\[\d+\]\s*", "", line).strip()
        if line:
            refs.append(line)
    return refs[:12]


def check_paper(request: GenerateRequest, full_text: str) -> dict:
    """阶段6：全文检查（逻辑/重复/字数/格式）。"""
    user = _prompt("paper_check.txt").format(
        title=request.title, full_text=full_text[:12000])
    text = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])
    data = _extract_json(text) or {}
    return {
        "problems": data.get("problems") or [],
        "suggestions": data.get("suggestions") or [],
    }


def _parse_full_body(body: str) -> list[dict]:
    """把单次生成模式的正文章节文本解析为 chapters（含 blocks）。"""
    chapters: list[dict] = []
    current: dict | None = None
    buffer: list[str] = []
    chapter_re = re.compile(
        r"^(第[一二三四五六七八九十百\d]+章\s*\S.*|\d+[、.．]\s*\S.*)$")
    for line in body.splitlines():
        stripped = line.strip()
        if chapter_re.match(stripped):
            if current is not None:
                current["blocks"] = _parse_chapter("\n".join(buffer))
                chapters.append(current)
            current = {"id": f"ch{len(chapters) + 1}", "title": stripped,
                       "level": 1, "blocks": []}
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        current["blocks"] = _parse_chapter("\n".join(buffer))
        chapters.append(current)
    return chapters


def generate_full_paper(request: GenerateRequest) -> dict:
    """single 策略：一次调用生成整篇论文（测试用）。"""
    plan = _chapter_plan(request)
    outline = "\n".join(
        f"{ch['title']}" for ch in plan if ch["level"] == 1)
    user = _prompt("full_paper_generate.txt").format(
        title=request.title, major=request.major,
        paper_type=request.paper_type, word_count=request.word_count,
        special_requirements=(request.special_requirements or "").strip() or "无",
        outline=outline)
    text = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])

    def section(marker: str) -> str:
        m = re.search(re.escape(marker) + r"\s*(.*?)(?=\n【|\Z)", text, re.S)
        return m.group(1).strip() if m else ""

    abstract_text = section("【摘要】")
    keywords_text = section("【关键词】")
    body = section("【正文】")
    refs_text = section("【参考文献】")
    abstract, keywords = _parse_abstract(
        abstract_text, _default_keywords(request.title, request.major))
    if keywords_text:
        keywords = [k.strip() for k in re.split(r"[；;，,]", keywords_text)
                    if k.strip()][:5] or keywords
    chapters = _parse_full_body(body)
    references = [re.sub(r"^\s*\[\d+\]\s*", "", ln).strip()
                  for ln in refs_text.splitlines() if ln.strip()]
    if not chapters:
        raise deepseek.DeepSeekModelError("整篇生成输出解析失败，请重试")
    return {
        "abstract": abstract or "（摘要生成失败，请重试）",
        "keywords": keywords,
        "chapters": chapters,
        "references": references,
    }


def _chapter_plan(request: GenerateRequest) -> list[dict]:
    """返回章节计划：[{title, level, words}]（一级章节分配字数）。"""
    if request.generation_mode == "outline" and (request.outline or "").strip():
        chapters = outline_service.parse_outline(request.outline or "")
        tops = [c for c in chapters if c["level"] == 1] or chapters
    else:
        tops = [{"title": t, "level": 1}
                for t in OUTLINES.get(request.paper_type, OUTLINES["课程论文"])]
        chapters = tops
    alloc = outline_service.allocate_words(len(tops), request.word_count)
    top_index = -1
    plan: list[dict] = []
    for ch in chapters:
        if ch["level"] == 1:
            top_index += 1
            ch["words"] = alloc[min(top_index, len(alloc) - 1)] if alloc else 0
        else:
            ch["words"] = 0
        plan.append(ch)
    return plan


def _parse_abstract(text: str, fallback: list[str]) -> tuple[str, list[str]]:
    keywords = fallback
    m = re.search(r"关键词[：:]\s*(.+)", text)
    if m:
        parsed = [k.strip() for k in re.split(r"[；;，,]", m.group(1)) if k.strip()]
        if parsed:
            keywords = parsed[:5]
    abstract = re.sub(r"关键词[：:].*", "", text, flags=re.S).strip()
    abstract = re.sub(r"^摘要[：:]", "", abstract).strip()
    return abstract, keywords


def _parse_chapter(text: str) -> list[dict]:
    """把模型输出的章节文本解析为 blocks（h2/h3/p）。"""
    blocks: list[dict] = []
    paragraph: list[str] = []

    def flush():
        if paragraph:
            blocks.append({"type": "p", "text": "".join(paragraph)})
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("### "):
            flush()
            blocks.append({"type": "h3", "text": line[4:].strip()})
        elif line.startswith("## "):
            flush()
            blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("# "):
            flush()
            blocks.append({"type": "h2", "text": line[2:].strip()})
        else:
            paragraph.append(line)
    flush()
    return blocks


def generate_paper_content(
    request: GenerateRequest,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """调用 DeepSeek 生成摘要/关键词与各章节正文，返回 spec 内容。"""
    title = request.title
    major = request.major
    requirement = (request.special_requirements or "").strip() or "无"
    system = system_prompt()
    plan = _chapter_plan(request)

    if on_progress:
        on_progress("正在生成摘要...")
    abstract_prompt = _prompt("abstract_generate.txt").format(
        title=title, major=major, paper_type=request.paper_type,
        special_requirements=requirement)
    abstract_text = deepseek.chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": abstract_prompt}])
    abstract, keywords = _parse_abstract(abstract_text,
                                         _default_keywords(title, major))

    sections: list[dict] = []
    chapter_prompt_tpl = _prompt("chapter_generate.txt")
    for i, ch in enumerate(plan):
        label = ch["title"]
        if ch["level"] == 1:
            if on_progress:
                on_progress(f"正在生成第{i + 1}章：{label}...")
            user = chapter_prompt_tpl.format(
                title=title, major=major, paper_type=request.paper_type,
                chapter_title=label, chapter_words=ch.get("words", 0),
                special_requirements=requirement)
            content = deepseek.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}])
            sections.append({"type": "h1", "text": label})
            sections.extend(_parse_chapter(content))
        else:
            # 大纲模式的小节标题（内容由一级章节生成）
            sections.append({"type": f"h{min(3, ch['level'])}",
                             "text": label})

    return {
        "abstract": abstract or "（摘要生成失败，请重试）",
        "keywords": keywords,
        "sections": sections,
    }


def generate_outline(title: str, major: str, paper_type: str,
                     word_count: int) -> dict:
    """调用 DeepSeek 生成论文大纲。"""
    user = _prompt("outline_generate.txt").format(
        title=title, major=major, paper_type=paper_type, word_count=word_count)
    content = deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])
    outline = content.strip()
    data = _extract_json(content)
    if isinstance(data, dict):
        outline_text = (
            data.get("outline_text") or data.get("outline") or ""
        ).strip()
        if outline_text:
            outline = outline_text
        elif isinstance(data.get("chapters"), list):
            titles = [
                ch.get("title") for ch in data["chapters"]
                if isinstance(ch, dict) and ch.get("title")
            ]
            if titles:
                outline = "\n".join(titles)
    chapters = outline_service.parse_outline(outline)
    tops = [c for c in chapters if c["level"] == 1] or chapters
    alloc = outline_service.allocate_words(len(tops), word_count)
    top_index = -1
    out_chapters = []
    for ch in chapters:
        if ch["level"] == 1:
            top_index += 1
            words = alloc[min(top_index, len(alloc) - 1)] if alloc else 0
        else:
            words = 0
        out_chapters.append({"title": ch["title"], "level": ch["level"],
                             "word_count": words})
    return {"outline": outline, "chapters": out_chapters}


def revise_chapter(title: str, major: str, chapter_title: str,
                   current_text: str, change_type: str,
                   instruction: str) -> str:
    """调用 DeepSeek 修改整章，返回修改后的章节文本。"""
    user = _prompt("revision.txt").format(
        title=title, major=major, change_type=change_type,
        instruction=instruction,
        context=f"当前章节：{chapter_title}\n当前章节内容：\n{current_text}")
    return deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])


def revise_paragraph(title: str, major: str, paragraph_text: str,
                     change_type: str, instruction: str) -> str:
    """调用 DeepSeek 修改单个段落，返回修改后的段落文本。"""
    user = _prompt("revision.txt").format(
        title=title, major=major, change_type=change_type,
        instruction=instruction,
        context=f"当前段落内容：\n{paragraph_text}")
    return deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])


_POLISH_LABELS = {
    "polish": "润色",
    "expand": "扩写",
    "condense": "缩写",
    "rewrite": "修改",
    "translate": "翻译",
}


def polish_text(text: str, operation: str, instruction: str) -> str:
    """对用户粘贴的文本进行润色/扩写/缩写/修改/翻译等处理。"""
    label = _POLISH_LABELS.get(operation, "润色")
    user = _prompt("polish.txt").format(
        operation_label=label,
        instruction=instruction.strip() or "无",
        text=text)
    return deepseek.chat(
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": user}])


def example_references(title: str, major: str) -> list[dict]:
    return make_example_refs(title, major)
