"""模板渲染接入层（供 formatter/service.py 与业务层调用）。

职责：模板选择（``TemplateService.resolve``）→ spec 转换（``to_render_spec``）
→ ``TemplateRenderer.render``（Template → Document）→ ``DocxExporter.export``
（Document → .docx 文件）→ ``LibreOffice headless`` 刷新域（TOC 等）
→ 落盘。让业务层/格式化层不直接依赖 python-docx 与
Renderer/Exporter 细节，也不直接触碰模板存储细节。

- ``render_with_template``：按 template_id 解析 v2 模板（空/别名 → 默认模板，
  找不到 → 回退默认，与 Service.resolve 语义一致），转换 spec 后渲染落盘；
- 导出后调用 ``_refresh_docx_fields``：用 LibreOffice headless 重新加载并保存
  docx，把 TOC 等域的计算结果**内嵌**到文件里（Word/WPS 打开即显示目录，
  无需手动更新域）。未检测到 soffice 时优雅降级：保留原文件（``w:updateFields
  =true`` 仍在，Word 打开时仍会自动更新域）；
- 模板选择**不写死在 Renderer 内部**，统一走 TemplateService；
- Renderer 只负责渲染，文件输出（文件名/目录/覆盖/保存）统一由
  DocxExporter 负责；
- 本层不修改旧 docx_builder / template_manager 流程。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.formatter.template.exporter import DocxExporter
from app.formatter.template.models import Template
from app.formatter.template.renderer import TemplateRenderer
from app.formatter.template.service import get_service
from app.formatter.template.spec_converter import to_render_spec
from app.services import deepseek

logger = logging.getLogger(__name__)


def _ensure_english_abstract(render_spec: dict) -> None:
    """Generate English abstract and keywords only when the source omitted them."""
    import re

    meta = render_spec.get("meta")
    if not isinstance(meta, dict):
        return
    abstract = str(meta.get("abstract") or "").strip()
    if not abstract or str(meta.get("abstract_en") or "").strip():
        return
    keywords = meta.get("keywords") or []
    if isinstance(keywords, (list, tuple)):
        keyword_text = ", ".join(str(x).strip() for x in keywords if str(x).strip())
    else:
        keyword_text = str(keywords).strip()
    prompt = (
        "Translate the Chinese academic abstract into accurate academic English. "
        "Return exactly two lines and no explanation:\n"
        "Abstract: <English abstract>\nKeywords: <comma-separated English keywords>\n\n"
        f"Chinese abstract: {abstract}\nChinese keywords: {keyword_text}"
    )
    try:
        response = str(deepseek.chat([{"role": "user", "content": prompt}])).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("English abstract generation skipped: %s", exc)
        return
    abstract_match = re.search(
        r"(?:^|\n)\s*Abstract\s*[:：]\s*(.+?)(?=\n\s*Keywords\s*[:：]|\Z)",
        response, re.I | re.S,
    )
    keyword_match = re.search(
        r"(?:^|\n)\s*Keywords\s*[:：]\s*(.+?)\s*$", response, re.I | re.S,
    )
    translated = abstract_match.group(1).strip() if abstract_match else response
    if translated:
        meta["abstract_en"] = translated
    if keyword_match and not meta.get("keywords_en"):
        meta["keywords_en"] = [
            item.strip() for item in re.split(r"[,，;；]", keyword_match.group(1)) if item.strip()
        ]


def render_with_template(template_id: str | None, task_dir: Path | str,
                         spec: dict,
                         paper_info: dict | None = None,
                         out_name: str = "论文.docx") -> Path:
    """解析模板并渲染 docx，返回输出路径（模板不可用回退默认模板）。

    链路：TemplateService.resolve → to_render_spec → TemplateRenderer.render
    （Document）→ DocxExporter.export（.docx 文件）→
    LibreOffice headless 刷新域（TOC 等，缺失时优雅降级）。

    :raises: 底层渲染/保存失败时向上抛（由调用方决定是否回退旧构建器）
    """
    service = get_service()
    template: Template = service.resolve(template_id)
    default_template: Template | None = None
    try:
        default_template = service.default_template()
    except Exception:  # noqa: BLE001 - 兜底模板拿不到时跳过第二级 fallback
        default_template = None
    renderer = TemplateRenderer(default_template=default_template)
    render_spec = to_render_spec(spec, paper_info)
    _ensure_english_abstract(render_spec)
    source_docx = service.repo.source_docx_path(template.meta.id)
    doc = renderer.render(template, render_spec, base_dir=task_dir,
                          source_docx=source_docx)
    out_path = DocxExporter().export(doc, task_dir, out_name)
    _refresh_docx_fields(out_path)
    return out_path


def _refresh_docx_fields(docx_path: Path) -> str:
    """用 LibreOffice headless 刷新 docx 域（TOC 等），返回状态说明。

    流程：soffice --headless --convert-to docx（源与输出同格式），LibreOffice
    加载文档时按 ``w:updateFields`` 计算所有域，再原样保存回 docx —— 这样 TOC
    域的计算结果被**内嵌**进文件，打开即显示目录。

    未检测到 LibreOffice/soffice 或刷新失败时保留原文件（不抛异常），
    ``w:updateFields=true`` 仍在 settings.xml 中，Word/WPS 打开时仍会自动更新。

    :return: 状态说明（供日志/排查用）
    """
    # Preserve the live Word TOC field.  Direct LibreOffice conversion can
    # flatten it into static content and prevent later updates in Word/WPS.
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        logger.warning("未检测到 LibreOffice/soffice，跳过域刷新（Word 打开时仍会按 updateFields 自动更新目录）")
        return "no-libreoffice"
    tmp_dir = docx_path.parent / f".refresh_{docx_path.stem}"
    tmp_dir.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            [exe, "--headless", "--norestore", "--convert-to", "docx",
             "--outdir", str(tmp_dir), str(docx_path)],
            timeout=180, capture_output=True)
        converted = tmp_dir / docx_path.name
        if result.returncode == 0 and converted.exists():
            shutil.move(str(converted), str(docx_path))
            logger.info("LibreOffice 域刷新完成: %s", docx_path.name)
            return "refreshed"
        logger.warning("LibreOffice 刷新失败（exit=%s）: %s",
                       result.returncode, result.stderr.decode("utf-8", "replace")[:300])
        return "refresh-failed"
    except Exception as exc:  # noqa: BLE001 - 刷新失败不阻塞导出
        logger.warning("LibreOffice 刷新异常: %s", exc)
        return "refresh-error"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
