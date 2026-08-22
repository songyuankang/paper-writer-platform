"""论文草稿服务：逐段生成编辑器的数据与逻辑。

草稿（draft.json）结构：
{
  title, meta{...}, abstract{zh,en}, keywords{zh,en},
  acknowledgement, references[], generating, progress,
  sections: [{id, number, title, level, gist, paragraphs:[{id,text}]}]
}
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from typing import Iterator
from pathlib import Path

from app.config import Settings, settings

from app.draft import outline as outline_mod
from app.draft.chart_runtime import now, recompute_chart_block, walk_sections
from app.draft.generation_quality import GeneratedBodyQualityError, assert_generated_body
from app.draft.outline_role_validator import OutlineRoleValidator
from app.services.research_object_service import renumber_document_references
from app.services.cross_reference_service import CrossReferenceService
from app.services.dependency_graph_service import DependencyGraphService
from app.services.literature_service import LiteratureService

from app.formatter import service as formatter_service
from app.models.task import TaskStatus
from app.services import deepseek, deepseek_service, model_service


def _prompt(name: str) -> str:
    return (settings.prompts_dir / name).read_text(encoding="utf-8")


def _leaf_ids(sections: list[dict]) -> set[str]:
    """叶子节点 = 不是任何其他节点的父节点（id 前缀）。"""
    ids = {s["id"] for s in sections}
    parents = {s["id"] for s in sections
               if any(o["id"].startswith(s["id"] + "-") for o in sections)}
    return ids - parents


# -- AI 输出清洗 -----------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S.*$")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MD_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s+")
_SENTENCE_END_RE = re.compile(r"[。！？；：]$")
_SECTION_DRAFT_LABEL_RE = re.compile(
    r"^\s*第[一二三四五六七八九十百\d]+段(?:具体)?(?:草稿|正文)\s*[：:]\s*"
)
_INTERNAL_INSTRUCTION_PATTERNS = (
    re.compile(r"(?:现在(?:开始)?起草(?:段落|正文)?|现在写正式内容|让我们(?:慢慢)?(?:构思|具体计算))"),
    re.compile(r"(?:需要(?:满足|达到)(?:约|至少)?\s*\d+\s*字|每(?:个)?段落约\s*\d+\s*(?:[-—]\s*\d+\s*)?字)"),
    re.compile(r"(?:注意|请)(?:不要|勿).*(?:输出)?(?:标题|markdown)" , re.I),
    re.compile(r"段落(?:之间|间)空行"),
)


def _is_internal_generation_instruction(paragraph: str) -> bool:
    """判断模型是否误输出了写作计划、字数计算或格式指令。"""
    compact = re.sub(r"\s+", "", paragraph)
    return bool(compact) and any(pattern.search(compact) for pattern in _INTERNAL_INSTRUCTION_PATTERNS)


def _clean_generated_paragraphs(text: str) -> list[str]:
    """把 AI 生成的章节文本清洗为自然段列表。

    - 丢弃 Markdown 标题行（#/##/###…，标题由 section.title 管理）与表格行
    - 去除行内 Markdown 标记（**粗体**、*斜体*、`代码`、~~删除线~~、列表前缀）
    - 以空行作为自然段边界；单个换行视为段内换行（合并时以空格连接）
    - 兼容“逐行段落”输出：段内每行都以句末标点结尾时按行拆成独立段
    - strip 并过滤空段
    """
    lines: list[str] = []
    for raw in text.splitlines():
        if _MD_HEADING_RE.match(raw) or _MD_TABLE_ROW_RE.match(raw):
            lines.append("")  # 标题/表格行丢弃，但保留自然段边界
            continue
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        line = _MD_LIST_RE.sub("", line)
        line = _SECTION_DRAFT_LABEL_RE.sub("", line)
        if not line:
            lines.append("")
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", line)
        line = re.sub(r"~~(.+?)~~", r"\1", line)
        line = re.sub(r"`([^`\n]+)`", r"\1", line)
        line = line.strip()
        lines.append(line)

    # 以空行切分自然段
    groups: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        if line:
            buf.append(line)
        elif buf:
            groups.append(buf)
            buf = []
    if buf:
        groups.append(buf)

    result: list[str] = []
    for group in groups:
        if len(group) > 1 and all(
                _SENTENCE_END_RE.search(ln) for ln in group if ln.strip()):
            # 逐行段落：每行都是完整句子 → 按行拆成独立段
            result.extend(ln.strip() for ln in group if ln.strip())
        else:
            result.append(" ".join(ln.strip() for ln in group if ln.strip()))
    return [
        paragraph for paragraph in result
        if paragraph.strip() and not _is_internal_generation_instruction(paragraph)
    ]


def _effective_text_length(text: str) -> int:
    """按编辑器一致的非空白字符口径统计有效正文长度。"""
    return len(re.sub(r"\s+", "", text or ""))


def _body_char_count(draft: dict) -> int:
    """只统计正文叶子小节中的有效文本，不计摘要、致谢和参考文献。"""
    leaf_ids = _leaf_ids(draft.get("sections") or [])
    return sum(
        _effective_text_length(str(paragraph.get("text") or ""))
        for section in draft.get("sections") or []
        if section.get("id") in leaf_ids
        for paragraph in section.get("paragraphs") or []
    )


def _leaf_budget_weight(section: dict) -> float:
    """按章节功能进行温和加权，避免核心分析章节被平均稀释。"""
    title = str(section.get("title") or "")
    if any(word in title for word in ("引言", "绪论", "结论", "总结", "展望")):
        return 0.85
    if any(word in title for word in ("方法", "实证", "结果", "分析", "讨论", "机制", "对策")):
        return 1.15
    return 1.0


def _apply_leaf_budgets(sections: list[dict], target_chars: int) -> None:
    """向每个叶子小节写入目标字数和最低字数，预算总和带少量清洗缓冲。"""
    leaves = sorted(
        [section for section in sections if section.get("id") in _leaf_ids(sections)],
        key=lambda section: str(section.get("id") or ""),
    )
    if not leaves:
        return
    buffered_target = max(int(target_chars * 1.02), target_chars)
    weights = [_leaf_budget_weight(section) for section in leaves]
    weight_sum = sum(weights) or 1.0
    budgets = [max(180, round(buffered_target * weight / weight_sum)) for weight in weights]
    budgets[-1] += buffered_target - sum(budgets)
    for section, budget in zip(leaves, budgets):
        section["target_chars"] = int(budget)
        section["min_chars"] = max(160, int(budget * 0.88))


_EN_ABSTRACT_PLACEHOLDER_RE = re.compile(r"<\s*(?:英文摘要|英文关键词)\s*>", re.I)
_EN_ABSTRACT_META_RE = re.compile(
    r"(?:我们需要|用户(?:要求|给的)|格式(?:为)?|注意|翻译摘要|摘要内容|"
    r"输出英文|关键词(?:可能|提取)|Abstract\s*[：:]\s*<|Keywords?\s*[：:]\s*<)",
    re.I,
)
_CJK_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _split_en_abstract(text: str) -> tuple[str, list[str]]:
    """把 AI 返回的最终英文摘要拆分为（摘要, 关键词列表）。

    仅接受 ``Abstract: <English text>`` 与 ``Keywords: <English keywords>``
    的最终输出；模型泄漏的中文规划、占位符或格式说明不会写入草稿。
    """
    raw = text.strip()
    if not raw or _EN_ABSTRACT_PLACEHOLDER_RE.search(raw) or _EN_ABSTRACT_META_RE.search(raw):
        return "", []

    abstract = raw
    keywords: list[str] = []
    match = re.search(r"Keywords?\s*[：:]\s*(.+)", abstract, flags=re.I | re.S)
    if match:
        parsed = [item.strip() for item in re.split(r"[，,;；]", match.group(1)) if item.strip()]
        keywords = [
            item for item in parsed
            if re.search(r"[A-Za-z]", item)
            and not _CJK_TEXT_RE.search(item)
            and not _EN_ABSTRACT_META_RE.search(item)
        ][:5]
    abstract = re.sub(r"Keywords?\s*[：:].*", "", abstract,
                      flags=re.I | re.S).strip()
    abstract = re.sub(r"^Abstract\s*[：:]\s*", "", abstract,
                      flags=re.I).strip()
    if not abstract or _CJK_TEXT_RE.search(abstract) or not re.search(r"[A-Za-z]", abstract):
        return "", []
    return abstract, keywords


class DraftService:
    def __init__(self, task_id: str, task_dir: Path, task_manager=None):
        self.task_id = task_id
        self.task_dir = task_dir
        self.task_manager = task_manager
        self.path = task_dir / "draft.json"
        self.lock = threading.Lock()

    # -- 持久化 ------------------------------------------------------------

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save(self, draft: dict) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    def _storage_settings(self) -> Settings:
        """Resolve storage relative to this draft for isolated tests and exports.

        Runtime tasks use the application singleton.  Test and E2E services may
        point a DraftService at a temporary ``outputs/<task>`` root; deriving the
        sibling data directory keeps ResearchObject/CrossReference lookups in the
        same task workspace instead of silently falling back to process globals.
        """
        if self.task_dir.parent == settings.output_dir:
            return settings
        root = self.task_dir.parent.parent
        return Settings(
            db_path=root / "data" / "history.db",
            output_dir=self.task_dir.parent,
            upload_dir=root / "uploads",
            log_dir=root / "logs",
        )

    def body_char_count(self, draft: dict | None = None) -> int:

        """返回当前草稿正文有效字数，供生成验收和接口复用。"""
        return _body_char_count(draft if draft is not None else self.load())

    def _refresh_word_stats(self, draft: dict) -> dict:
        target = max(int((draft.get("meta") or {}).get("word_count", 3000)), 500)
        actual = _body_char_count(draft)
        stats = {
            "target": target,
            "minimum": int((draft.get("meta") or {}).get("completion_min_chars", target * 0.95)),
            "actual": actual,
            "shortfall": max(0, target - actual),
        }
        draft["word_stats"] = stats
        return stats

    def _paper_info(self, draft: dict) -> dict:
        meta = draft.get("meta", {})
        return {
            "title": draft.get("title", ""),
            "major": meta.get("major", ""),
            "paper_type": meta.get("paper_type", "课程论文"),
            "word_count": meta.get("word_count", 3000),
            "special_requirements": meta.get("special_requirements"),
            "keywords": meta.get("keywords", []),
            "reference_style": meta.get("reference_style", "gb7714"),
            "references": draft.get("references", []),
        }

    # -- 构建 --------------------------------------------------------------

    def build(self, paper_info: dict, model_id: str | None = None,
              require_confirmation: bool = False) -> dict:
        """根据论文信息构建草稿（生成三级大纲 + 每叶主旨）。"""
        with self.lock:
            ctx = self._model_ctx(model_id)
            if ctx:
                with ctx:
                    sections, outline_meta = outline_mod.build_outline_with_meta(paper_info)
            else:
                sections, outline_meta = outline_mod.build_outline_with_meta(paper_info)
            role_validation = OutlineRoleValidator.validate(paper_info, sections)
            outline_meta["role_validation"] = role_validation
            outline_meta["role_repair_attempts"] = 0
            outline_meta["role_base_confirmation_required"] = require_confirmation
            outline_meta["confirmation_required"] = require_confirmation or role_validation["requires_repair"]
            outline_meta["confirmed"] = not outline_meta["confirmation_required"]
            if not outline_meta["confirmation_required"]:
                outline_meta["confirmed_at"] = "legacy_or_direct_build"
            target_body_chars = max(int(paper_info.get("word_count", 3000)), 500)
            _apply_leaf_budgets(sections, target_body_chars)
            draft = {
                "title": paper_info.get("title", ""),
                "meta": {
                    "major": paper_info.get("major", ""),
                    "paper_type": paper_info.get("paper_type", "课程论文"),
                    "word_count": target_body_chars,
                    "completion_min_chars": int(target_body_chars * 0.95),
                    "special_requirements": paper_info.get("special_requirements"),
                    "keywords": paper_info.get("keywords", []),
                    "reference_style": paper_info.get("reference_style", "gb7714"),
                },
                "abstract": {"zh": paper_info.get("abstract") or "", "en": ""},
                "keywords": {"zh": paper_info.get("keywords") or [], "en": []},
                "acknowledgement": "",
                "references": list(paper_info.get("references") or []),
                "outline_meta": outline_meta,
                "sections": sections,
                "generating": False,
                "progress": 0,
                "done": 0,
                "total": len(_leaf_ids(sections)),
                "word_stats": {
                    "target": target_body_chars,
                    "minimum": int(target_body_chars * 0.95),
                    "actual": 0,
                    "shortfall": target_body_chars,
                },
            }
            self.save(draft)
            return draft

    # -- 大纲确认与结构编辑 ------------------------------------------------

    def outline_meta(self) -> dict:
        draft = self.load()
        return dict(draft.get("outline_meta") or {})

    def ensure_outline_confirmed(self) -> None:
        meta = self.outline_meta()
        if meta.get("confirmation_required") and not meta.get("confirmed"):
            role = meta.get("role_validation") or {}
            if role.get("requires_user_confirmation"):
                raise ValueError("大纲章节职责异常；请在大纲确认页核对后明确确认，或重新生成目录。")
            raise ValueError("请先在大纲确认页核对并确认目录后，再生成正文。")

    def validate_outline_roles_before_full_generation(self, model_id: str | None = None) -> dict:
        """全文启动前的唯一职责校验入口。

        首次发现严重职责异常时仅自动修复一次；修复后仍异常则写回可解释状态，
        由用户在大纲确认页显式确认，禁止悄然继续全文生成。
        """
        with self.lock:
            draft = self.load()
            paper_info = self._paper_info(draft)
            meta = dict(draft.get("outline_meta") or {})
            validation = OutlineRoleValidator.validate(paper_info, draft.get("sections") or [])
            previous = dict(meta.get("role_validation") or {})
            if validation["valid"] or not validation["requires_repair"] or previous.get("user_confirmed"):
                validation["user_confirmed"] = bool(previous.get("user_confirmed"))
                meta["role_validation"] = validation
                draft["outline_meta"] = meta
                self.save(draft)
                status = "valid" if validation["valid"] else ("user_confirmed" if previous.get("user_confirmed") else "warning")
                return {"status": status, "validation": validation}

            attempts = int(meta.get("role_repair_attempts") or 0)
            if attempts < 1:
                repair_info = dict(paper_info)
                original = str(repair_info.get("special_requirements") or "")
                repair_info["special_requirements"] = (original + "\n" + OutlineRoleValidator.repair_instruction(validation)).strip()
                version = int(meta.get("version") or 1) + 1
                ctx = self._model_ctx(model_id)
                if ctx:
                    with ctx:
                        sections, repaired_meta = outline_mod.build_outline_with_meta(repair_info, version=version)
                else:
                    sections, repaired_meta = outline_mod.build_outline_with_meta(repair_info, version=version)
                repaired_validation = OutlineRoleValidator.validate(paper_info, sections)
                repaired_meta["role_validation"] = repaired_validation
                repaired_meta["role_repair_attempts"] = 1
                repaired_meta["role_base_confirmation_required"] = bool(meta.get("role_base_confirmation_required", meta.get("confirmation_required", False)))
                repaired_meta["role_repaired_at"] = now()
                if repaired_validation["valid"]:
                    _apply_leaf_budgets(sections, int(paper_info["word_count"]))
                    repaired_meta["confirmation_required"] = repaired_meta["role_base_confirmation_required"]
                    repaired_meta["confirmed"] = not repaired_meta["confirmation_required"]
                    if repaired_meta["confirmed"]:
                        repaired_meta["confirmed_at"] = "role_repair_validated"
                    draft["sections"] = sections
                    draft["outline_meta"] = repaired_meta
                    draft["total"] = len(_leaf_ids(sections))
                    draft["done"] = 0
                    draft["progress"] = 0
                    self.save(draft)
                    return {"status": "repaired", "validation": repaired_validation}
                meta = repaired_meta
                draft["sections"] = sections
                draft["total"] = len(_leaf_ids(sections))

            validation = meta.get("role_validation") or validation
            validation["requires_user_confirmation"] = True
            meta["role_validation"] = validation
            meta["role_repair_attempts"] = max(1, int(meta.get("role_repair_attempts") or 0))
            meta["confirmation_required"] = True
            meta["confirmed"] = False
            meta["role_repair_failed"] = True
            draft["outline_meta"] = meta
            self.save(draft)
            raise ValueError("大纲职责校验连续两次未通过；请在大纲确认页调整目录后明确确认，系统不会自动生成全文。")

    def confirm_outline(self) -> dict:
        with self.lock:
            draft = self.load()
            meta = dict(draft.get("outline_meta") or {})
            paper_info = self._paper_info(draft)
            validation = OutlineRoleValidator.validate(paper_info, draft.get("sections") or [])
            previous = dict(meta.get("role_validation") or {})
            validation["user_confirmed"] = bool(validation["requires_user_confirmation"])
            if validation["requires_user_confirmation"]:
                validation["user_confirmation_note"] = "用户在大纲确认页确认带职责风险的目录。"
            elif previous.get("user_confirmed"):
                validation["user_confirmed"] = True
            meta["role_validation"] = validation
            meta["confirmation_required"] = True
            meta["confirmed"] = True
            from datetime import datetime, timezone
            meta["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            draft["outline_meta"] = meta
            self.save(draft)
            return meta

    def regenerate_outline(self, model_id: str | None = None) -> dict:
        with self.lock:
            draft = self.load()
            if _body_char_count(draft) > 0:
                raise ValueError("正文已开始生成，不能直接重生成大纲；请新建任务或先清空正文。")
            paper_info = self._paper_info(draft)
            old_meta = dict(draft.get("outline_meta") or {})
            version = int(old_meta.get("version") or 1) + 1
            ctx = self._model_ctx(model_id)
            if ctx:
                with ctx:
                    sections, meta = outline_mod.build_outline_with_meta(paper_info, version=version)
            else:
                sections, meta = outline_mod.build_outline_with_meta(paper_info, version=version)
            _apply_leaf_budgets(sections, int(paper_info["word_count"]))
            role_validation = OutlineRoleValidator.validate(paper_info, sections)
            meta["role_validation"] = role_validation
            meta["role_repair_attempts"] = 0
            meta["role_base_confirmation_required"] = True
            meta["confirmation_required"] = True
            meta["confirmed"] = False
            draft["sections"] = sections
            draft["outline_meta"] = meta
            draft["total"] = len(_leaf_ids(sections))
            draft["done"] = 0
            draft["progress"] = 0
            self.save(draft)
            return draft

    def _assert_outline_editable(self, draft: dict) -> None:
        if _body_char_count(draft) > 0:
            raise ValueError("正文已开始生成，不能修改目录结构；仍可修改章节标题与主旨。")

    def _reindex_outline(self, sections: list[dict]) -> list[dict]:
        nodes = {str(item.get("id")): dict(item) for item in sections}
        children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        roots: list[str] = []
        for node_id in nodes:
            parent_id = node_id.rsplit("-", 1)[0] if "-" in node_id else ""
            if parent_id in nodes:
                children[parent_id].append(node_id)
            else:
                roots.append(node_id)
        ordered: list[dict] = []
        def walk(old_id: str, parent: str, index: int) -> None:
            node = nodes[old_id]
            level = 1 if not parent else min(int(node.get("level") or parent.count("-") + 2), 3)
            new_id = str(index + 1) if not parent else f"{parent}-{index + 1}"
            number = f"第{['零','一','二','三','四','五','六','七','八','九','十'][index + 1] if index < 10 else index + 1}章" if not parent else new_id.replace("-", ".")
            node.update({"id": new_id, "number": number, "level": level, "children": []})
            ordered.append(node)
            for child_index, child_id in enumerate(children.get(old_id, [])):
                walk(child_id, new_id, child_index)
        for root_index, root_id in enumerate(roots):
            walk(root_id, "", root_index)
        return ordered

    def add_outline_section(self, title: str, gist: str = "", parent_id: str | None = None) -> dict:
        with self.lock:
            draft = self.load()
            self._assert_outline_editable(draft)
            sections = list(draft.get("sections") or [])
            if parent_id and not any(item.get("id") == parent_id for item in sections):
                raise ValueError("父章节不存在。")
            level = 1 if not parent_id else min(next(int(item.get("level") or 1) for item in sections if item.get("id") == parent_id) + 1, 3)
            if parent_id and level > 3:
                raise ValueError("当前仅支持三级目录。")
            temp_id = f"new-{uuid.uuid4().hex[:8]}"
            sections.append({"id": temp_id, "number": "", "title": title.strip(), "level": level, "gist": gist.strip(), "paragraphs": [], "children": [], "_parent": parent_id or ""})
            # 临时 parent 用于构树；转换成可识别的虚拟层级关系后重排。
            if parent_id:
                sections[-1]["id"] = f"{parent_id}-999"
            sections = self._reindex_outline(sections)
            _apply_leaf_budgets(sections, int((draft.get("meta") or {}).get("word_count", 3000)))
            draft["sections"] = sections
            draft["total"] = len(_leaf_ids(sections))
            self.save(draft)
            return sections[-1]

    def delete_outline_section(self, section_id: str) -> None:
        with self.lock:
            draft = self.load()
            self._assert_outline_editable(draft)
            sections = list(draft.get("sections") or [])
            kept = [item for item in sections if item.get("id") != section_id and not str(item.get("id")).startswith(section_id + "-")]
            if len(kept) == len(sections):
                raise ValueError("章节不存在。")
            if not kept:
                raise ValueError("目录至少保留一个章节。")
            kept = self._reindex_outline(kept)
            _apply_leaf_budgets(kept, int((draft.get("meta") or {}).get("word_count", 3000)))
            draft["sections"] = kept
            draft["total"] = len(_leaf_ids(kept))
            self.save(draft)

    # -- 段落 / 小节操作 ----------------------------------------------------

    def _find_section(self, draft: dict, section_id: str) -> dict:
        for s in draft["sections"]:
            if s["id"] == section_id:
                return s
        raise ValueError(f"小节不存在: {section_id}")

    def _next_paragraph_id(self, section: dict) -> str:
        return f"p{len(section['paragraphs']) + 1}-{uuid.uuid4().hex[:6]}"

    def add_paragraph(self, section_id: str, text: str = "") -> dict:
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            para = {"id": self._next_paragraph_id(section), "text": text}
            section["paragraphs"].append(para)
            self.save(draft)
            return para

    def update_paragraph(self, pid: str, text: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                for p in s["paragraphs"]:
                    if p["id"] == pid:
                        p["text"] = text
                        self.save(draft)
                        return
            raise ValueError(f"段落不存在: {pid}")

    def delete_paragraph(self, pid: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                before = len(s["paragraphs"])
                s["paragraphs"] = [p for p in s["paragraphs"] if p["id"] != pid]
                if len(s["paragraphs"]) != before:
                    self.save(draft)
                    return
            raise ValueError(f"段落不存在: {pid}")

    def move_paragraph(self, pid: str, direction: str) -> None:
        with self.lock:
            draft = self.load()
            for s in draft["sections"]:
                paras = s["paragraphs"]
                idx = next((i for i, p in enumerate(paras) if p["id"] == pid), None)
                if idx is None:
                    continue
                target = idx - 1 if direction == "up" else idx + 1
                if target < 0 or target >= len(paras):
                    return
                paras[idx], paras[target] = paras[target], paras[idx]
                self.save(draft)
                return
            raise ValueError(f"段落不存在: {pid}")

    def update_section(self, section_id: str, title: str | None = None,
                       gist: str | None = None) -> None:
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            if title is not None:
                section["title"] = title
            if gist is not None:
                section["gist"] = gist
            self.save(draft)

    # -- AI 生成 ------------------------------------------------------------

    def _previous_summaries(self, draft: dict, section_id: str) -> str:
        """收集当前小节之前所有已生成内容的摘要（避免重复）。"""
        summaries: list[str] = []
        for s in draft["sections"]:
            for p in s["paragraphs"]:
                text = (p.get("text") or "").strip()
                if text:
                    summaries.append(f"{s['number']} {s['title']}：{text[:120]}")
            if s["id"] == section_id:
                break
        return "\n".join(summaries)

    def _refs_text(self, draft: dict) -> str:
        refs = draft.get("references") or []
        return "\n".join(f"[{i + 1}] {r}" for i, r in enumerate(refs)) or "（无）"

    def _model_ctx(self, model_id: str | None):
        model_cfg = model_service.resolve_model(model_id)
        if model_cfg:
            return deepseek.connection(model_cfg)
        return None

    def generate_section(self, section_id: str, model_id: str | None = None) -> dict:
        """生成一个章节，并在文本进入 ``draft.json`` 前执行阻断式质量校验。

        首次命中 Markdown、调试残片、重复标题、重复短语或异常长度时，仅执行
        一次受控重试。第二次仍不合格时不写入任何正文 Block，而是在 section
        上记录 ``generation_status=quality_blocked``，由全文流水线继续处理其余章节。
        """
        with self.lock:
            draft = self.load()
            self.ensure_outline_confirmed()
            section = self._find_section(draft, section_id)
            if not (section.get("gist") or "").strip():
                raise ValueError(f"小节「{section['title']}」没有段落主旨，请先填写主旨")
            paper = self._paper_info(draft)
            if not section.get("target_chars"):
                _apply_leaf_budgets(draft["sections"], int(paper["word_count"]))
                section = self._find_section(draft, section_id)
            target_chars = max(int(section.get("target_chars") or 300), 180)
            min_chars = min(
                target_chars,
                max(int(section.get("min_chars") or target_chars * 0.88), 160),
            )
            user = _prompt("section_generate.txt").format(
                title=paper["title"], major=paper["major"],
                paper_type=paper["paper_type"],
                number=section["number"], section_title=section["title"],
                gist=section.get("gist", ""),
                outline=outline_mod.outline_text(draft["sections"]),
                previous_summaries=self._previous_summaries(draft, section_id) or "（无）",
                references=self._refs_text(draft),
                target_chars=target_chars,
                min_chars=min_chars,
            )
            section_title = str(section["title"])

        ctx = self._model_ctx(model_id)
        quality_issues: list[dict] = []
        model_error = ""
        segments: list[str] = []
        attempts = 0
        for attempt in (1, 2):
            attempts = attempt
            messages = [
                {"role": "system", "content": deepseek_service.system_prompt()},
                {"role": "user", "content": user},
            ]
            if attempt == 2:
                messages.append({
                    "role": "user",
                    "content": (
                        "上一轮正文未通过入库质量检查。请只输出当前小节的正式学术正文："
                        "不得输出 Markdown 标题、代码围栏、debug/reasoning/analysis、JSON、"
                        "解释文字或任何重复标题；不得复述句子。只返回 2—5 个自然段。"
                    ),
                })
            try:
                if ctx:
                    with ctx:
                        text = deepseek.chat(messages)
                else:
                    text = f"（未配置 AI 模型）{section_title}：请配置模型后生成。"
                assert_generated_body(text, target_chars=target_chars)
                segments = _clean_generated_paragraphs(text)
                if not segments:
                    raise GeneratedBodyQualityError([{
                        "code": "empty_cleaned_body", "message": "清洗后未保留可用正文。"
                    }])
                quality_issues = []
                break
            except GeneratedBodyQualityError as exc:
                quality_issues = list(exc.issues)
                continue
            except deepseek.DeepSeekError as exc:
                model_error = str(exc)
                quality_issues = [{"code": "model_error", "message": f"模型调用失败：{exc}"}]
                break

        if not segments:
            with self.lock:
                draft = self.load()
                blocked = self._find_section(draft, section_id)
                blocked["generation_status"] = "quality_blocked"
                blocked["generation_attempt_count"] = attempts
                blocked["generation_quality_issues"] = quality_issues
                if model_error:
                    blocked["generation_error"] = model_error
                self.save(draft)
            return {
                "id": "", "type": "generation_failed", "status": "quality_blocked",
                "section_id": section_id, "attempt_count": attempts,
                "quality_issues": quality_issues,
            }

        with self.lock:
            draft = self.load()
            target = self._find_section(draft, section_id)
            para = {
                "id": self._next_paragraph_id(target), "text": segments[0],
                "generation_quality": {"attempt_count": attempts, "status": "passed"},
            }
            target.setdefault("paragraphs", []).append(para)
            for seg in segments[1:]:
                target["paragraphs"].append({
                    "id": self._next_paragraph_id(target), "text": seg,
                    "generation_quality": {"attempt_count": attempts, "status": "passed"},
                })
            target["generation_status"] = "generated"
            target["generation_attempt_count"] = attempts
            target.pop("generation_quality_issues", None)
            target.pop("generation_error", None)
            self.save(draft)
        return para

    def _section_char_count(self, section: dict) -> int:
        return sum(
            _effective_text_length(str(paragraph.get("text") or ""))
            for paragraph in section.get("paragraphs") or []
        )

    def _supplement_section(self, section_id: str, requested_chars: int,
                            model_id: str | None = None) -> int:
        """仅向字数不足的小节追加新论证，不覆盖既有或用户编辑的文本。"""
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            paper = self._paper_info(draft)
            current_text = "\n".join(
                str(paragraph.get("text") or "").strip()
                for paragraph in section.get("paragraphs") or []
                if str(paragraph.get("text") or "").strip()
            )
            target = max(int(section.get("target_chars") or requested_chars), requested_chars)
            requested = min(max(int(requested_chars), 160), 1200)
            user = (
                f"论文题目：{paper['title']}\n专业方向：{paper['major']}\n"
                f"当前小节：{section['number']} {section['title']}\n"
                f"小节主旨：{section.get('gist', '')}\n"
                f"当前已写正文：\n{current_text}\n\n"
                f"该小节目标约 {target} 字，目前仍需补充约 {requested} 字。"
                "请只新增 2—4 个自然段的学术论证，补足尚未覆盖的概念、机制、依据、分析或小结；"
                "不得复述当前文本，不得编造数据、表格、参考文献或实验结论，不得输出标题、列表、Markdown 或说明文字。"
            )
        ctx = self._model_ctx(model_id)
        if not ctx:
            return 0
        try:
            with ctx:
                generated = deepseek.chat(
                    [{"role": "system", "content": deepseek_service.system_prompt()},
                     {"role": "user", "content": user}]
                )
            segments = _clean_generated_paragraphs(generated)
        except deepseek.DeepSeekError:
            return 0
        if not segments:
            return 0
        with self.lock:
            draft = self.load()
            section = self._find_section(draft, section_id)
            for segment in segments:
                section["paragraphs"].append(
                    {"id": self._next_paragraph_id(section), "text": segment}
                )
            self._refresh_word_stats(draft)
            self.save(draft)
        return sum(_effective_text_length(segment) for segment in segments)

    def _deficient_leaf_sections(self, draft: dict) -> list[dict]:
        leaf_ids = _leaf_ids(draft.get("sections") or [])
        rows = []
        for section in draft.get("sections") or []:
            if section.get("id") not in leaf_ids:
                continue
            target = max(int(section.get("target_chars") or 180), 180)
            rows.append((target - self._section_char_count(section), section))
        return [section for deficit, section in sorted(rows, key=lambda row: row[0], reverse=True) if deficit > 0]

    def generate_acknowledgement(self, model_id: str | None = None) -> str:
        """生成致谢。"""
        with self.lock:
            draft = self.load()
            paper = self._paper_info(draft)
            user = (f"论文题目：{paper['title']}\n专业：{paper['major']}\n"
                    "请生成 150-250 字的论文致谢（学术语体，感谢导师、同学与家人）。"
                    "只输出致谢文本。")
        ctx = self._model_ctx(model_id)
        try:
            if ctx:
                with ctx:
                    text = deepseek.chat(
                        [{"role": "system",
                          "content": deepseek_service.system_prompt()},
                         {"role": "user", "content": user}])
            else:
                text = "（未配置 AI 模型）"
            text = text.strip()
        except deepseek.DeepSeekError as exc:
            text = f"（生成失败：{exc}）"
        with self.lock:
            draft = self.load()
            draft["acknowledgement"] = text
            self.save(draft)
        return text

    def generate_en_abstract(self, model_id: str | None = None) -> str:
        """根据中文摘要生成英文摘要（自动拆分关键词到 keywords.en）。"""
        with self.lock:
            draft = self.load()
            zh = draft.get("abstract", {}).get("zh", "")
            user = (
                "请将以下中文摘要翻译为英文，并给出英文关键词。最终回复只能包含两行英文，"
                "第一行必须为 `Abstract: ` 加英文摘要，第二行必须为 `Keywords: ` 加 3—5 个英文关键词（英文逗号分隔）。"
                "不得输出中文，不得输出思考、计划、格式说明、占位符或任何额外文字。\n\n"
                f"中文摘要：\n{zh}"
            )
        ctx = self._model_ctx(model_id)
        try:
            if ctx:
                with ctx:
                    text = deepseek.chat(
                        [{"role": "system",
                          "content": deepseek_service.system_prompt()},
                         {"role": "user", "content": user}])
            else:
                text = "（未配置 AI 模型）"
            text = text.strip()
        except deepseek.DeepSeekError as exc:
            text = f"（生成失败：{exc}）"
        abstract_en, keywords_en = _split_en_abstract(text)
        with self.lock:
            draft = self.load()
            draft["abstract"]["en"] = abstract_en
            if keywords_en:
                draft.setdefault("keywords", {})["en"] = keywords_en
            self.save(draft)
        return abstract_en

    def oneclick(self, model_id: str | None = None,
                 progress_cb=None) -> dict:
        """一键全文：生成正文、补足字数，并补齐缺失的英文摘要与致谢。"""
        with self.lock:
            draft = self.load()
            target_chars = max(int((draft.get("meta") or {}).get("word_count", 3000)), 500)
            _apply_leaf_budgets(draft["sections"], target_chars)
            draft.update(generating=True, progress=0, done=0,
                         total=len(_leaf_ids(draft["sections"])),
                         word_status="generating", supplement_rounds=0)
            self._refresh_word_stats(draft)
            self.save(draft)

        leaf = sorted(
            [section for section in draft["sections"]
             if section["id"] in _leaf_ids(draft["sections"])],
            key=lambda section: section["id"],
        )
        done = 0
        for section in leaf:
            try:
                if (section.get("gist") or "").strip():
                    self.generate_section(section["id"], model_id)
            except Exception:  # noqa: BLE001
                pass
            done += 1
            with self.lock:
                current = self.load()
                current["progress"] = min(80, int(done / max(1, len(leaf)) * 80))
                current["done"] = done
                current["generating"] = True
                self._refresh_word_stats(current)
                self.save(current)
            if progress_cb:
                progress_cb(done, len(leaf))

        # 最多两轮：按小节缺口从大到小补写，避免无限扩写或覆盖已有正文。
        rounds = 0
        for round_index in range(2):
            with self.lock:
                current = self.load()
                stats = self._refresh_word_stats(current)
                if stats["actual"] >= stats["minimum"]:
                    self.save(current)
                    break
                current["word_status"] = "supplementing"
                current["supplement_rounds"] = round_index + 1
                current["progress"] = 80 + round_index * 8
                candidates = self._deficient_leaf_sections(current)
                self.save(current)
            if not candidates:
                break
            rounds = round_index + 1
            for section in candidates:
                with self.lock:
                    latest = self.load()
                    latest_stats = self._refresh_word_stats(latest)
                    if latest_stats["actual"] >= latest_stats["minimum"]:
                        self.save(latest)
                        break
                    fresh_section = self._find_section(latest, section["id"])
                    deficit = max(int(fresh_section.get("target_chars") or 0)
                                  - self._section_char_count(fresh_section), 0)
                    global_share = max(
                        160,
                        (latest_stats["minimum"] - latest_stats["actual"]
                         + max(1, len(candidates)) - 1) // max(1, len(candidates)),
                    )
                if deficit > 0:
                    self._supplement_section(
                        section["id"], min(max(deficit, global_share), 1200), model_id
                    )

        with self.lock:
            draft = self.load()
            needs_en_abstract = not (draft.get("abstract", {}).get("en") or "").strip()
            needs_acknowledgement = not (draft.get("acknowledgement") or "").strip()

        # 一键全文应交付完整稿件；已有用户手动内容时不覆盖。
        if needs_en_abstract:
            self.generate_en_abstract(model_id)
        if needs_acknowledgement:
            self.generate_acknowledgement(model_id)

        with self.lock:
            draft = self.load()
            stats = self._refresh_word_stats(draft)
            meets_minimum = stats["actual"] >= stats["minimum"]
            draft["generating"] = False
            draft["supplement_rounds"] = rounds
            draft["word_status"] = "completed" if meets_minimum else "shortfall"
            draft["progress"] = 100 if meets_minimum else 98
            self.save(draft)
        if self.task_manager:
            message = (
                "全文生成完成，字数已达标"
                if meets_minimum
                else f"正文仍差 {stats['shortfall']} 字，可继续补写"
            )
            self.task_manager.update(
                self.task_id,
                progress=100 if meets_minimum else 98,
                status=TaskStatus.completed,
                message=message,
            )
        return self.load()

    def oneclick_stream(self, model_id: str | None = None) -> Iterator[dict]:
        """按小节串行生成，并实时产出 AI 文本片段。"""
        with self.lock:
            draft = self.load()
            draft.update(generating=True, progress=0, done=0,
                         total=len(_leaf_ids(draft["sections"])))
            self.save(draft)
        leaf = [s for s in draft["sections"] if s["id"] in _leaf_ids(draft["sections"])]
        total = len(leaf)
        for index, section in enumerate(leaf):
            if not (section.get("gist") or "").strip():
                continue
            sid = section["id"]
            with self.lock:
                current = self.load()
                sec = self._find_section(current, sid)
                paper = self._paper_info(current)
                prompt = _prompt("section_generate.txt").format(
                    title=paper["title"], major=paper["major"], paper_type=paper["paper_type"],
                    number=sec["number"], section_title=sec["title"], gist=sec.get("gist", ""),
                    outline=outline_mod.outline_text(current["sections"]),
                    previous_summaries=self._previous_summaries(current, sid) or "（无）",
                    references=self._refs_text(current))
                pid = self._next_paragraph_id(sec)
                sec["paragraphs"].append({"id": pid, "text": ""})
                self.save(current)
            ctx = self._model_ctx(model_id)
            try:
                if ctx:
                    with ctx:
                        chunks = deepseek.chat_stream([
                            {"role": "system", "content": deepseek_service.system_prompt()},
                            {"role": "user", "content": prompt}])
                        for chunk in chunks:
                            with self.lock:
                                current = self.load()
                                target = self._find_section(current, sid)
                                target["paragraphs"][-1]["text"] += chunk
                                self.save(current)
                            yield {"type": "chunk", "section_id": sid, "text": chunk}
                else:
                    text = f"（未配置 AI 模型）{section['title']}：请配置模型后生成。"
                    with self.lock:
                        current = self.load()
                        self._find_section(current, sid)["paragraphs"][-1]["text"] = text
                        self.save(current)
                    yield {"type": "chunk", "section_id": sid, "text": text}
            except deepseek.DeepSeekError as exc:
                yield {"type": "error", "section_id": sid, "message": str(exc)}
            with self.lock:
                current = self.load()
                current.update(done=index + 1,
                               progress=int((index + 1) / max(1, total) * 100),
                               generating=index + 1 < total)
                self.save(current)
            yield {"type": "section_done", "done": index + 1, "total": total,
                   "progress": int((index + 1) / max(1, total) * 100)}

        # 一键全文收尾时自动补充英文摘要。
        yield {"type": "stage", "stage": "english_abstract",
               "message": "正在生成英文摘要..."}
        try:
            english_abstract = self.generate_en_abstract(model_id)
            yield {"type": "english_abstract", "text": english_abstract}
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "stage": "english_abstract",
                   "message": f"英文摘要生成失败：{exc}"}
        with self.lock:
            current = self.load()
            current.update(generating=False, progress=100)
            self.save(current)
        yield {"type": "completed", "done": total, "total": total, "progress": 100}

    # -- 导出 --------------------------------------------------------------

    def export(self, template_path: Path | None = None,
               template_id: str | None = None) -> list[str]:
        """把草稿组装为 spec 并格式化出 docx。"""
        with self.lock:
            draft = self.load()
            # Export is the final consistency boundary: regenerate every stale
            # table-backed chart before its asset is embedded in the DOCX.
            for section in walk_sections(draft.get("sections") or []):
                for block in section.get("paragraphs") or []:
                    if block.get("type") != "chart":
                        continue
                    binding = (block.get("chart_spec") or {}).get("binding") or {}
                    if binding.get("source_table_id") and (
                        block.get("status") == "stale"
                        or not (block.get("asset") or {}).get("png_path")
                    ):
                        recompute_chart_block(draft, self.task_dir, block)
            # ResearchObject is the sole numbering authority.  It persists global
            # Figure/Table numbers before spec construction so editor and DOCX share
            # exactly the same domain facts, including old drafts without numbers.
            storage_settings = self._storage_settings()
            renumber_document_references(self.task_id, storage_settings, draft)
            self.save(draft)
        paper = self._paper_info(draft)
        # Text in structured references is resolved from target_object_id after
        # renumbering; cached labels are never treated as DOCX source-of-truth.
        cross_reference_text = CrossReferenceService(storage_settings).render_draft_text(self.task_id, draft)
        literature_service = LiteratureService(storage_settings)
        literature_citation_text = literature_service.render_draft_text(self.task_id, draft)
        cross_reference_records = {item["id"]: item for item in CrossReferenceService(storage_settings).list(self.task_id)}
        literature_citation_records = {item["id"]: item for item in literature_service.citations(self.task_id)}
        def render_structured_text(block: dict) -> str:
            content = block.get("content")
            if not isinstance(content, list):
                return str(block.get("text") or "")
            fragments: list[str] = []
            for item in content:
                if item.get("type") == "text":
                    fragments.append(str(item.get("text") or ""))
                elif item.get("type") == "cross_reference":
                    fragments.append(str((cross_reference_records.get(str(item.get("reference_id"))) or {}).get("resolved_label") or "[引用对象不存在]"))
                elif item.get("type") == "literature_citation":
                    fragments.append(str((literature_citation_records.get(str(item.get("citation_id"))) or {}).get("resolved_label") or "[引用文献不存在]"))
            return "".join(fragments)
        # Phase 6C remains read-only: export records stale-source warnings but
        # never silently reruns analyses, changes results or rewrites findings.
        impact_warnings = (
            DependencyGraphService(storage_settings).export_warnings(self.task_id)
            if self.task_dir == storage_settings.output_dir / self.task_id else []
        )
        if impact_warnings:
            draft["export_warnings"] = {"generated_at": now(), "warnings": impact_warnings}
            self.save(draft)

        spec_sections: list[dict] = []

        for s in draft["sections"]:
            htype = {1: "h1", 2: "h2", 3: "h3"}.get(s["level"], "h2")
            spec_sections.append({"type": htype, "text": f"{s['number']} {s['title']}"})
            for p in s["paragraphs"]:

                # Structured draft block export: editor and Word share the same stored block.
                kind = p.get("type", "paragraph")
                if kind == "literature_citation":
                    text = literature_citation_text.get(str(p.get("id")), render_structured_text(p)).strip()
                    if text:
                        spec_sections.append({"type": "p", "text": text})
                    continue
                if kind == "cross_reference" or kind == "discussion" or isinstance(p.get("content"), list):
                    text = render_structured_text(p).strip()
                    if text:
                        spec_sections.append({"type": "p", "text": text})
                    continue

                if kind == "insight":
                    # semantic-insight export adapter: retain evidence-first summaries
                    # as a readable table or caption in the existing DOCX pipeline.
                    insight_kind = str(p.get("kind") or "")
                    title = str(p.get("title") or "章节要点归纳")
                    caption = str(p.get("caption") or "")
                    source_status = str(p.get("source_status") or "text_synthesis")
                    if insight_kind == "chart":
                        chart = p.get("chart") or {}
                        if chart.get("kind") == "pie":
                            headers = ["类别", "数值"]
                            rows = [[str(item.get("name") or ""), str(item.get("value") or "")] for item in (chart.get("pie") or [])]
                        else:
                            series = chart.get("series") or []
                            headers = ["类别"] + [str(item.get("name") or "指标") for item in series]
                            rows = []
                            for index, category in enumerate(chart.get("categories") or []):
                                rows.append([str(category)] + [str((item.get("values") or [])[index]) if len(item.get("values") or []) > index else "" for item in series])
                        if rows:
                            spec_sections.append({"type": "table", "title": f"图表数据：{title}", "headers": headers, "rows": rows})
                    elif insight_kind in {"three_line_table", "comparison_table", "problem_solution_table", "method_table"}:
                        table = p.get("table") or {}
                        headers = [str(item) for item in (table.get("headers") or [])]
                        rows = [[str(cell) for cell in row] for row in (table.get("rows") or [])]
                        if headers and rows:
                            spec_sections.append({"type": "table", "title": title, "headers": headers, "rows": rows})
                    elif insight_kind == "framework_diagram":
                        labels = [str(item.get("label") or "") for item in ((p.get("framework") or {}).get("nodes") or [])]
                        if labels:
                            spec_sections.append({"type": "p", "text": "研究结构：" + " → ".join(labels)})
                    evidence = p.get("evidence") or []
                    evidence_note = "；".join(str(item.get("excerpt") or "")[:80] for item in evidence[:3] if item.get("excerpt"))
                    disclosure = "数据来源：用户维护的数据表。" if source_status == "user_data" else "内容归纳基于论文目录与已列正文证据，不代表统计结论。"
                    spec_sections.append({"type": "p", "text": f"{title}。{caption}{disclosure}{(' 证据：' + evidence_note) if evidence_note else ''}"})
                # semantic-insight export adapter
                elif kind == "chart":
                    # ChartSpec v2 owns a real PNG/SVG ChartAsset. Export its
                    # PNG as a native FigureBlock so both DOCX renderers embed it.
                    asset = p.get("asset") or {}
                    png_path = str(asset.get("png_path") or "")
                    chart = p.get("chart") or {}
                    chart_title = str(p.get("title") or chart.get("title") or "图表")
                    raw_figure_number = p.get("figure_number")
                    try:
                        figure_number = f"图{int(raw_figure_number)}" if int(raw_figure_number) > 0 else "图"
                    except (TypeError, ValueError):
                        figure_number = "图"
                    caption = str(p.get("caption") or chart.get("caption") or "")
                    if png_path and (self.task_dir / png_path).is_file():
                        spec_sections.append({
                            "type": "figure",
                            "path": png_path,
                            "title": f"{figure_number} {chart_title}",
                            "chart_id": p.get("id"),
                            "asset_id": asset.get("id"),
                        })
                        source_note = ((p.get("chart_spec") or {}).get("provenance") or {}).get("source_note")
                        if caption or source_note:
                            spec_sections.append({"type": "p", "text": "".join(value for value in [caption, source_note] if value)})
                    else:
                        # Preserve legacy charts that predate the asset service.
                        if chart.get("kind") == "pie":
                            headers = ["类别", "数值"]
                            rows = [[str(item.get("name") or ""), str(item.get("value") or "")] for item in (chart.get("pie") or [])]
                        else:
                            categories = [str(item) for item in (chart.get("categories") or [])]
                            series = chart.get("series") or []
                            headers = ["类别"] + [str(item.get("name") or "指标") for item in series]
                            rows = [[category] + [str((item.get("values") or [])[index]) if len(item.get("values") or []) > index else "" for item in series] for index, category in enumerate(categories)]
                        if rows:
                            spec_sections.append({"type": "table", "title": f"图表数据：{chart_title}", "headers": headers, "rows": rows})
                        spec_sections.append({"type": "p", "text": f"{figure_number}：{chart_title}。{caption}"})
                # chart-block export adapter
                elif kind == "table":
                    raw_table_number = p.get("table_number")
                    try:
                        table_label = f"表{int(raw_table_number)}" if int(raw_table_number) > 0 else "表"
                    except (TypeError, ValueError):
                        table_label = "表"
                    table_title = str(p.get("title") or "数据表")
                    spec_sections.append({
                        "type": "table",
                        "title": f"{table_label} {table_title}",
                        "headers": list(p.get("headers") or []),
                        "rows": list(p.get("rows") or []),
                    })
                    source_note = "".join(str(value) for value in [p.get("source") or "", p.get("note") or ""])
                    if source_note:
                        spec_sections.append({"type": "p", "text": source_note})
                    continue

                if kind == "chart":
                    continue
                text = (p.get("text") or "").strip()
                if text:
                    spec_sections.append({"type": "p", "text": text})
        if (draft.get("acknowledgement") or "").strip():
            spec_sections.append({"type": "h1", "text": "致谢"})
            spec_sections.append({"type": "p", "text": draft["acknowledgement"]})
        refs = list(draft.get("references") or [])
        # Citation truth remains literature_id.  Only currently resolvable citations
        # contribute a minimal bibliography line; deleted Literature stays visible as
        # a broken in-text marker rather than being silently removed or invented.
        for literature in literature_service.reference_records(self.task_id):
            author_text = ", ".join(str(item) for item in literature.get("authors") or []) or "匿名"
            year = literature.get("year") or "n.d."
            doi = str(literature.get("doi") or "")
            line = f"{author_text}. {literature.get('title') or '未命名文献'}. {year}." + (f" DOI: {doi}" if doi else "")
            if line not in refs:
                refs.append(line)
        spec_sections.append({"type": "references", "items": refs})

        spec = {
            "meta": {
                "title": paper["title"],
                "abstract": draft.get("abstract", {}).get("zh", ""),
                "keywords": draft.get("keywords", {}).get("zh", []),
                # 模板渲染器使用 abstract_en / keywords_en 渲染英文摘要页。
                # 这里必须从草稿传递，不能只依赖导出阶段的自动翻译回退。
                "abstract_en": draft.get("abstract", {}).get("en", ""),
                "keywords_en": draft.get("keywords", {}).get("en", []),
                "reference_style": paper.get("reference_style", "gb7714"),
                "citation_style": "numeric",
            },
            "sections": spec_sections,
            "references": refs,
        }
        files = formatter_service.format_paper(
            self.task_id, self.task_dir, paper, spec,
            template_path=template_path, template_id=template_id
        )
        if self.task_manager:
            self.task_manager.update(
                self.task_id, progress=100, status=TaskStatus.completed,
                files=files, message="导出完成")
        return files
