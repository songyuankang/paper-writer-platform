"""模板管理 API（v2 模板系统）。

- ``GET /api/templates``            模板列表（含默认标记）
- ``GET /api/templates/{id}``       模板详情（可读展示信息）
- ``POST /api/templates``           创建我的模板
- ``PUT /api/templates/{id}``       更新我的模板
- ``POST /api/templates/{id}/duplicate`` 复制模板
- ``DELETE /api/templates/{id}``    删除我的模板
- ``POST /api/templates/{id}/set-default`` 设置默认模板

设计约束：
- 模板解析统一走 ``TemplateService``（resolve / list_meta / get / repo.default_id），
  不在本模块重复编写模板 ID 映射；
- 写入请求使用结构化 DTO，完整 Template JSON 由 TemplateService 组装；
- 所有写入先经过 TemplateValidator；
- 只输出**展示层 DTO**，不把 Template/TemplateMeta 内部对象直接暴露给前端。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.formatter.template import get_service
from app.formatter.template.models import (
    Template,
    TemplateBlock,
    TemplateMeta,
)
from app.formatter.template.validator import TemplateValidationError
from app.models.template import (
    TemplateDuplicateRequest,
    TemplateWriteRequest,
)
from app.formatter.template.service import TemplateService

router = APIRouter(prefix="/api/templates", tags=["templates"])

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


# ----------------------------------------------------------------------
# DTO 构建（只暴露可读信息）
# ----------------------------------------------------------------------
def _source_of(meta: TemplateMeta) -> str:
    """来源：builtin / school / mine。"""
    if meta.builtin:
        return "builtin"
    return meta.type.value


def _editable_of(meta: TemplateMeta) -> bool:
    """只有 mine 且未标记 legacy 的模板可编辑/删除。"""
    return (meta.type.value == "mine"
            and not meta.builtin
            and not meta.legacy)


def _meta_dto(meta: TemplateMeta) -> dict:
    return {
        "id": meta.id,
        "name": meta.name,
        "description": meta.description,
        "category": meta.category,
        "paper_type": meta.paper_type,
        "source": _source_of(meta),
        "type": meta.type.value,
        "school_name": meta.school_name,
        "major": meta.major,
        "version": meta.version,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "is_default": meta.is_default,
        "is_favorite": meta.is_favorite,
        "has_cover": meta.has_cover,
        "legacy": meta.legacy,
        "editable": _editable_of(meta),
    }


def _block_summary(block: TemplateBlock) -> dict:
    return {
        "key": block.key,
        "kind": block.kind,
        "label": block.label,
        "enabled": block.enabled,
        "level": block.level,
    }


def _block_dto(block: TemplateBlock) -> dict:
    """完整区块 DTO（样式全量字段，供编辑器直接回填）。"""
    return {
        "key": block.key,
        "kind": block.kind,
        "label": block.label,
        "enabled": block.enabled,
        "level": block.level,
        "styles": {
            role: style.to_dict() for role, style in block.styles.items()
        },
        "settings": block.settings or {},
    }


def _font_summary(block: TemplateBlock | None) -> dict | None:
    """区块主样式的可读摘要（供前端展示 正文/标题 格式）。"""
    if block is None:
        return None
    style = block.styles.get("self") or block.styles.get("content")
    if style is None:
        return None
    return {
        "font": style.font_family_east_asia,
        "latin_font": style.font_family_latin,
        "font_size_pt": style.font_size_pt,
        "bold": style.bold,
        "alignment": style.alignment.value,
        "line_spacing": style.line_spacing_value,
        "first_line_indent": {
            "unit": style.first_line_indent_unit.value,
            "value": style.first_line_indent_value,
        },
    }


def _default_id(service: TemplateService) -> str | None:
    """有效默认模板 id（DB 标记优先，否则回退链首）。"""
    did = service.repo.default_id()
    if did:
        return did
    try:
        return service.default_template().meta.id
    except Exception:  # noqa: BLE001 - 无模板时返回 None
        return None


def _detail_dto(tpl: Template) -> dict:
    meta = tpl.meta
    dto = _meta_dto(meta)
    page = tpl.page or {}
    dto["page"] = {
        "size": page.get("size", "A4"),
        "orientation": page.get("orientation", "portrait"),
        "margins": page.get("margins", {}),
        "header_distance_mm": page.get("header_distance_mm"),
        "footer_distance_mm": page.get("footer_distance_mm"),
    }
    dto["numbering"] = tpl.numbering or {}
    toc = tpl.get_block("toc")
    dto["toc"] = {
        "enabled": bool(toc and toc.enabled),
        "include_page_numbers": bool(
            toc and toc.settings and toc.settings.get(
                "include_page_numbers", True)),
    }
    ref = tpl.get_block("references")
    ref_style = "gb7714"
    if ref and ref.settings and ref.settings.get("style"):
        ref_style = ref.settings["style"]
    dto["reference_style"] = ref_style
    dto["header"] = tpl.header or {}
    dto["footer"] = tpl.footer or {}
    dto["blocks"] = [_block_dto(b) for b in tpl.blocks]
    dto["styles"] = {
        "title": _font_summary(tpl.get_block("title_zh")),
        "heading1": _font_summary(tpl.get_block("heading1")),
        "body": _font_summary(tpl.get_block("body")),
        "references": _font_summary(tpl.get_block("references")),
    }
    return dto


# ----------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------
@router.get("")
def list_templates() -> dict:
    """当前所有可用模板（过滤 legacy，含默认标记）。"""
    service = get_service()
    default_id = _default_id(service)
    items = []
    for m in service.list_meta():
        if m.legacy:
            continue
        dto = _meta_dto(m)
        # 默认标记以有效默认模板（DB 标记或回退链首）为准
        dto["is_default"] = (m.id == default_id)
        items.append(dto)
    return {"items": items, "default_id": default_id}


@router.get("/{template_id}")
def template_detail(template_id: str) -> dict:
    """模板可读详情（页面/编号/目录/参考文献/区块摘要/样式摘要）。"""
    _require_valid_id(template_id)
    service = get_service()
    tpl = service.get(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return _detail_dto(tpl)


@router.post("")
def create_template(data: TemplateWriteRequest) -> dict:
    """创建我的模板（结构化 DTO → Service → Validator → Repository）。"""
    if data.base_template_id:
        _require_valid_id(data.base_template_id)
    service = get_service()
    try:
        tpl = service.create_from_data(
            data.model_dump(exclude_none=True), data.base_template_id)
    except Exception as exc:  # noqa: BLE001 - 统一映射为 HTTP 错误
        _raise_http_error(exc)
    return _detail_dto(tpl)


@router.put("/{template_id}")
def update_template(template_id: str, data: TemplateWriteRequest) -> dict:
    """更新我的模板；builtin / school 返回 403。"""
    _require_valid_id(template_id)
    service = get_service()
    try:
        tpl = service.update_from_data(
            template_id, data.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
    return _detail_dto(tpl)


@router.post("/{template_id}/duplicate")
def duplicate_template(
        template_id: str,
        data: TemplateDuplicateRequest | None = None) -> dict:
    """复制任意可用模板为我的模板。"""
    _require_valid_id(template_id)
    service = get_service()
    try:
        tpl = service.duplicate(
            template_id, data.name if data is not None else None)
    except Exception as exc:  # noqa: BLE001
        _raise_http_error(exc)
    return _detail_dto(tpl)


@router.delete("/{template_id}")
def delete_template(template_id: str) -> dict:
    """删除我的模板；builtin / school 返回 403。"""
    _require_valid_id(template_id)
    service = get_service()
    meta = service.get_meta(template_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    if not _editable_of(meta):
        raise HTTPException(
            status_code=403,
            detail="只有我的模板可以删除，内置模板请先复制为我的模板")
    if not service.delete(template_id):
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"deleted": template_id}


@router.post("/{template_id}/set-default")
def set_default_template(template_id: str) -> dict:
    """设置默认模板（全局唯一；builtin / school / mine 均可作为默认）。"""
    _require_valid_id(template_id)
    service = get_service()
    meta = service.get_meta(template_id)
    if meta is None or meta.legacy:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    if not service.set_default(template_id):
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"default_id": template_id}


def _require_valid_id(template_id: str) -> None:
    """模板 id 只允许安全字符，防止路径穿越/异常 id。"""
    if not template_id or not _ID_RE.fullmatch(template_id):
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")


def _raise_http_error(exc: Exception) -> None:
    """Service 异常 → HTTP 异常；未知异常继续向上抛。"""
    if isinstance(exc, TemplateValidationError):
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "issues": [i.as_dict() for i in exc.result.issues],
            })
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc
