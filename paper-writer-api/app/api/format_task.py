"""格式处理任务与学校模板接口（独立于论文内容生成）。"""

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings
from app.formatter import template_manager
from app.formatter.template import get_service as get_template_service
from app.formatter.format_task import format_manager
from app.models.format import FormatCreateRequest

router = APIRouter(prefix="/api/format", tags=["format"])


def _require_content_task(task_id: str) -> Path:
    task_dir = settings.output_dir / task_id
    if not task_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    has_content = (task_dir / "paper_content").is_dir() or \
        (task_dir / "paper_spec.json").exists()
    if not has_content:
        raise HTTPException(status_code=400, detail="任务没有论文内容，请先生成内容")
    return task_dir


@router.post("/create")
def create_format(req: FormatCreateRequest) -> dict:
    _require_content_task(req.task_id)
    format_id = format_manager.create(req.task_id, req.template_id, req.settings)
    return {"format_id": format_id, "status": "waiting"}


@router.post("/start/{format_id}")
def start_format(format_id: str) -> dict:
    if not format_manager.start(format_id):
        raise HTTPException(status_code=404, detail=f"格式任务不存在: {format_id}")
    return {"ok": True, "status": "processing"}


@router.get("/status/{format_id}")
def format_status(format_id: str) -> dict:
    record = format_manager.get(format_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"格式任务不存在: {format_id}")
    return record


@router.get("/download/{format_id}")
def download_format(format_id: str, file: str | None = None):
    record = format_manager.get(format_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"格式任务不存在: {format_id}")
    if record["status"] != "completed":
        raise HTTPException(status_code=409, detail="格式处理尚未完成")
    fdir = format_manager.formatted_dir(format_id)
    if fdir is None or not fdir.is_dir():
        raise HTTPException(status_code=404, detail="没有格式处理产物")
    if file is not None:
        target = (fdir / file).resolve()
        if not str(target).startswith(str(fdir.resolve())) or not target.is_file():
            raise HTTPException(status_code=404, detail=f"文件不存在: {file}")
        return FileResponse(target, filename=target.name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(fdir.iterdir()):
            if p.is_file():
                zf.write(p, arcname=f"formatted/{p.name}")
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=formatted_{format_id}.zip"})


@router.get("/templates")
def list_templates() -> dict:
    return {"templates": template_manager.list_templates()}


# ---------------------------------------------------------------------------
# DOCX 解析结果 → v2 模板结构化字段的映射（复用现有 v2 schema，
# 不改 TemplateService / TemplateValidator / TemplateRenderer）。
# ---------------------------------------------------------------------------

#: 解析器样式角色 → (block key, style role, keep_with_next)
_STYLE_ROLE_MAP = {
    "title_zh_direct": ("title_zh", "self", True),
    "heading1": ("heading1", "self", True),
    "heading2": ("heading2", "self", True),
    "heading3": ("heading3", "self", True),
    "body_direct": ("body", "self", False),
    "body": ("body", "self", False),
    "reference": ("references", "item", False),
}

#: python-docx 对齐枚举（str 形如 "CENTER (1)"）→ v2 alignment
_ALIGN_MAP = {
    "LEFT": "left",
    "CENTER": "center",
    "RIGHT": "right",
    "JUSTIFY": "justify",
    "DISTRIBUTE": "justify",
}

#: 常见纸张规格（宽 × 高，cm，容差 0.3cm）
_PAGE_SIZES_CM = [
    ("A3", (29.7, 42.0)),
    ("A4", (21.0, 29.7)),
    ("A5", (14.8, 21.0)),
    ("B4", (25.0, 35.3)),
    ("B5", (17.6, 25.0)),
    ("Letter", (21.59, 27.94)),
    ("Legal", (21.59, 35.56)),
]


def _detect_page_size(page: dict) -> str:
    """按解析出的纸张宽高识别规格，识别不出回退 A4。"""
    width = page.get("page_width_cm")
    height = page.get("page_height_cm")
    if width and height:
        for name, (pw, ph) in _PAGE_SIZES_CM:
            if abs(float(width) - pw) < 0.3 and abs(float(height) - ph) < 0.3:
                return name
    return "A4"


def _norm_alignment(value) -> str | None:
    """归一化 python-docx 对齐值（"CENTER (1)" → "center"）。"""
    if not value:
        return None
    key = str(value).split(" ")[0].upper()
    return _ALIGN_MAP.get(key)


def _font_family(style_font, default_font: dict) -> dict:
    """解析样式字体 + 文档默认字体 → v2 font_family。"""
    east_asia = None
    latin = None
    if isinstance(style_font, dict):
        east_asia = style_font.get("east_asia")
        latin = style_font.get("ascii") or style_font.get("h_ansi")
    if not east_asia:
        east_asia = default_font.get("east_asia") or default_font.get("h_ansi")
    if not latin:
        latin = default_font.get("ascii")
    return {
        "east_asia": east_asia or "宋体",
        "latin": latin or "Times New Roman",
    }


def _parsed_style_to_v2(parsed, default_font: dict) -> dict | None:
    """把解析器的单个样式（font + paragraph）转成 v2 TemplateStyle。"""
    if not isinstance(parsed, dict):
        return None
    font = parsed.get("font")
    para = parsed.get("paragraph")
    if not isinstance(font, dict) and not isinstance(para, dict):
        return None
    font = font if isinstance(font, dict) else {}
    para = para if isinstance(para, dict) else {}

    line = para.get("line_spacing")
    if line is None:
        mode, value = "multiple", 1.5
    else:
        line = float(line)
        if 0.5 <= line <= 3.0:
            mode, value = "multiple", line
        else:
            mode, value = "exact", line

    indent_pt = para.get("first_line_indent_pt")
    return {
        "font_family": _font_family(font, default_font),
        "font_size_pt": float(font.get("size_pt")
                               or default_font.get("size_pt") or 12.0),
        "bold": bool(font.get("bold")),
        "italic": False,
        "underline": False,
        "alignment": _norm_alignment(para.get("alignment")) or "left",
        "line_spacing": {"mode": mode, "value": value},
        "space_before_pt": float(para.get("space_before_pt") or 0),
        "space_after_pt": float(para.get("space_after_pt") or 0),
        "first_line_indent": {
            "unit": "pt" if indent_pt else "chars",
            "value": float(indent_pt or 0),
        },
        "keep_with_next": False,
        "page_break_before": False,
    }


def _apply_parsed_styles(blocks: list[dict], styles, default_font: dict) -> None:
    """把解析出的标题/正文/题注/参考文献样式合并进基础模板 blocks。"""
    if not isinstance(styles, dict):
        return

    def _set(block_key: str, style_role: str, keep_with_next: bool, parsed) -> None:
        style = _parsed_style_to_v2(parsed, default_font)
        if style is None:
            return
        style["keep_with_next"] = keep_with_next
        for b in blocks:
            if b.get("key") == block_key:
                b.setdefault("styles", {})[style_role] = style
                return

    for role, (block_key, style_role, keep_with_next) in _STYLE_ROLE_MAP.items():
        if role == "body" and styles.get("body_direct") is not None:
            continue
        _set(block_key, style_role, keep_with_next, styles.get(role))
    caption = styles.get("caption")
    if caption is not None:
        _set("figure_caption", "self", False, caption)
        _set("table_caption", "self", False, caption)


def _apply_parsed_toc(blocks: list[dict], toc_cfg) -> None:
    """把解析出的目录信息（检测到 TOC 域）写入 toc block。"""
    detected = bool(toc_cfg.get("detected")) if isinstance(toc_cfg, dict) else False
    for b in blocks:
        if b.get("key") == "toc":
            b["enabled"] = True
            settings = dict(b.get("settings") or {})
            settings["include_page_numbers"] = True
            b["settings"] = settings
            return


def _cover_block(cover_cfg) -> dict | None:
    """解析出的封面信息 → cover block（settings 携带字段明细）。"""
    if not isinstance(cover_cfg, dict) or not cover_cfg.get("detected"):
        return None
    return {
        "key": "cover",
        "kind": "cover",
        "label": "封面",
        "enabled": True,
        "settings": {
            "detected": True,
            "fields": cover_cfg.get("fields", []),
        },
    }



def _structural_blocks(config: dict) -> list[dict]:
    """Convert parsed table/section metadata into reusable template blocks."""
    blocks: list[dict] = []
    for layout in config.get("tables") or []:
        if not isinstance(layout, dict) or not layout.get("key"):
            continue
        blocks.append({
            "key": str(layout["key"]),
            "kind": "table",
            "enabled": True,
            "styles": {},
            "settings": {
                "headers": list(layout.get("headers") or []),
                "column_widths_cm": list(layout.get("column_widths_cm") or []),
                "source_row_count": layout.get("row_count"),
                "source_column_count": layout.get("column_count"),
                "source_style": layout.get("style"),
            },
        })
    for layout in (config.get("sections") or [])[1:]:
        if not isinstance(layout, dict) or not layout.get("key"):
            continue
        blocks.append({
            "key": str(layout["key"]),
            "kind": "sectionbreak",
            "enabled": True,
            "styles": {},
            "settings": {
                "start_type": layout.get("start_type") or "NEW_PAGE",
                "page": dict(layout.get("page") or {}),
                "header": dict(layout.get("header") or {}),
                "footer": dict(layout.get("footer") or {}),
            },
        })
    return blocks


@router.post("/templates")
async def upload_template(
    name: str = Form(..., min_length=1, max_length=100),
    school_name: str = Form("", max_length=100),
    major: str = Form("", max_length=100),
    paper_type: str = Form("", max_length=100),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"模板文件超过 {settings.max_upload_mb} MB")
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 模板")
    if not content.startswith(b"PK\x03\x04") or b"word/document.xml" not in content:
        raise HTTPException(status_code=400, detail="文件不是有效的 .docx（Word）模板")
    # 统一写入新版模板仓库，避免上传 ID 与模板管理详情接口不兼容。
    # 先用现有 DOCX 解析器提取页面信息，再由新版 TemplateService
    # 基于默认模板创建可查看、可编辑的 mine 模板。
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        config = template_manager._extract_config(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    page = config.get("page", {})

    # 基于默认模板的 blocks 全量合并解析出的样式（保持未解析区块不回退）
    service = get_template_service()
    base = service.resolve(None)
    blocks = [b.to_dict() for b in base.blocks]
    _apply_parsed_styles(blocks, config.get("styles"),
                         config.get("fonts", {}).get("default", {}))
    _apply_parsed_toc(blocks, config.get("toc"))
    cover_block = _cover_block(config.get("cover"))
    if cover_block is not None:
        blocks.append(cover_block)
    blocks.extend(_structural_blocks(config))

    width_cm = page.get("page_width_cm") or 0
    height_cm = page.get("page_height_cm") or 0
    data = {
        "name": name,
        "school_name": school_name,
        "major": major,
        "paper_type": paper_type,
        "description": "上传 DOCX 自动分析：兼容性评分 "
                       f"{config.get('compatibility', {}).get('score', 0)}/100",
        "page": {
            "size": _detect_page_size(page),
            "orientation": ("landscape" if width_cm > height_cm
                             else "portrait"),
            "margins": {
                "top_mm": float(page.get("top_margin_cm", 2.5)) * 10,
                "bottom_mm": float(page.get("bottom_margin_cm", 2.5)) * 10,
                "left_mm": float(page.get("left_margin_cm", 2.5)) * 10,
                "right_mm": float(page.get("right_margin_cm", 2.5)) * 10,
            },
            "header_distance_mm": float(page.get("header_distance_cm", 1.5)) * 10,
            "footer_distance_mm": float(page.get("footer_distance_cm", 1.75)) * 10,
        },
        "blocks": blocks,
    }
    template = service.create_from_data(data)
    service.repo.save_source_docx(template.meta.id, content)
    return {"id": template.meta.id, "name": template.meta.name,
            "school_name": template.meta.school_name,
            "major": template.meta.major, "paper_type": template.meta.paper_type,
            "type": template.meta.type.value, "source": "mine",
            "description": template.meta.description}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> dict:
    if not template_manager.delete_template(template_id):
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"deleted": template_id}
