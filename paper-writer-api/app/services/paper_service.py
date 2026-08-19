"""Paper generation orchestration.

The paper-writer *skill scripts* are imported at runtime (never copied) and act
as the core engine: parse_template / build_docx / plot_chart / references.
This service only wires the API request into the engine and collects outputs.
"""

import logging
import sys
from contextlib import nullcontext
from pathlib import Path

from app.config import Settings
from app.models.generate import GenerateRequest
from app.models.task import TaskStatus
from app.services import quality_service
from app.services.content_generator import build_spec
from app.services import history_service
from app.services import deepseek, deepseek_service
from app.services import model_service
from app.formatter.service import spec_from_paper_content
from app.formatter import service as formatter_service
from app.services.task_manager import TaskManager

logger = logging.getLogger(__name__)

ENGINE = {"mods": None}


class PaperService:
    def __init__(self, settings: Settings, task_manager: TaskManager):
        self.settings = settings
        self.task_manager = task_manager

    # -- engine access -------------------------------------------------------

    def engine(self):
        if ENGINE["mods"] is None:
            scripts = self.settings.paper_writer_scripts_dir
            if not scripts.exists():
                raise RuntimeError(
                    f"paper-writer 引擎脚本目录不存在: {scripts}。"
                    "请设置 PAPER_WRITER_SCRIPTS_DIR 指向 paper-writer skill 的 scripts 目录。"
                )
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            import build_docx  # noqa: F401
            import parse_template  # noqa: F401
            import references  # noqa: F401
            ENGINE["mods"] = (build_docx, parse_template, references)
            logger.info("paper-writer engine loaded from %s", scripts)
        return ENGINE["mods"]

    # -- task runner ---------------------------------------------------------

    def run_task(self, task_id: str) -> None:
        req = self._load_request(task_id)
        task_dir = self.settings.output_dir / task_id
        template_path = self.settings.upload_dir / f"{task_id}.docx"
        history_service.update_record(task_id, status="generating")
        self._step(task_id, 5, "初始化")

        # 草稿模式：只构建大纲草稿，由逐段生成编辑器驱动全文（不跑自动管线）
        if req.draft_mode:
            try:
                from app.draft.service import DraftService
                DraftService(task_id, task_dir, self.task_manager).build(
                    req.model_dump(), model_id=req.model_id, require_confirmation=True)
                files = self._list_outputs(task_dir)
                self.task_manager.update(
                    task_id, progress=100, status=TaskStatus.completed,
                    message="大纲草稿已生成，请确认大纲后进入正文编辑器",
                    files=files)
                history_service.update_record(
                    task_id, status="completed",
                    error=None, completed=True)
                history_service.update_record_progress(
                    task_id, current_stage="completed", progress=100)
                logger.info("Task %s draft outline built: %s", task_id, files)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Task %s draft build failed", task_id)
                history_service.update_record(
                    task_id, status="failed",
                    error=f"{type(exc).__name__}: {exc}")
                self.task_manager.update(
                    task_id, status=TaskStatus.failed,
                    error=f"{type(exc).__name__}: {exc}")
            return

        try:
            try:
                self._run(task_id, req, task_dir,
                          template_path if template_path.exists() else None)
            except deepseek.DeepSeekError:
                # 断点续传：分段生成失败时从检查点继续重跑一次
                logger.warning("DeepSeek 调用失败，执行一次断点续传重试")
                self._run(task_id, req, task_dir,
                          template_path if template_path.exists() else None)
            files = self._list_outputs(task_dir)
            self.task_manager.update(task_id, progress=100,
                                     status=TaskStatus.completed, files=files)
            history_service.update_record(task_id, status="completed",
                                          completed=True)
            history_service.update_record_progress(
                task_id, current_stage="completed", progress=100)
            logger.info("Task %s completed: %s", task_id, files)
        except Exception as exc:  # noqa: BLE001 - surfaced via status
            logger.exception("Task %s failed", task_id)
            history_service.update_record(task_id, status="failed",
                                          error=f"{type(exc).__name__}: {exc}")
            self.task_manager.update(task_id, status=TaskStatus.failed,
                                     error=f"{type(exc).__name__}: {exc}")

    def _run(self, task_id: str, req: GenerateRequest, task_dir: Path,
             template_path: Path | None) -> None:
        build_docx, parse_template, references = self.engine()
        task_dir.mkdir(parents=True, exist_ok=True)

        # ===== 第一阶段：论文内容生成（只生成内容，不处理格式）=====
        spec = None
        content_dir = task_dir / "paper_content"
        model_cfg = model_service.resolve_model(req.model_id)
        ctx = deepseek.connection(model_cfg) if model_cfg else nullcontext()
        if model_cfg is not None:
            with ctx:
                if req.generation_strategy == "section":
                    from app.generation.service import ContentGenerator
                    self._step(task_id, 5, "开始分段生成")
                    ContentGenerator(task_id, req.model_dump(), content_dir,
                                     self.task_manager).run()
                    spec = spec_from_paper_content(req.model_dump(), content_dir)
                else:  # single：一次生成（测试用）
                    self._step(task_id, 12, "正在一次生成全文...")
                    single = deepseek_service.generate_full_paper(req)
                    spec = pipeline_spec_from_content(req, single)
                self.task_manager.update(task_id, current_stage="completed",
                                         message="内容生成完成")
        else:
            self._step(task_id, 25, "生成内容 spec")
            spec = build_spec(req)

        # ===== 第二阶段：格式处理（markdown/json → 交付物）=====
        # 不再立即生成最终 DOCX：用户点击「导出论文」时按所选模板渲染（见 /api/export）。
        self._step(task_id, 75, "生成质量报告")
        quality_service.write_quality_report(task_dir, req)
        self._step(task_id, 80, "格式处理")
        formatter_service.format_paper(
            task_id, task_dir, req.model_dump(), spec, build_docx=False)
        self._step(task_id, 95, "格式化完成")

    # -- helpers --------------------------------------------------------------

    def _step(self, task_id: str, progress: int, label: str) -> None:
        self.task_manager.update(task_id, progress=progress)
        logger.info("Task %s [%d%%] %s", task_id, progress, label)

    def _load_request(self, task_id: str) -> GenerateRequest:
        path = self.settings.output_dir / task_id / "request.json"
        return GenerateRequest.model_validate_json(path.read_text(encoding="utf-8"))

    def _list_outputs(self, task_dir: Path) -> list[str]:
        files = []
        for p in sorted(task_dir.rglob("*")):
            if p.is_file() and p.name != "task.json":
                files.append(str(p.relative_to(task_dir)).replace("\\", "/"))
        return files

def pipeline_spec_from_content(req: GenerateRequest, content: dict) -> dict:
    """把 deepseek 生成结果（chapters/references）组装为 spec。"""
    meta = {
        "title": req.title,
        "abstract": content.get("abstract", ""),
        "keywords": content.get("keywords", []),
        "reference_style": req.reference_style,
        "citation_style": "numeric",
    }
    sections: list[dict] = []
    for ch in content.get("chapters", []):
        sections.append({"type": "h1", "text": ch["title"]})
        for b in ch.get("blocks", []):
            t = b.get("type")
            if t == "p":
                sections.append({"type": "p", "text": b.get("text", "")})
            elif t in ("h2", "h3"):
                sections.append({"type": t, "text": b.get("text", "")})
    references = content.get("references", [])
    sections.append({"type": "references", "items": references})
    return {"meta": meta, "sections": sections, "references": references}


def _count_docx(doc) -> int:
    import re
    cjk = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
    total = 0
    for p in doc.paragraphs:
        total += len(cjk.findall(p.text))
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                total += len(cjk.findall(cell.text))
    return total
