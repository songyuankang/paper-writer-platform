"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.generate import router
from app.api.history import router as history_router
from app.api.revise import router as revise_router
from app.api.models import router as models_router
from app.api.format_task import router as format_router
from app.api.polish import router as polish_router
from app.api.draft import router as draft_router
from app.api.templates import router as templates_router
from app.config import settings
from app.db import init_db
from app.formatter import template_manager
from app.services.paper_service import PaperService
from app.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_dir / "app.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    console = logging.StreamHandler()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=[file_handler, console],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    setup_logging()
    init_db()
    template_manager.ensure_default_template()
    task_manager = TaskManager(settings, runner=None)
    paper_service = PaperService(settings, task_manager)
    task_manager.runner = paper_service.run_task
    task_manager.start()
    app.state.task_manager = task_manager
    app.state.paper_service = paper_service
    logger.info("paper-writer-api started (engine dir: %s)",
                settings.paper_writer_scripts_dir)
    yield


app = FastAPI(
    title=settings.app_name,
    description="paper-writer Skill 的 API 接口层：提交论文生成任务、查询进度、下载结果。",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(history_router)
app.include_router(revise_router)
app.include_router(models_router)
app.include_router(format_router)
app.include_router(polish_router)
app.include_router(draft_router)
app.include_router(templates_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                reload=False)
