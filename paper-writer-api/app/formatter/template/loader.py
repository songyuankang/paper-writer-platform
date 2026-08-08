"""模板文件加载层（TemplateLoader）。

统一负责从文件系统加载模板资源：
- JSON 模板（basic/*.json、school/<slug>/template.json、我的模板 content 是 DB 存储）
- ``cover.docx`` 版式母版定位（封面/校徽/水印/页眉页脚母版，双模板机制的 DOCX 侧）

Repository 只调用本 Loader，不直接碰文件。职责边界：
- Loader 只做"读文件 → 数据/模型"，不含存储与业务规则
- JSON 非法时抛 :class:`TemplateLoadError`（含路径信息）
- 结构缺字段由模型 ``from_dict`` 兜底，不抛异常（结构校验归 Validator）
"""

from __future__ import annotations

from pathlib import Path

from app.formatter.template.models import (
    CURRENT_SCHEMA_VERSION,
    Template,
    TemplateMeta,
)

#: 内置模板目录名
BASIC_DIRNAME = "basic"
SCHOOL_DIRNAME = "school"
#: 双模板机制：DOCX 版式母版文件名
COVER_DOCX_NAME = "cover.docx"
#: 学校模板目录内的主 JSON 文件名
SCHOOL_TEMPLATE_JSON = "template.json"

#: 内置模板 id 前缀（id 由路径推导，稳定）
BASIC_PREFIX = "basic-"
SCHOOL_PREFIX = "school-"


class TemplateLoadError(Exception):
    """模板文件加载失败（不存在 / JSON 非法 / 结构非对象）。"""

    def __init__(self, path: Path | str, reason: str = ""):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"模板加载失败: {self.path}" +
                         (f"（{reason}）" if reason else ""))


class TemplateLoader:
    """模板文件系统访问层。"""

    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------------
    # JSON 读取 / 解析
    # ------------------------------------------------------------------
    def read_json(self, path: Path) -> dict:
        """读取并解析 JSON；非法 JSON 抛 TemplateLoadError。"""
        path = Path(path)
        if not path.is_file():
            raise TemplateLoadError(path, "文件不存在")
        try:
            data = json_load(path)
        except (ValueError, OSError) as exc:
            raise TemplateLoadError(path, f"JSON 非法: {exc}") from exc
        if not isinstance(data, dict):
            raise TemplateLoadError(path, "JSON 顶层必须是对象")
        return data

    def load_template(self, path: Path) -> Template:
        """加载模板 JSON → Template 模型（缺字段兜底，结构问题抛错）。"""
        data = self.read_json(path)
        return Template.from_dict(data, template_id=self._id_from_path(path))

    def load_meta(self, path: Path, template_id: str | None = None) -> TemplateMeta:
        """加载模板元数据（只读 meta 段，不解析完整 blocks）。"""
        data = self.read_json(path)
        tid = template_id or self._id_from_path(path)
        meta = TemplateMeta.from_json(data.get("meta"), tid)
        # 文件优先原则：schema_version 以文件为准
        meta.schema_version = int(data.get("schema_version")
                                  or CURRENT_SCHEMA_VERSION)
        meta.has_cover = self.cover_docx_path(path.parent) is not None
        return meta

    # ------------------------------------------------------------------
    # 目录扫描（返回文件路径，id 推导不在此处）
    # ------------------------------------------------------------------
    def basic_files(self) -> list[Path]:
        """basic 目录下所有 *.json。"""
        d = self.root / BASIC_DIRNAME
        if not d.is_dir():
            return []
        return sorted(p for p in d.glob("*.json") if p.is_file())

    def school_dirs(self) -> list[Path]:
        """school 目录下所有含 template.json 的子目录。"""
        d = self.root / SCHOOL_DIRNAME
        if not d.is_dir():
            return []
        return sorted(
            p for p in d.iterdir()
            if p.is_dir() and (p / SCHOOL_TEMPLATE_JSON).is_file())

    def school_template_file(self, slug: str) -> Path:
        return self.root / SCHOOL_DIRNAME / slug / SCHOOL_TEMPLATE_JSON

    # ------------------------------------------------------------------
    # id 推导（命名规范，供 Repository 使用）
    # ------------------------------------------------------------------
    @staticmethod
    def basic_id(stem: str) -> str:
        return f"{BASIC_PREFIX}{stem}"

    @staticmethod
    def school_id(slug: str) -> str:
        return f"{SCHOOL_PREFIX}{slug}"

    @staticmethod
    def _id_from_path(path: Path) -> str:
        """由路径推导内置模板 id：basic/<stem>.json 或 school/<slug>/template.json。"""
        path = Path(path)
        parent = path.parent
        if parent.name == BASIC_DIRNAME:
            return TemplateLoader.basic_id(path.stem)
        if parent.name == SCHOOL_DIRNAME:
            return TemplateLoader.school_id(path.stem)
        return path.stem

    # ------------------------------------------------------------------
    # DOCX 版式母版（双模板机制）
    # ------------------------------------------------------------------
    def cover_docx_path(self, template_dir: Path | str) -> Path | None:
        """定位模板目录下的 cover.docx；不存在返回 None。"""
        d = Path(template_dir)
        if not d.is_dir():
            return None
        cover = d / COVER_DOCX_NAME
        return cover if cover.is_file() else None

    def has_cover(self, template_dir: Path | str) -> bool:
        return self.cover_docx_path(template_dir) is not None


def json_load(path: Path):
    """小工具：读 UTF-8 JSON（供 read_json 使用，便于独立测试）。"""
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))
