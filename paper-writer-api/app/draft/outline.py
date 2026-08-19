"""草稿大纲构建：三级结构（章→节→小节）+ 每叶节点段落主旨。

AI 生成优先，失败时回退到内置模板（OUTLINES + SUB_TEMPLATES），
保证无模型配置时编辑器也能出可用大纲。
"""

from __future__ import annotations

import json
import logging
import re

from app.services import deepseek, deepseek_service
from app.services.outline_service import (
    OUTLINES,
    SUB_TEMPLATES,
)
from app.draft.outline_quality import evaluate_outline

#: fallback 子章节补充：SUB_TEMPLATES 以精确 key 匹配，"文献综述与理论基础"
#: 无法命中 "文献综述"，这里补全毕业论文第二章的子章节模板。
SUB_TEMPLATES_EXTRA: dict[str, list[str]] = {
    "文献综述与理论基础": ["国内外研究现状", "相关理论基础", "研究述评"],
}


def _sub_chapters_for(title: str) -> list[str]:
    """为章节名匹配子章节模板：先精确匹配，再按关键词长度降序做包含匹配。

    安全模糊匹配规则：章节名**包含**模板关键词即命中（如
    "文献综述与理论基础" 包含 "文献综述"）；多个候选时取关键词最长的
    （避免短关键词如 "方法" 抢先匹配 "研究方法"）。
    """
    merged = {**SUB_TEMPLATES, **SUB_TEMPLATES_EXTRA}
    exact = merged.get(title)
    if exact:
        return exact
    for key in sorted(merged, key=len, reverse=True):
        if key in title:
            return merged[key]
    return ["主要内容概述", "重点问题分析"]

logger = logging.getLogger(__name__)

#: 大纲生成使用的 token 上限（三级大纲 + 每叶 gist 的 JSON 较长，
#: 4000 容易被截断导致解析失败，调整到 8000）。
OUTLINE_MAX_TOKENS = 8000

CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _prompt(name: str) -> str:
    return (deepseek_service.settings.prompts_dir / name).read_text(encoding="utf-8")


def _extract_json(text: str) -> tuple[dict | None, str | None]:
    """提取模型输出中的 JSON，返回 ``(data, error)``。

    兼容模型常见的四种输出形式：
    - 纯 JSON 对象；
    - ```json ... ``` 代码块包裹；
    - JSON 前后夹带说明文字；
    - 首个 JSON 对象后又夹带第二段 JSON、诊断或说明文字。

    :return: 解析成功时 ``(dict, None)``；失败时 ``(None, 原因字符串)``。
    """
    if not text or not text.strip():
        return None, "模型输出为空"
    content = text.strip()
    # 1) 剥离 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if m:
        content = m.group(1).strip()

    # 2) 从每个可能的 JSON 起点尝试 raw_decode。它只消费一个完整值，
    # 因此不会把首个对象与后续诊断 JSON 贪婪拼接为无效内容。
    decoder = json.JSONDecoder()
    last_error: str | None = None
    found_json = False
    for index, char in enumerate(content):
        if char not in "{[":
            continue
        try:
            data, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            continue
        found_json = True
        if isinstance(data, dict):
            return data, None
        last_error = f"JSON 顶层不是对象（实际: {type(data).__name__}）"

    if not found_json:
        return None, "输出中未找到可解析的 JSON 对象/数组"
    return None, f"JSON 解析失败: {last_error or '未找到 JSON 对象'}"


def _flatten(node: dict, parent: str, idx: int, out: list[dict]) -> None:
    """把嵌套 sections 展开成扁平列表（id/number/level/title/gist/paragraphs）。"""
    level = int(node.get("level") or 1)
    title = (node.get("title") or "").strip() or f"章节{idx}"
    if level == 1:
        # idx 从 0 开始，一级章节编号应为 idx + 1（第一章 → “第一章”）；
        # 超过 CN_NUM 长度时回退阿拉伯数字
        chapter_num = idx + 1
        number = f"第{CN_NUM[chapter_num] if chapter_num < len(CN_NUM) else chapter_num}章"
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


def _ai_outline(paper_info: dict) -> tuple[list[dict] | None, str | None]:
    """调用 AI 生成三级大纲，返回 ``(flat, error)``。

    ``error`` 非 None 表示生成/解析失败（原因字符串），此时 ``flat`` 为 None。
    """
    references = paper_info.get("references") or []
    ref_text = "\n".join(f"[{index + 1}] {item}" for index, item in enumerate(references[:20])) or "（未选择参考文献）"
    user = _prompt("draft_outline.txt").format(
        title=paper_info.get("title", ""),
        major=paper_info.get("major", ""),
        paper_type=paper_info.get("paper_type", "课程论文"),
        word_count=paper_info.get("word_count", 3000),
        abstract=(paper_info.get("abstract") or "").strip() or "（未提供摘要）",
        special_requirements=(paper_info.get("special_requirements") or "").strip() or "无",
        keywords="、".join(paper_info.get("keywords") or []) or "（由大纲生成）",
        references=ref_text,
    )
    content = deepseek.chat(
        [{"role": "system", "content": deepseek_service.system_prompt()},
         {"role": "user", "content": user}],
        max_tokens=OUTLINE_MAX_TOKENS)
    data, err = _extract_json(content)
    if err:
        return None, err
    if not data.get("sections"):
        return None, "JSON 中缺少 sections 字段"
    flat: list[dict] = []
    for i, ch in enumerate(data["sections"]):
        _flatten(ch, "", i, flat)
    if not flat:
        return None, "sections 展开后为空"
    return flat, None


def _fallback_outline(paper_info: dict) -> list[dict]:
    """无模型时的确定性大纲：内置章模板 + 小节模板，gist 用章节 focus。"""
    paper_type = paper_info.get("paper_type", "课程论文")
    titles = OUTLINES.get(paper_type, OUTLINES["课程论文"])
    flat: list[dict] = []
    for i, t in enumerate(titles):
        name = t.split(" ", 1)[-1] if " " in t else t
        sid = str(i + 1)
        number = f"第{CN_NUM[i + 1] if i + 1 < len(CN_NUM) else i + 1}章"
        flat.append({"id": sid, "number": number, "title": name,
                     "level": 1, "gist": "", "paragraphs": [], "children": []})
        subs = _sub_chapters_for(name)
        for j, sub in enumerate(subs):
            flat.append({"id": f"{sid}-{j + 1}", "number": f"{i + 1}.{j + 1}",
                         "title": sub, "level": 2, "gist": f"围绕“{sub}”展开论述",
                         "paragraphs": [], "children": []})
    return flat


def build_outline_with_meta(paper_info: dict, version: int = 1) -> tuple[list[dict], dict]:
    """构建大纲并记录来源、回退原因与可解释质量诊断。"""
    fallback_reason: str | None = None
    if deepseek.is_enabled():
        try:
            flat, err = _ai_outline(paper_info)
        except Exception as exc:  # noqa: BLE001 - 调用/网络异常统一走回退
            logger.warning("AI 大纲生成异常，进入 fallback：原因=%s", exc)
            flat, err = None, str(exc)
        if flat is not None:
            logger.info("AI 大纲生成成功：章节数量=%d", len(flat))
            return flat, evaluate_outline(paper_info, flat, source="ai", version=version)
        fallback_reason = err or "模型输出无法解析为合格的 JSON 大纲"
        logger.warning("AI 大纲解析失败，进入 fallback：原因=%s", fallback_reason)
    else:
        fallback_reason = "未配置可用模型，使用内置模板大纲"
        logger.info(fallback_reason)
    flat = _fallback_outline(paper_info)
    return flat, evaluate_outline(
        paper_info, flat, source="fallback", fallback_reason=fallback_reason, version=version,
    )


def build_outline(paper_info: dict) -> list[dict]:
    """兼容旧调用方：仅返回大纲结构。"""
    return build_outline_with_meta(paper_info)[0]


def outline_text(flat: list[dict]) -> str:
    """把扁平大纲渲染为纯文本（用于生成段落时的完整大纲上下文）。"""
    lines: list[str] = []
    for s in flat:
        indent = "  " * (s["level"] - 1)
        lines.append(f"{indent}{s['number']} {s['title']}")
    return "\n".join(lines)
