"""In-process task queue with disk-backed metadata.

Workers consume the queue and run paper generation. Status is persisted to
``outputs/{task_id}/task.json`` so it survives a service restart.
"""

import json
import logging
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import Settings
from app.models.task import TaskInfo, TaskStatus

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, settings: Settings, runner: Callable):
        self.settings = settings
        self.runner = runner
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._recover_unfinished()
        for i in range(self.settings.task_workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"paper-worker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)
        logger.info("TaskManager started with %d worker(s)", len(self._workers))

    def _recover_unfinished(self) -> None:
        """重启后把 outputs/ 里未完成的任务重新入队（防止 pending 任务丢失）。

        任务元数据持久化在 outputs/<task_id>/task.json：
        - queued/pending：从未开始执行，直接重新排队
        - running：上次进程被中断，重新执行（生成管线支持断点续传）
        已删除的任务其 outputs 目录一并被清除，不会被恢复。
        """
        output_dir = self.settings.output_dir
        if not output_dir.is_dir():
            return
        recovered = 0
        for task_dir in output_dir.iterdir():
            meta_path = task_dir / "task.json"
            if not meta_path.is_file():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                status = data.get("status")
                if status in ("queued", "pending", "running"):
                    task_id = data.get("task_id") or task_dir.name
                    self.submit(task_id)
                    recovered += 1
            except Exception:  # noqa: BLE001 - 跳过损坏的元数据
                continue
        if recovered:
            logger.info("TaskManager recovered %d unfinished task(s)", recovered)

    def _worker_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                self._tasks[task_id] = self._load_meta(task_id)
                self._tasks[task_id].status = TaskStatus.running
                self._tasks[task_id].updated_at = _now()
                self._save_meta(self._tasks[task_id])
                self.runner(task_id)
            except Exception as exc:  # noqa: BLE001 - worker must not die
                logger.exception("Task %s failed", task_id)
                self.update(task_id, status=TaskStatus.failed,
                            error=f"{type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()

    # -- task management ----------------------------------------------------

    def create(self, task_id: str) -> TaskInfo:
        info = TaskInfo(
            task_id=task_id,
            status=TaskStatus.queued,
            progress=0,
            created_at=_now(),
            updated_at=_now(),
        )
        with self._lock:
            self._tasks[task_id] = info
        self._save_meta(info)
        return info

    def submit(self, task_id: str) -> None:
        self._queue.put(task_id)

    def update(self, task_id: str, *, progress: int | None = None,
               status: TaskStatus | None = None,
               message: str | None = None,
               current_stage: str | None = None,
               current_chapter: str | None = None,
               chapter_count: int | None = None,
               error: str | None = None,
               files: list[str] | None = None) -> TaskInfo | None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                info = self._load_meta(task_id)
                if info is None:
                    return None
                self._tasks[task_id] = info
            if progress is not None:
                info.progress = max(0, min(100, progress))
            if status is not None:
                info.status = status
            if message is not None:
                info.message = message
            if current_stage is not None:
                info.current_stage = current_stage
            if current_chapter is not None:
                info.current_chapter = current_chapter
            if chapter_count is not None:
                info.chapter_count = chapter_count
            if error is not None:
                info.error = error
            if files is not None:
                info.files = files
            info.updated_at = _now()
        self._save_meta(info)
        return info

    def get(self, task_id: str) -> TaskInfo | None:
        with self._lock:
            info = self._tasks.get(task_id)
        if info is not None:
            return info
        return self._load_meta(task_id)

    # -- persistence ---------------------------------------------------------

    def _meta_path(self, task_id: str) -> Path:
        return self.settings.output_dir / task_id / "task.json"

    def _save_meta(self, info: TaskInfo) -> None:
        try:
            path = self._meta_path(info.task_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(info.model_dump_json(indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to persist metadata for %s", info.task_id)

    def _load_meta(self, task_id: str) -> TaskInfo | None:
        path = self._meta_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskInfo.model_validate(data)
        except Exception:  # noqa: BLE001
            logger.warning("Corrupt metadata for %s", task_id)
            return None


def _now() -> datetime:
    return datetime.now(timezone.utc)
