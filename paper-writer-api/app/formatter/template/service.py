"""模板业务层（TemplateService）。

承载业务规则，保持 Repository 纯净（Repository 只做读取/保存/删除/查询）：
- 默认模板回退链（is_default → 基础模板第一个 → 任意内置）
- ``resolve()`` 解析：空/别名 → 默认；找不到 → 回退默认（渲染不中断）
- legacy 兼容：旧版上传模板（无新格式 content）识别与处理
- 复制（duplicate）：命名"（副本）"、parent_id 溯源
- 新建：content 缺省时基于默认模板生成（开箱可用）

本层只依赖 Repository + Loader，不直接碰 DB 与文件。
"""

from __future__ import annotations

import copy
from pathlib import Path

from app.formatter.template.loader import TemplateLoader
from app.formatter.template.models import (
    CURRENT_SCHEMA_VERSION,
    Template,
    TemplateBlock,
    TemplateMeta,
    TemplateType,
)
from app.formatter.template.repository import TemplateRepository
from app.formatter.template.validator import (
    TemplateValidationError,
    TemplateValidator,
)

#: 旧接口传入的"默认模板"占位 id
_DEFAULT_ALIASES = {"", "default", "default_template", None}

#: 复制默认后缀
DUPLICATE_SUFFIX = "（副本）"


class TemplateService:
    """模板业务入口：默认回退 / 解析 / legacy / 复制 / CRUD 业务封装。"""

    def __init__(self, repo: TemplateRepository, loader: TemplateLoader):
        self.repo = repo
        self.loader = loader

    # ------------------------------------------------------------------
    # 默认模板回退 / 解析
    # ------------------------------------------------------------------
    def default_template(self) -> Template:
        """返回默认模板（回退链：is_default → basic 第一个 → 任意内置）。"""
        default_id = self.repo.default_id()
        if default_id:
            tpl = self.repo.get(default_id)
            if tpl is not None:
                return tpl
        for p in self.loader.basic_files():
            tpl = self.repo.get(self.loader.basic_id(p.stem))
            if tpl is not None:
                return tpl
        for tid, _path in self.repo.builtin_files().items():
            tpl = self.repo.get(tid)
            if tpl is not None:
                return tpl
        raise FileNotFoundError("未找到任何可用模板（请检查 templates 目录）")

    def resolve(self, template_id: str | None = None) -> Template:
        """解析模板：空/别名 → 默认；指定 id 找不到或不可用 → 回退默认。"""
        if template_id in _DEFAULT_ALIASES:
            return self.default_template()
        tpl = self.repo.get(template_id)
        if tpl is None:
            return self.default_template()
        return tpl

    # ------------------------------------------------------------------
    # 查询（转发 + legacy 感知）
    # ------------------------------------------------------------------
    def list_meta(self, type: str | None = None, keyword: str | None = None,
                  category: str | None = None) -> list[TemplateMeta]:
        return self.repo.list_meta(type=type, keyword=keyword,
                                   category=category)

    def get(self, template_id: str) -> Template | None:
        """读取完整模板。旧版模板（legacy）无法加载，返回 None。"""
        return self.repo.get(template_id)

    def get_meta(self, template_id: str) -> TemplateMeta | None:
        return self.repo.get_meta(template_id)

    def is_legacy(self, template_id: str) -> bool:
        """判断是否为旧版上传模板（无法用新格式加载）。"""
        if self.repo.get(template_id) is not None:
            return False
        meta = self.repo.get_meta(template_id)
        return bool(meta and meta.legacy)

    def cover_docx_path(self, template_id: str) -> Path | None:
        """定位模板的 cover.docx（双模板版式母版）；无则 None。"""
        tdir = self.repo.template_dir(template_id)
        if tdir is None:
            return None
        return self.loader.cover_docx_path(tdir)

    # ------------------------------------------------------------------
    # CRUD（业务封装）
    # ------------------------------------------------------------------
    def create(self, name: str, category: str = "", description: str = "",
               content: Template | None = None,
               parent_id: str | None = None) -> Template:
        """新建我的模板。content 缺省基于默认模板（开箱可用）。"""
        if content is None:
            content = copy.deepcopy(self.default_template())
        content.meta.name = name.strip() if name else "未命名模板"
        content.meta.category = category or content.meta.category
        content.meta.description = description or content.meta.description
        content.meta.parent_id = parent_id
        content.schema_version = content.schema_version \
            or CURRENT_SCHEMA_VERSION
        self._validate(content)
        return self.repo.create(content)

    def update(self, template_id: str, content: Template) -> Template:
        """更新我的模板（内置只读由存储层约束）。"""
        self._validate(content)
        return self.repo.update(template_id, content)

    def delete(self, template_id: str) -> bool:
        """删除我的模板（内置不可删）。"""
        return self.repo.delete(template_id)

    def duplicate(self, template_id: str,
                  name: str | None = None) -> Template:
        """复制任意模板（基础/学校/我的）→ 生成我的模板，parent_id 溯源。"""
        tpl = self.repo.get(template_id)
        if tpl is None:
            raise KeyError(f"模板不存在或不可用: {template_id}")
        content = copy.deepcopy(tpl)
        content.meta.parent_id = template_id
        content.meta.name = name or f"{content.meta.name}{DUPLICATE_SUFFIX}"
        self._validate(content)
        return self.repo.create(content)

    # ------------------------------------------------------------------
    # 结构化写入（API DTO → Template → Validator → Repository）
    # ------------------------------------------------------------------
    def create_from_data(self, data: dict,
                         base_template_id: str | None = None) -> Template:
        """按结构化字段创建我的模板；content 缺省继承基础模板。"""
        if base_template_id:
            base = self.repo.get(base_template_id)
            if base is None:
                raise KeyError(f"基础模板不存在或不可用: {base_template_id}")
        else:
            base = self.default_template()
        name = data.get("name")
        if not name or not str(name).strip():
            raise ValueError("模板名称不能为空")
        tpl = copy.deepcopy(base)
        tpl.meta.id = ""
        tpl.meta.parent_id = base_template_id
        tpl.meta.name = str(name).strip()
        self._apply_template_data(tpl, data)
        self._validate(tpl)
        return self.repo.create(tpl)

    def update_from_data(self, template_id: str, data: dict) -> Template:
        """按结构化字段更新我的模板（只允许 mine）。"""
        tpl = self.repo.get(template_id)
        if tpl is None:
            raise KeyError(f"模板不存在或不可用: {template_id}")
        if tpl.meta.builtin or tpl.meta.type != TemplateType.MINE:
            raise PermissionError("只有我的模板可以编辑")
        if data.get("name") is not None \
                and not str(data["name"]).strip():
            raise ValueError("模板名称不能为空")
        self._apply_template_data(tpl, data)
        self._validate(tpl)
        return self.repo.update(template_id, tpl)

    @staticmethod
    def _validate(tpl: Template) -> None:
        """所有 CRUD 写入统一过 Validator，不通过直接抛错。"""
        result = TemplateValidator().validate_template(tpl)
        if not result.valid:
            raise TemplateValidationError(result)

    @staticmethod
    def _apply_template_data(tpl: Template, data: dict) -> None:
        """把结构化 DTO 字段合并进 Template（未提供的字段保留原值）。"""
        if data.get("name") is not None:
            tpl.meta.name = str(data["name"]).strip()

        for field in ("description", "category", "paper_type",
                      "school_name", "major"):
            if data.get(field) is not None:
                setattr(tpl.meta, field, data[field])

        blocks = data.get("blocks")
        if blocks is not None:
            tpl.blocks = [TemplateBlock.from_dict(b) for b in blocks]

        if data.get("page") is not None:
            tpl.page = dict(data["page"])
        if data.get("header") is not None:
            tpl.header = dict(data["header"])
        if data.get("footer") is not None:
            tpl.footer = dict(data["footer"])
        if data.get("numbering") is not None:
            tpl.numbering = dict(data["numbering"])

        toc = data.get("toc")
        if toc is not None:
            toc_block = tpl.get_block("toc")
            if toc_block is None:
                toc_block = TemplateBlock(
                    key="toc", kind="toc", label="目录", enabled=True)
                tpl.blocks.append(toc_block)
            toc_block.enabled = bool(toc.get("enabled", True))
            toc_block.settings = dict(toc_block.settings or {})
            toc_block.settings["include_page_numbers"] = bool(
                toc.get("include_page_numbers", True))

        ref_style = data.get("reference_style")
        if ref_style is not None:
            ref = tpl.get_block("references")
            if ref is None:
                ref = TemplateBlock(
                    key="references", kind="references",
                    label="参考文献", enabled=True)
                tpl.blocks.append(ref)
            ref.settings = dict(ref.settings or {})
            ref.settings["style"] = ref_style

    # ------------------------------------------------------------------
    # 状态（转发）
    # ------------------------------------------------------------------
    def set_favorite(self, template_id: str, favorite: bool) -> bool:
        return self.repo.set_favorite(template_id, favorite)

    def set_default(self, template_id: str) -> bool:
        return self.repo.set_default(template_id)


#: 模块级单例（懒初始化由 build_services 提供）
_service: TemplateService | None = None


def build_services(root: Path | None = None) -> tuple[TemplateRepository,
                                                      TemplateLoader,
                                                      TemplateService]:
    """装配 Repository / Loader / Service 三件套（依赖注入入口）。"""
    from app.formatter.template import DEFAULT_TEMPLATES_ROOT
    loader = TemplateLoader(root or DEFAULT_TEMPLATES_ROOT)
    repo = TemplateRepository(loader)
    return repo, loader, TemplateService(repo, loader)


def get_service() -> TemplateService:
    """获取全局 Service 单例。"""
    global _service
    if _service is None:
        _repo, _loader, _service = build_services()
    return _service
