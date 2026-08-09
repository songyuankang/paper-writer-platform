"""草稿大纲构建：三级结构（章→节→小节）+ 每叶节点段落主旨。

AI 生成优先，失败时回退到内置模板（OUTLINES + SUB_TEMPLATES），
保证无模型配置时编辑器也能出可用大纲。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.generate import GenerateRequest
from app.services import deepseek, deepseek_service
from app.services.outline_service import OUTLINES, SUB_TEMPLATES, allocate_words

CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _prompt(name: str) -> str:
    return (deepseek_service.settings.prompts_dir / name).read_text(encoding="utf-8")


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _flatten(node: dict, parent: str, idx: int, out: list[dict]) -> None:
    """把嵌套 sections 展开成扁平列表（id/number/level/title/gist/paragraphs）。"""
    level = int(node.get("level") or 1)
    title = (node.get("title") or "").strip() or f"章节{idx}"
    if level == 1:
        number = f"第{CN_NUM[idx] if idx < len(CN_NUM) else idx + 1}章"
    else:
        number = f"{parent}.{idx + 1}" if parent else str(idx + 1)
    sid = f"{parent}-{idx + 1}" if parent else str(idx + 1)
    gist = (node.get("gist") or "").strip()
    children = node.get("children") or []
    out.append({
        "id": sid,
        "number": number,
        "title": title,
        "level": level,
        "gist": gist,
        "paragraphs": [],
        "children": children,  # 仅用于判断叶子
    })
    for i, ch in enumerate(children):
        _flatten(ch, sid, i, out)


def _ai_outline(paper_info: dict) -> list[dict] | None:
    user = _prompt("draft_outline.txt").format(
        title=paper_info.get("title", ""),
        major=paper_info.get("major", ""),
        paper_type=paper_info.get("paper_type", "课程论文"),
        word_count=paper_info.get("word_count", 3000),
        special_requirements=(paper_info.get("special_requirements") or "").strip() or "无",
        keywords="、".join(paper_info.get("keywords") or []) or "（由大纲生成）",
    )
    content = deepseek.chat(
        [{"role": "system", "content": deepseek_service.system_prompt()},
         {"role": "user", "content": user}])
    data = _extract_json(content)
    if not data or not data.get("sections"):
        return None
    flat: list[dict] = []
    for i, ch in enumerate(data["sections"]):
        _flatten(ch, "", i, flat)
    return flat


def _fallback_outline(paper_info: dict) -> list[dict]:
    """无模型时的确定性大纲：内置章模板 + 小节模板，gist 用章节 focus。"""
    paper_type = paper_info.get("paper_type", "课程论文")
    titles = OUTLINES.get(paper_type, OUTLINES["课程论文"])
    alloc = allocate_words(len(titles), paper_info.get("word_count", 3000))
    flat: list[dict] = []
    for i, t in enumerate(titles):
        name = t.split(" ", 1)[-1] if " " in t else t
        sid = str(i + 1)
        number = f"第{CN_NUM[i + 1] if i + 1 < len(CN_NUM) else i + 1}章"
        flat.append({"id": sid, "number": number, "title": name,
                     "level": 1, "gist": "", "paragraphs": [], "children": []})
        subs = SUB_TEMPLATES.get(name) or SUB_TEMPLATES.get(name.replace("与", "与"), [])
        for j, sub in enumerate(subs):
            flat.append({"id": f"{sid}-{j + 1}", "number": f"{i + 1}.{j + 1}",
                         "title": sub, "level": 2, "gist": f"围绕“{sub}”展开论述",
                         "paragraphs": [], "children": []})
    return flat


def build_outline(paper_info: dict) -> list[dict]:
    """构建三级大纲（扁平列表）。AI 失败回退模板。"""
    if deepseek.is_enabled():
        try:
            flat = _ai_outline(paper_info)
            if flat:
                return flat
        except Exception:  # noqa: BLE001
            pass
    return _fallback_outline(paper_info)


def outline_text(flat: list[dict]) -> str:
    """把扁平大纲渲染为纯文本（用于生成段落时的完整大纲上下文）。"""
    lines: list[str] = []
    for s in flat:
        indent = "  " * (s["level"] - 1)
        lines.append(f"{indent}{s['number']} {s['title']}")
    return "\n".join(lines)
