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
    data = {
        "name": name,
        "school_name": school_name,
        "major": major,
        "paper_type": paper_type,
        "description": "上传 DOCX 自动分析：兼容性评分 "
                       f"{config.get('compatibility', {}).get('score', 0)}/100",
        "page": {
            "size": "A4",
            "orientation": "portrait",
            "margins": {
                "top_mm": float(page.get("top_margin_cm", 2.5)) * 10,
                "bottom_mm": float(page.get("bottom_margin_cm", 2.5)) * 10,
                "left_mm": float(page.get("left_margin_cm", 2.5)) * 10,
                "right_mm": float(page.get("right_margin_cm", 2.5)) * 10,
            },
            "header_distance_mm": float(page.get("header_distance_cm", 1.5)) * 10,
            "footer_distance_mm": float(page.get("footer_distance_cm", 1.75)) * 10,
        },
    }
    template = get_template_service().create_from_data(data)
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
