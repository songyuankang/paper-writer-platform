"""目录：保持模板目录样式并标记打开时更新（逻辑不变）。"""

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def mark_toc_update(doc) -> None:
    settings = doc.settings.element
    el = settings.find(qn("w:updateFields"))
    if el is None:
        el = OxmlElement("w:updateFields")
        settings.append(el)
    el.set(qn("w:val"), "true")
