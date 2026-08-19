"""Structured editable table blocks for the draft editor."""
from __future__ import annotations

from typing import Any

_MAX_TABLE_ROWS = 100
_MAX_TABLE_COLS = 12


def _clean_headers(headers: list[Any]) -> list[str]:
    result = [str(item).strip() for item in headers if str(item).strip()]
    if not result:
        raise ValueError("表格至少需要一个非空表头。")
    if len(result) > _MAX_TABLE_COLS:
        raise ValueError(f"表格最多支持 {_MAX_TABLE_COLS} 列。")
    return result


def _clean_rows(rows: list[Any], width: int) -> list[list[str]]:
    if len(rows) > _MAX_TABLE_ROWS:
        raise ValueError(f"表格最多支持 {_MAX_TABLE_ROWS} 行。")
    cleaned: list[list[str]] = []
    for row in rows:
        values = list(row) if isinstance(row, list) else []
        cleaned.append([str(values[index]).strip() if index < len(values) else "" for index in range(width)])
    return cleaned


def add_table(service: Any, section_id: str, title: str, headers: list[Any], rows: list[Any]) -> dict:
    headers_clean = _clean_headers(headers)
    with service.lock:
        draft = service.load()
        section = service._find_section(draft, section_id)
        block = {
            "id": service._next_paragraph_id(section),
            "type": "table",
            "title": str(title).strip() or "数据表",
            "headers": headers_clean,
            "rows": _clean_rows(rows, len(headers_clean)),
        }
        section["paragraphs"].append(block)
        service.save(draft)
        return block


def update_block(service: Any, block_id: str, patch: dict[str, Any]) -> dict:
    with service.lock:
        draft = service.load()
        for section in draft["sections"]:
            for block in section["paragraphs"]:
                if block.get("id") != block_id:
                    continue
                if block.get("type", "paragraph") == "table":
                    headers = _clean_headers(patch.get("headers", block.get("headers", [])))
                    block["headers"] = headers
                    block["rows"] = _clean_rows(patch.get("rows", block.get("rows", [])), len(headers))
                    if "title" in patch:
                        block["title"] = str(patch["title"]).strip() or "数据表"
                elif "text" in patch:
                    block["text"] = str(patch["text"])
                service.save(draft)
                return block
    raise ValueError(f"内容块不存在: {block_id}")
