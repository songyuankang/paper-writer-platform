"""正文生成结果的阻断式质量校验。

该模块在任何模型输出写入 ``draft.json`` 之前运行。它只给出确定性
问题码与可审计的简短说明，不对文本进行猜测性修复。
"""
from __future__ import annotations

import re
from typing import Any


_MARKDOWN_HEADING = re.compile(r"(?P<heading>#{1,6}\s+[^\n#]{1,180})")
_CODE_FENCE = re.compile(r"```|~~~")
_DEBUG_MARKER = re.compile(r"(?i)(?:^|\s)(?:debug|reasoning|analysis)\s*:")
_JSON_FRAGMENT = re.compile(
    r"(?m)^\s*(?:\{\s*[\"'](?:title|sections|analysis|reasoning|content)[\"']\s*:|\[\s*\{\s*[\"'])"
)


class GeneratedBodyQualityError(ValueError):
    """模型正文不符合入库质量要求。"""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("；".join(str(item.get("message") or item.get("code")) for item in issues))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _repeated_phrase(compact: str, *, min_size: int = 12, max_size: int = 48, repeats: int = 3) -> str:
    """找出连续重复的非平凡短语，避免仅按单字符误报中文正文。"""
    if len(compact) < min_size * repeats:
        return ""
    upper = min(max_size, len(compact) // repeats)
    for size in range(upper, min_size - 1, -1):
        for start in range(0, len(compact) - size * repeats + 1):
            phrase = compact[start:start + size]
            if not phrase.strip() or len(set(phrase)) == 1:
                continue
            if all(compact.startswith(phrase, start + size * index) for index in range(1, repeats)):
                return phrase
    return ""


def evaluate_generated_body(text: str, *, target_chars: int | None = None) -> dict[str, Any]:
    """返回模型输出是否可安全持久化，以及所有确定性问题。

    阈值针对章节正文设置得较宽松：只有长度同时超过 3,000 字且超过目标
    字数四倍时才判为异常，避免误伤正常的多段正文。
    """
    raw = str(text or "")
    compact = _compact(raw)
    issues: list[dict[str, Any]] = []

    if not compact:
        issues.append({"code": "empty_body", "message": "模型未返回可用正文。"})
    headings = [match.group("heading").strip() for match in _MARKDOWN_HEADING.finditer(raw)]
    if headings:
        normalized = [re.sub(r"\s+", " ", value)[:180] for value in headings]
        duplicate_count = max(normalized.count(value) for value in set(normalized))
        issues.append({
            "code": "markdown_heading",
            "message": "正文包含 Markdown 标题标记。",
            "sample": normalized[0],
            "count": len(normalized),
        })
        if duplicate_count >= 3:
            repeated = next(value for value in normalized if normalized.count(value) == duplicate_count)
            issues.append({
                "code": "repeated_heading",
                "message": f"同一标题在单段内重复 {duplicate_count} 次。",
                "sample": repeated,
                "count": duplicate_count,
            })
    if _CODE_FENCE.search(raw):
        issues.append({"code": "code_fence", "message": "正文包含代码围栏标记。"})
    if _DEBUG_MARKER.search(raw):
        issues.append({"code": "debug_marker", "message": "正文包含 debug/reasoning/analysis 调试标记。"})
    if _JSON_FRAGMENT.search(raw):
        issues.append({"code": "json_fragment", "message": "正文包含疑似 JSON 结构残片。"})

    phrase = _repeated_phrase(compact)
    if phrase:
        issues.append({
            "code": "repeated_ngram",
            "message": "正文存在连续重复短语。",
            "sample": phrase,
            "count": 3,
        })

    if target_chars:
        maximum = max(3000, int(target_chars) * 4)
        if len(compact) > maximum:
            issues.append({
                "code": "abnormal_length",
                "message": f"正文长度 {len(compact)} 超过章节允许上限 {maximum}。",
                "count": len(compact),
                "limit": maximum,
            })

    return {"valid": not issues, "issues": issues, "char_count": len(compact)}


def assert_generated_body(text: str, *, target_chars: int | None = None) -> dict[str, Any]:
    """在持久化前执行质量校验；失败时抛出含问题码的异常。"""
    result = evaluate_generated_body(text, target_chars=target_chars)
    if not result["valid"]:
        raise GeneratedBodyQualityError(list(result["issues"]))
    return result
