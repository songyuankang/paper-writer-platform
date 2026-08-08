"""模板渲染接入层（供 formatter/service.py 与业务层调用）。

职责：模板选择（``TemplateService.resolve``）→ spec 转换（``to_render_spec``）
→ ``TemplateRenderer.render``（Template → Document）→ ``DocxExporter.export``
（Document → .docx 文件）。让业务层/格式化层不直接依赖 python-docx 与
Renderer/Exporter 细节，也不直接触碰模板存储细节。

- ``render_with_template``：按 template_id 解析 v2 模板（空/别名 → 默认模板，
  找不到 → 回退默认，与 Service.resolve 语义一致），转换 spec 后渲染落盘；
- 模板选择**不写死在 Renderer 内部**，统一走 TemplateService；
- Renderer 只负责渲染，文件输出（文件名/目录/覆盖/保存）统一由
  DocxExporter 负责；
- 本层不修改旧 docx_builder / template_manager 流程。
"""

from __future__ import annotations

from pathlib import Path

from app.formatter.template.exporter import DocxExporter
from app.formatter.template.models import Template
from app.formatter.template.renderer import TemplateRenderer
from app.formatter.template.service import get_service
from app.formatter.template.spec_converter import to_render_spec


def render_with_template(template_id: str | None, task_dir: Path | str,
                         spec: dict,
                         paper_info: dict | None = None,
                         out_name: str = "论文.docx") -> Path:
    """解析模板并渲染 docx，返回输出路径（模板不可用回退默认模板）。

    链路：TemplateService.resolve → to_render_spec → TemplateRenderer.render
    （Document）→ DocxExporter.export（.docx 文件）。

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
    doc = renderer.render(template, render_spec, base_dir=task_dir)
    return DocxExporter().export(doc, task_dir, out_name)
