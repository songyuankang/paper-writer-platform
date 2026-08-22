"""草稿大纲构建：统一 ``sections`` 契约、受控重试与安全回退预览。

AI 输出始终先规范化为内部大纲契约。无法生成合格 AI 大纲时仍可展示
确定性模板帮助用户理解编辑器结构，但该模板绝不具备启动全文生成的资格。
"""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import re
from typing import Any

from app.draft.outline_quality import evaluate_outline
from app.services import deepseek, deepseek_service
from app.services.outline_service import OUTLINES, SUB_TEMPLATES

SUB_TEMPLATES_EXTRA: dict[str, list[str]] = {
    "文献综述与理论基础": ["国内外研究现状", "相关理论基础", "研究述评"],
}

logger = logging.getLogger(__name__)
OUTLINE_MAX_TOKENS = 8000
OUTLINE_MAX_ATTEMPTS = 2
CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

# Prefer strict JSON Schema on providers that support it.  The request helper
# catches a 400 capability error and retries once without this parameter while
# retaining the same strict prompt and local canonical-schema validation.
OUTLINE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "draft_outline",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "research_paradigm": {"type": "string"},
                "sections": {"type": "array", "minItems": 4, "items": {"$ref": "#/$defs/root_section"}},
            },
            "required": ["title", "research_paradigm", "sections"],
            "additionalProperties": False,
            "$defs": {
                "root_section": {
                    "allOf": [
                        {"$ref": "#/$defs/section"},
                        {
                            "properties": {
                                "level": {"const": 1},
                                "children": {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/section"}},
                            }
                        }
                    ]
                },
                "section": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string"},
                        "number": {"type": "string"},
                        "title": {"type": "string"},
                        "level": {"type": "integer", "minimum": 1, "maximum": 3},
                        "purpose": {"type": "string"},
                        "children": {"type": "array", "items": {"$ref": "#/$defs/section"}},
                    },
                    "required": ["title", "level", "purpose", "children"],
                    "additionalProperties": False,
                }
            },
        },
    },
}
OUTLINE_ALIASES = ("sections", "outline", "chapters")


def _response_format_for(paper_info: dict[str, Any]) -> dict[str, Any]:
    """Keep strict graduation-thesis hierarchy constraints out of other paper types."""
    response_format = deepcopy(OUTLINE_RESPONSE_FORMAT)
    schema = response_format["json_schema"]["schema"]
    if "毕业" not in str(paper_info.get("paper_type") or ""):
        schema["properties"]["sections"]["minItems"] = 1
        schema["properties"]["sections"]["items"] = {"$ref": "#/$defs/section"}
    return response_format


def _sub_chapters_for(title: str) -> list[str]:
    """为章节名匹配确定性的预览模板子章节。"""
    merged = {**SUB_TEMPLATES, **SUB_TEMPLATES_EXTRA}
    if exact := merged.get(title):
        return exact
    for key in sorted(merged, key=len, reverse=True):
        if key in title:
            return merged[key]
    return ["主要内容概述", "重点问题分析"]


def _prompt(name: str) -> str:
    return (deepseek_service.settings.prompts_dir / name).read_text(encoding="utf-8")


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """安全提取模型输出中的第一个 JSON 对象，兼容 fenced JSON 与尾随文本。"""
    if not text or not text.strip():
        return None, "模型输出为空"
    content = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.S | re.I)
    if fenced:
        content = fenced.group(1).strip()

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
        return None, "输出中未找到可解析的 JSON 对象"
    return None, f"JSON 解析失败: {last_error or '未找到 JSON 对象'}"


def _canonical_section(
    node: Any,
    *,
    expected_level: int,
    require_children: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """规范化章节并拒绝毕业论文缺失的一级章节 children。"""
    if not isinstance(node, dict):
        return None, "sections 中存在非对象章节"
    title = str(node.get("title") or "").strip()
    if not title:
        return None, "sections 中存在缺少 title 的章节"

    raw_children = node.get("children")
    if raw_children is None:
        raw_children = node.get("sections", node.get("subsections", []))
    if raw_children is None:
        raw_children = []
    if not isinstance(raw_children, list):
        return None, f"章节「{title}」的 children 不是数组"

    raw_level = node.get("level")
    try:
        level = int(raw_level) if raw_level is not None else expected_level
    except (TypeError, ValueError):
        return None, f"章节「{title}」的 level 无效"
    if level < 1 or level > 3:
        return None, f"章节「{title}」的 level 必须在 1-3 之间"
    if level != expected_level:
        return None, f"章节「{title}」的 level 应为 {expected_level}，实际为 {level}"
    if require_children and len(raw_children) < 2:
        return None, f"毕业论文一级章节「{title}」至少需要 2 个二级小节 children"

    children: list[dict[str, Any]] = []
    for child in raw_children:
        normalized, error = _canonical_section(
            child,
            expected_level=min(level + 1, 3),
            require_children=False,
        )
        if error:
            return None, error
        assert normalized is not None
        children.append(normalized)

    return {
        "section_id": str(node.get("section_id") or node.get("id") or "").strip(),
        "number": str(node.get("number") or "").strip(),
        "title": title,
        "level": level,
        "purpose": str(node.get("purpose") or node.get("gist") or "").strip(),
        "children": children,
    }, None


def _normalize_outline_payload(
    data: dict[str, Any],
    *,
    paper_type: str = "",
) -> tuple[dict[str, Any] | None, str | None]:
    """兼容明确别名并对毕业论文强制非空二级 children。"""
    raw_sections: Any = None
    matched_alias: str | None = None
    for alias in OUTLINE_ALIASES:
        candidate = data.get(alias)
        if candidate is not None:
            raw_sections = candidate
            matched_alias = alias
            break
    if not isinstance(raw_sections, list) or not raw_sections:
        aliases = " / ".join(OUTLINE_ALIASES)
        return None, f"JSON 中缺少非空 {aliases} 数组"

    is_graduation_thesis = "毕业" in paper_type
    if is_graduation_thesis and len(raw_sections) < 4:
        return None, "毕业论文至少需要 4 个一级章节"

    sections: list[dict[str, Any]] = []
    for node in raw_sections:
        normalized, error = _canonical_section(
            node,
            expected_level=1,
            require_children=is_graduation_thesis,
        )
        if error:
            return None, error
        assert normalized is not None
        sections.append(normalized)

    return {
        "title": str(data.get("title") or "").strip(),
        "research_paradigm": str(data.get("research_paradigm") or data.get("research_type") or "").strip(),
        "sections": sections,
        "normalized_from": matched_alias,
    }, None


def _flatten(node: dict[str, Any], parent: str, idx: int, out: list[dict[str, Any]]) -> None:
    """把 canonical nested sections 展开为草稿编辑器的扁平章节列表。"""
    level = int(node.get("level") or 1)
    title = str(node.get("title") or "").strip() or f"章节{idx + 1}"
    if level == 1:
        chapter_num = idx + 1
        number = f"第{CN_NUM[chapter_num] if chapter_num < len(CN_NUM) else chapter_num}章"
    else:
        number = f"{parent.replace('-', '.')}.{idx + 1}" if parent else str(idx + 1)
    sid = f"{parent}-{idx + 1}" if parent else str(idx + 1)
    children = list(node.get("children") or [])
    out.append({
        "id": sid,
        "number": number,
        "title": title,
        "level": level,
        "gist": str(node.get("purpose") or "").strip(),
        "paragraphs": [],
        "children": children,
    })
    for child_index, child in enumerate(children):
        _flatten(child, sid, child_index, out)


def _outline_user_prompt(paper_info: dict[str, Any], retry_reason: str | None = None) -> str:
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
    if retry_reason:
        user += (
            "\n\n上一轮输出不符合大纲 JSON 契约，原因：" + retry_reason + "。"
            "请重新生成。只能返回一个 JSON 对象；不要 Markdown、解释或代码围栏。"
            "顶层必须有 sections 数组，每个章节必须包含 title、level、purpose、children。"
            "毕业论文必须有 4—6 个一级章节；每个一级章节必须至少包含 2 个 level=2 的 children。"
            "重要章节可继续使用 level=3 children 展开；不允许所有 children 为空，也不允许只返回章节标题列表。"
        )
    return user


def _request_ai_outline(paper_info: dict[str, Any], retry_reason: str | None = None) -> str:
    messages = [
        {"role": "system", "content": deepseek_service.system_prompt()},
        {"role": "user", "content": _outline_user_prompt(paper_info, retry_reason)},
    ]
    try:
        return deepseek.chat(
            messages,
            max_tokens=OUTLINE_MAX_TOKENS,
            response_format=_response_format_for(paper_info),
        )
    except deepseek.DeepSeekModelError as exc:
        # A minority of OpenAI-compatible endpoints do not implement response_format.
        # Continue with the same strict prompt and local schema validation instead of
        # broadening the output contract or silently accepting malformed content.
        logger.info("当前模型不支持 response_format，改用本地 schema 兼容层：%s", exc)
        return deepseek.chat(messages, max_tokens=OUTLINE_MAX_TOKENS)


def _ai_outline(paper_info: dict[str, Any], retry_reason: str | None = None) -> tuple[list[dict[str, Any]] | None, str | None]:
    """调用 AI 并将其输出解析为 canonical sections 后的编辑器列表。"""
    content = _request_ai_outline(paper_info, retry_reason)
    data, error = _extract_json(content)
    if error:
        return None, error
    assert data is not None
    canonical, error = _normalize_outline_payload(
        data,
        paper_type=str(paper_info.get("paper_type") or ""),
    )
    if error:
        return None, error
    assert canonical is not None
    flat: list[dict[str, Any]] = []
    for index, section in enumerate(canonical["sections"]):
        _flatten(section, "", index, flat)
    if not flat:
        return None, "sections 展开后为空"
    return flat, None


def _fallback_outline(paper_info: dict[str, Any]) -> list[dict[str, Any]]:
    """仅用于 UI 预览的确定性通用结构，绝不作为全文生成输入。"""
    paper_type = paper_info.get("paper_type", "课程论文")
    titles = OUTLINES.get(paper_type, OUTLINES["课程论文"])
    flat: list[dict[str, Any]] = []
    for index, title in enumerate(titles):
        name = title.split(" ", 1)[-1] if " " in title else title
        sid = str(index + 1)
        number = f"第{CN_NUM[index + 1] if index + 1 < len(CN_NUM) else index + 1}章"
        flat.append({"id": sid, "number": number, "title": name,
                     "level": 1, "gist": "", "paragraphs": [], "children": []})
        for child_index, child_title in enumerate(_sub_chapters_for(name)):
            flat.append({"id": f"{sid}-{child_index + 1}", "number": f"{index + 1}.{child_index + 1}",
                         "title": child_title, "level": 2,
                         "gist": f"围绕“{child_title}”展开论述",
                         "paragraphs": [], "children": []})
    return flat


def build_outline_with_meta(paper_info: dict[str, Any], version: int = 1) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """构建大纲；AI 失败仅重试一次，随后返回被质量门禁标记的预览模板。"""
    last_error: str | None = None
    if deepseek.is_enabled():
        for attempt in range(1, OUTLINE_MAX_ATTEMPTS + 1):
            try:
                flat, error = _ai_outline(paper_info, retry_reason=last_error if attempt > 1 else None)
            except Exception as exc:  # noqa: BLE001 - normalized into a controlled retry reason
                flat, error = None, f"{type(exc).__name__}: {exc}"
            if flat is not None:
                meta = evaluate_outline(paper_info, flat, source="ai", version=version)
                if meta.get("hierarchy_valid"):
                    logger.info("AI 大纲生成成功：attempt=%d sections=%d", attempt, len(flat))
                    meta["generation_attempts"] = attempt
                    meta["last_generation_error"] = None
                    return flat, meta
                error = "；".join(meta.get("block_reasons") or []) or "大纲层级不足"
            last_error = error or "模型输出无法解析为合格 JSON 大纲"
            logger.warning("AI 大纲生成 attempt=%d 失败：%s", attempt, last_error)
    else:
        last_error = "未配置可用模型，当前仅显示通用模板预览"
        logger.info(last_error)

    flat = _fallback_outline(paper_info)
    meta = evaluate_outline(
        paper_info,
        flat,
        source="fallback",
        fallback_reason=last_error,
        version=version,
    )
    meta["generation_attempts"] = OUTLINE_MAX_ATTEMPTS if deepseek.is_enabled() else 0
    meta["last_generation_error"] = last_error
    return flat, meta


def build_outline(paper_info: dict[str, Any]) -> list[dict[str, Any]]:
    """兼容旧调用方：仅返回大纲结构。"""
    return build_outline_with_meta(paper_info)[0]


def outline_text(flat: list[dict[str, Any]]) -> str:
    """把扁平大纲渲染为正文生成上下文。"""
    lines: list[str] = []
    for section in flat:
        indent = "  " * (int(section["level"]) - 1)
        lines.append(f"{indent}{section['number']} {section['title']}")
    return "\n".join(lines)
