"""论文修改：章节/段落修改、全文分析、版本管理与 docx 重建。

当前为规则化示例实现（修改内容明确标注【修改示例】），正式版可替换为 LLM 生成。
每次修改保存一个新版本，重建为 paper_vN.docx，不覆盖原始 论文.docx。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from docx import Document

from app.config import settings
from app.db import get_conn
from app.services import deepseek, deepseek_service
from app.services import model_service

logger = logging.getLogger(__name__)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
ENGINE = {"mods": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _engine():
    if ENGINE["mods"] is None:
        scripts = settings.paper_writer_scripts_dir
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import build_docx  # noqa: F401
        import parse_template  # noqa: F401
        ENGINE["mods"] = (build_docx, parse_template)
    return ENGINE["mods"]


# ------------------------------------------------------------------ 内容模型

def _content_path(task_dir: Path) -> Path:
    return task_dir / "content.json"


def spec_to_content(spec: dict) -> dict:
    chapters: list[dict] = []
    current: dict | None = None
    for item in spec.get("sections", []):
        t = item.get("type")
        if t == "h1":
            current = {
                "id": f"ch{len(chapters) + 1}",
                "title": item.get("text", ""),
                "level": 1,
                "blocks": [],
            }
            chapters.append(current)
        elif current is not None:
            blocks = current["blocks"]
            if t == "p":
                pn = sum(1 for b in blocks if b["type"] == "p") + 1
                blocks.append({"id": f"{current['id']}-p{pn}", "type": "p",
                               "text": item.get("text", "")})
            elif t in ("h2", "h3"):
                blocks.append({"id": f"{current['id']}-b{len(blocks) + 1}",
                               "type": t, "text": item.get("text", "")})
            elif t == "table":
                blocks.append({"id": f"{current['id']}-b{len(blocks) + 1}",
                               "type": "table", "title": item.get("title", ""),
                               "headers": item.get("headers", []),
                               "rows": item.get("rows", [])})
            elif t == "figure":
                blocks.append({"id": f"{current['id']}-b{len(blocks) + 1}",
                               "type": "figure", "path": item.get("path", ""),
                               "title": item.get("title", "")})
    references = []
    for item in spec.get("sections", []):
        if item.get("type") == "references":
            references = item.get("items", [])
    return {"meta": spec.get("meta", {}), "chapters": chapters,
            "references": references}


def content_to_spec(content: dict) -> dict:
    sections: list[dict] = []
    for ch in content.get("chapters", []):
        sections.append({"type": "h1", "text": ch.get("title", "")})
        for b in ch.get("blocks", []):
            t = b.get("type")
            if t == "p":
                sections.append({"type": "p", "text": b.get("text", "")})
            elif t in ("h2", "h3"):
                sections.append({"type": t, "text": b.get("text", "")})
            elif t == "table":
                sections.append({"type": "table", "title": b.get("title", ""),
                                 "headers": b.get("headers", []),
                                 "rows": b.get("rows", [])})
            elif t == "figure":
                sections.append({"type": "figure", "path": b.get("path", ""),
                                 "title": b.get("title", "")})
    sections.append({"type": "references",
                     "items": content.get("references", [])})
    return {"meta": content.get("meta", {}), "sections": sections}


def load_content(task_dir: Path) -> dict:
    path = _content_path(task_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    spec = json.loads((task_dir / "paper_spec.json").read_text(encoding="utf-8"))
    content = spec_to_content(spec)
    save_content(task_dir, content)
    return content


def save_content(task_dir: Path, content: dict) -> None:
    _content_path(task_dir).write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ 版本

def _ensure_initial_version(task_id: str, task_dir: Path) -> None:
    if list_versions(task_id):
        return
    content = load_content(task_dir)
    create_version(task_id, 1, "initial", "初始论文", content)


def create_version(task_id: str, version_number: int, change_type: str,
                   description: str, content: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO revision_versions
                (id, task_id, version_number, change_type, description,
                 created_at, content_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, task_id, version_number, change_type,
             description, _now(), json.dumps(content, ensure_ascii=False)),
        )


def list_versions(task_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, task_id, version_number, change_type, description, "
            "created_at FROM revision_versions WHERE task_id = ? "
            "ORDER BY version_number ASC",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_version(task_id: str, version_number: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM revision_versions WHERE task_id = ? AND version_number = ?",
            (task_id, version_number),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["content_snapshot"] = json.loads(record["content_snapshot"])
    return record


def next_version(task_id: str) -> int:
    versions = list_versions(task_id)
    return (versions[-1]["version_number"] + 1) if versions else 1


# ------------------------------------------------------------------ 修改操作

def _chapter_index(content: dict, chapter_id: str) -> int:
    chapters = content.get("chapters", [])
    if chapter_id.isdigit():
        idx = int(chapter_id) - 1
        if 0 <= idx < len(chapters):
            return idx
    for i, ch in enumerate(chapters):
        if ch.get("id") == chapter_id or str(i + 1) == chapter_id:
            return i
    raise ValueError(f"章节不存在: {chapter_id}")


def _placeholder_para(chapter_title: str, instruction: str, kind: str) -> str:
    return (
        f"（【修改示例·{kind}】围绕“{chapter_title}”，按修改要求"
        f"“{instruction}”生成的新内容占位，正式版由 LLM 生成。）"
    )


def _apply_chapter_blocks(ch, change_type: str, instruction: str) -> str:
    paras = [b for b in ch["blocks"] if b["type"] == "p"]
    label = {"regenerate": "重新生成本章", "expand": "扩展本章",
             "condense": "精简本章", "custom": "自定义修改"}.get(
        change_type, "修改本章")
    if change_type == "regenerate":
        for b in paras:
            b["text"] = _placeholder_para(ch["title"], instruction, "重新生成")
    elif change_type == "expand":
        for i in range(1, 3):
            paras.append({"id": f"{ch['id']}-p{len(paras) + i}",
                          "type": "p",
                          "text": _placeholder_para(ch["title"], instruction,
                                                    "扩展")})
        ch["blocks"].extend(paras[-2:])
    elif change_type == "condense":
        if len(paras) > 1:
            keep = paras[0]
            ch["blocks"] = [b for b in ch["blocks"] if b is keep]
    else:  # custom
        paras.append({"id": f"{ch['id']}-p{len(paras) + 1}", "type": "p",
                      "text": _placeholder_para(ch["title"], instruction,
                                                "自定义")})
        ch["blocks"].append(paras[-1])
    return label


def _find_paragraph(content: dict, paragraph_id: str):
    for ch in content.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("id") == paragraph_id:
                return ch, b
    raise ValueError(f"段落不存在: {paragraph_id}")


def _apply_paragraph_block(block: dict, change_type: str,
                           instruction: str) -> str:
    label = {"polish": "AI润色", "expand": "扩写", "rewrite": "改写",
             "delete": "删除段落"}.get(change_type, "修改段落")
    if change_type == "delete":
        return label
    text = block.get("text", "")
    if change_type == "polish":
        block["text"] = text + "（【AI润色示例】表达已优化，正式版由 LLM 生成）"
    elif change_type == "expand":
        block["text"] = text + (
            f"（【扩写示例】按“{instruction}”补充论述：该方面还可从更多维度"
            f"展开分析，正式版将扩充具体内容。）"
        )
    elif change_type == "rewrite":
        block["text"] = f"（【AI改写示例】按“{instruction}”改写）{text}"
    return label


def rebuild_docx(task_dir: Path, spec: dict, version_number: int) -> str:
    build_docx, parse_template = _engine()
    meta = spec.get("meta", {})
    out_name = f"paper_v{version_number}.docx"
    upload = settings.upload_dir / f"{task_dir.name}.docx"
    if upload.exists():
        profile = parse_template.parse_document(str(upload))
        doc = Document(str(upload))
        build_docx.build_with_template(doc, profile, spec, meta, task_dir)
    else:
        doc = build_docx.setup_document(meta)
        build_docx.build_default(doc, spec, meta, task_dir)
    doc.save(task_dir / out_name)
    return out_name


def apply_chapter_revision(task_id: str, task_dir: Path, chapter_id: str,
                           change_type: str, instruction: str,
                           model_id: str | None = None) -> dict:
    content = load_content(task_dir)
    idx = _chapter_index(content, chapter_id)
    ch = content["chapters"][idx]
    model_cfg = model_service.resolve_model(model_id, task_dir=task_dir)
    if model_cfg is not None:
        with deepseek.connection(model_cfg):
            try:
                current_text = "\n".join(
                    b.get("text", "") for b in ch["blocks"]
                    if b.get("type") in ("p", "h2", "h3"))
                meta = content.get("meta", {})
                new_text = deepseek_service.revise_chapter(
                    title=meta.get("title", ""), major=meta.get("major", ""),
                    chapter_title=ch["title"], current_text=current_text,
                    change_type=change_type, instruction=instruction)
                parsed = deepseek_service._parse_chapter(new_text)
                kept = [b for b in ch["blocks"]
                        if b.get("type") in ("table", "figure")]
                ch["blocks"] = parsed + kept
                description = (f"修改第{idx + 1}章（{ch['title']}）："
                               f"{_change_label(change_type)}（AI 模型）")
                return _commit(task_id, task_dir, content, change_type,
                               description)
            except deepseek.DeepSeekError as exc:
                logger.warning("AI 模型章节修改失败，回退规则修改: %s", exc)
    label = _apply_chapter_blocks(ch, change_type, instruction)
    description = f"修改第{idx + 1}章（{ch['title']}）：{label}"
    return _commit(task_id, task_dir, content, change_type, description)


def apply_paragraph_revision(task_id: str, task_dir: Path, paragraph_id: str,
                             change_type: str, instruction: str,
                             model_id: str | None = None) -> dict:
    content = load_content(task_dir)
    ch, block = _find_paragraph(content, paragraph_id)
    if change_type != "delete":
        model_cfg = model_service.resolve_model(model_id, task_dir=task_dir)
    else:
        model_cfg = None
    if model_cfg is not None:
        with deepseek.connection(model_cfg):
            try:
                meta = content.get("meta", {})
                new_text = deepseek_service.revise_paragraph(
                    title=meta.get("title", ""), major=meta.get("major", ""),
                    paragraph_text=block.get("text", ""),
                    change_type=change_type, instruction=instruction)
                block["text"] = new_text
                description = (f"{_change_label(change_type)}段落"
                               f"（{paragraph_id}）（AI 模型）")
                return _commit(task_id, task_dir, content, change_type,
                               description)
            except deepseek.DeepSeekError as exc:
                logger.warning("AI 模型段落修改失败，回退规则修改: %s", exc)
    label = _apply_paragraph_block(block, change_type, instruction)
    if change_type == "delete":
        ch["blocks"] = [b for b in ch["blocks"] if b.get("id") != paragraph_id]
    description = f"{label}段落（{paragraph_id}）"
    return _commit(task_id, task_dir, content, change_type, description)


def _change_label(change_type: str) -> str:
    return {"regenerate": "重新生成本章", "expand": "扩展本章",
            "condense": "精简本章", "custom": "自定义修改",
            "polish": "AI润色", "rewrite": "改写"}.get(change_type, change_type)


def _commit(task_id: str, task_dir: Path, content: dict, change_type: str,
            description: str) -> dict:
    save_content(task_dir, content)
    version = next_version(task_id)
    create_version(task_id, version, change_type, description, content)
    spec = content_to_spec(content)
    docx_file = rebuild_docx(task_dir, spec, version)
    return {
        "task_id": task_id,
        "version": version,
        "change_type": change_type,
        "description": description,
        "docx_file": docx_file,
        "preview_url": f"/api/preview/{task_id}",
    }


def analyze_paper(task_id: str, task_dir: Path) -> dict:
    content = load_content(task_dir)
    meta = content.get("meta", {})
    target = int(meta.get("word_count") or 0)
    all_text = ""
    chapter_words: list[tuple[str, int]] = []
    figures = 0
    placeholders = 0
    for ch in content.get("chapters", []):
        words = 0
        for b in ch.get("blocks", []):
            t = b.get("text", "")
            all_text += t
            words += len(CJK_RE.findall(t))
            if b.get("type") == "figure":
                figures += 1
            placeholders += t.count("【示例内容】") + t.count("【修改示例")
        chapter_words.append((ch.get("title", ""), words))
    total = len(CJK_RE.findall(all_text))

    problems: list[str] = []
    suggestions: list[str] = []
    if target and total < target * 0.8:
        problems.append(f"正文字数不足（当前约 {total} 字，目标 {target} 字）")
        suggestions.append("使用扩写/扩展章节补齐内容，或接入 LLM 生成完整正文")
    if placeholders:
        problems.append(f"全文包含 {placeholders} 处示例/修改占位内容，需替换为真实内容")
        suggestions.append("逐章替换占位内容；可对每章使用“重新生成本章”")
    if chapter_words:
        lengths = [w for _, w in chapter_words]
        if max(lengths) > 0 and max(lengths) / max(1, min(lengths)) > 3:
            problems.append("章节篇幅差异过大")
            suggestions.append("对篇幅过短的章节使用“扩展本章”，过长章节使用“精简本章”")
    if not content.get("references"):
        problems.append("缺少参考文献")
        suggestions.append("在生成页配置参考文献或导入 .bib 后重新生成")
    if figures == 0:
        suggestions.append("可在生成页开启图表生成，或为章节补充数据图表")
    if not problems:
        problems.append("未发现明显结构性问题（内容仍为示例占位，需人工审阅）")
    if not suggestions:
        suggestions.append("建议人工通读全文，并替换示例数据与示例文献")
    return {"problems": problems, "suggestions": suggestions,
            "word_count": total, "target_word_count": target,
            "chapter_words": chapter_words}


def restore_version(task_id: str, task_dir: Path, version_number: int) -> dict:
    version = get_version(task_id, version_number)
    if version is None:
        raise ValueError(f"版本不存在: {version_number}")
    content = version["content_snapshot"]
    save_content(task_dir, content)
    new_version = next_version(task_id)
    create_version(task_id, new_version, "restore",
                   f"恢复到版本 {version_number}", content)
    spec = content_to_spec(content)
    docx_file = rebuild_docx(task_dir, spec, new_version)
    return {
        "task_id": task_id,
        "version": new_version,
        "change_type": "restore",
        "description": f"恢复到版本 {version_number}",
        "docx_file": docx_file,
        "preview_url": f"/api/preview/{task_id}",
    }
