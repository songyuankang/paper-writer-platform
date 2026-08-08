"""论文数据 → TemplateRenderer spec 转换层。

现有业务层产生的论文 spec（``{meta, sections, references}``，由
``spec_from_paper_content`` / ``build_spec`` / ``pipeline_spec_from_content`` /
草稿导出等产生）与 TemplateRenderer 所需的 spec 高度一致。本层职责：

- 归一化/白名单校验 sections（h1-h4 / p / figure / table / pagebreak /
  references / acknowledgement / appendix / toc）；
- 从 ``paper_info`` 补充可选元数据（title_en / abstract_en / keywords_en），
  供 renderer 的英文摘要/关键词区块使用；
- 提供目录开关（``meta.toc=False`` 时 renderer 不渲染 TOC）；
- 成为"现有论文数据 → renderer spec"映射的**唯一入口**，使 TemplateRenderer
  不直接依赖业务 Service；未来业务结构变化时只需改本层。

设计原则：宽容（未知 section 类型保留不丢数据，renderer 会安全忽略），
不改动输入对象（返回深拷贝）。
"""

from __future__ import annotations

import copy
from typing import Any

#: renderer 支持的 section 类型（白名单，其余原样保留交由 renderer 忽略）
_ALLOWED_TYPES = {
    "h1", "h2", "h3", "h4",
    "p", "figure", "table", "pagebreak",
    "references", "acknowledgement", "appendix", "toc",
}

#: 可从 paper_info 补充到 meta 的可选字段（若 spec 未提供）
_ENRICH_KEYS = ("title_en", "abstract_en", "keywords_en")


def to_render_spec(spec: dict | None,
                   paper_info: dict | None = None) -> dict:
    """把现有论文 spec 转换为 TemplateRenderer spec（返回深拷贝）。

    :param spec: 现有论文 spec（{meta, sections, references}）；None/非法时
                 返回空骨架（renderer 仍可安全渲染）
    :param paper_info: 业务层论文信息（request/draft），用于补充可选元数据
    """
    if not isinstance(spec, dict):
        out: dict[str, Any] = {"meta": {}, "sections": [], "references": []}
    else:
        out = copy.deepcopy(spec)

    meta = out.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        out["meta"] = meta

    # 补充可选英文/附加元数据（spec 已有时不覆盖）
    if isinstance(paper_info, dict):
        for key in _ENRICH_KEYS:
            value = paper_info.get(key)
            if value and not meta.get(key):
                meta[key] = value

    # 目录开关：paper_info.toc 显式控制；否则 renderer 按模板默认
    if isinstance(paper_info, dict) and "toc" in paper_info:
        meta["toc"] = bool(paper_info["toc"])

    # sections 归一化（未知类型保留，renderer 会忽略，不丢数据）
    sections = out.get("sections")
    if not isinstance(sections, list):
        out["sections"] = []
    return out
