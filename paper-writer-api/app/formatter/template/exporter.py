"""DOCX 文件输出层（DocxExporter）：Document → .docx 文件。

与 ``TemplateRenderer`` 职责分离：

- ``TemplateRenderer`` 只负责 ``Template → python-docx Document``（内存对象，
  不落盘、不建业务目录、不决定最终文件名）；
- ``DocxExporter`` 只负责 ``Document → .docx 文件``：文件名安全处理、输出
  目录自动创建、覆盖策略、统一 ``document.save``。

设计原则：

- **文件名安全**：Windows 非法字符（``< > : " / \\ | ? *`` 与控制字符）替换、
  空文件名回退默认、超长截断（保留 ``.docx`` 后缀）、``.docx`` 后缀幂等
  （已有不重复补、无则补）；
- **目录归属**：``task_dir`` 不存在时自动创建——但这是 Exporter 的职责，
  业务目录创建不应散落在 Renderer 或其他业务代码里；
- **覆盖策略**：``overwrite=True`` 正常覆盖；``overwrite=False`` 且目标已
  存在时抛出 ``FileExistsError``（不静默覆盖）；
- **落盘唯一入口**：全项目 v2 模板链路统一经本类的 ``export`` 保存，不把
  ``document.save`` 散落在业务代码各处。

默认文件名 ``DEFAULT_DOCX_FILENAME = "论文.docx"`` 与现有约定一致
（preview_service / history_service / 下载 API / 集成测试均依赖此名）。
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

#: 默认输出文件名（与现有约定一致：preview/history/download 均依赖）
DEFAULT_DOCX_FILENAME = "论文.docx"

#: Windows 文件名非法字符（< > : " / \ | ? *）与控制字符
_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: 文件名最大长度（含扩展名）。Windows 组件名上限 255，这里保守取 200，
#: 为完整路径长度（MAX_PATH 260）预留空间。
_MAX_FILENAME_LEN = 200

_DOCX_SUFFIX = ".docx"


def _has_docx_suffix(name: str) -> bool:
    return name.lower().endswith(_DOCX_SUFFIX)


class DocxExporter:
    """把 python-docx ``Document`` 安全保存为 ``.docx`` 文件。

    用法::

        exporter = DocxExporter()
        path = exporter.export(doc, task_dir, filename="毕业论文")
        # filename="毕业论文" → "毕业论文.docx"
    """

    def __init__(self, default_filename: str = DEFAULT_DOCX_FILENAME):
        self.default_filename = default_filename

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def export(self, document: Document, task_dir: Path | str,
               filename: str = DEFAULT_DOCX_FILENAME,
               overwrite: bool = True) -> Path:
        """保存文档，返回输出路径。

        :param document: python-docx ``Document``（内存对象，未保存）
        :param task_dir: 输出目录（不存在时自动创建）
        :param filename: 输出文件名；None/空/空白 → 默认文件名；
                         自动处理非法字符 / 超长 / ``.docx`` 后缀
        :param overwrite: True 覆盖已存在文件；False 且文件已存在时
                          抛出 :class:`FileExistsError`
        :return: 输出文件绝对路径（已保存）
        :raises FileExistsError: ``overwrite=False`` 且目标文件已存在
        """
        name = self.sanitize_filename(filename)
        out_dir = Path(task_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / name
        if not overwrite and out_path.exists():
            raise FileExistsError(
                f"输出文件已存在（overwrite=False）: {out_path}")
        document.save(str(out_path))
        return out_path

    # ------------------------------------------------------------------
    # 文件名安全处理
    # ------------------------------------------------------------------
    def sanitize_filename(self, filename: str | None) -> str:
        """把用户提供的文件名转换为安全的 Windows 文件名。

        规则（幂等，可重复调用）：
        1. None/空/纯空白 → 默认文件名；
        2. Windows 非法字符（``< > : " / \\ | ? *`` 与控制字符）→ ``_``；
        3. 去掉结尾的空格与点（Windows 不允许文件名以它们结尾）；
        4. 处理后为空 → 默认文件名；
        5. 无 ``.docx`` 后缀 → 自动补；已有 → 保持（不重复添加）；
        6. 超长（> ``_MAX_FILENAME_LEN``）→ 截断主体，保留 ``.docx`` 后缀。
        """
        if filename is None:
            return self.default_filename
        name = str(filename).strip()
        if not name:
            return self.default_filename

        # 2. 非法字符 → 下划线
        name = _INVALID_CHARS_RE.sub("_", name)
        # 3. 结尾空格/点剥离（Windows 不允许）
        name = name.rstrip(" .")
        # 4. 全被清理 → 默认
        if not name:
            return self.default_filename

        # 5. 后缀幂等
        if not _has_docx_suffix(name):
            name += _DOCX_SUFFIX

        # 6. 超长截断（保留 .docx）
        if len(name) > _MAX_FILENAME_LEN:
            stem = name[:-len(_DOCX_SUFFIX)]
            name = stem[:_MAX_FILENAME_LEN - len(_DOCX_SUFFIX)] + _DOCX_SUFFIX
        return name
