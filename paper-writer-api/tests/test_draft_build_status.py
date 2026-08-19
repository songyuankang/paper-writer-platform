import json
from types import SimpleNamespace

from app.models.task import TaskStatus
from app.services import history_service
from app.services.paper_service import PaperService
from app.services.task_manager import TaskManager


TASK_ID = "11111111-1111-4111-8111-111111111111"


class _RecordingTaskManager:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, task_id: str, **kwargs):
        self.updates.append({"task_id": task_id, **kwargs})


class _SuccessfulDraftService:
    def __init__(self, task_id, task_dir, task_manager) -> None:
        self.task_dir = task_dir

    def build(self, request, *, model_id, require_confirmation) -> None:
        assert request["draft_mode"] is True
        assert require_confirmation is True
        self.task_dir.mkdir(parents=True, exist_ok=True)
        (self.task_dir / "draft.json").write_text('{"sections": []}', encoding="utf-8")


class _FailingDraftService:
    def __init__(self, task_id, task_dir, task_manager) -> None:
        pass

    def build(self, request, *, model_id, require_confirmation) -> None:
        raise RuntimeError("草稿构建异常")


def _prepare_draft_task(tmp_path):
    task_dir = tmp_path / TASK_ID
    task_dir.mkdir()
    (task_dir / "request.json").write_text(
        json.dumps(
            {
                "title": "草稿状态测试",
                "major": "计算机科学",
                "word_count": 3000,
                "draft_mode": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(output_dir=tmp_path, upload_dir=tmp_path), task_dir


def test_draft_build_success_marks_task_and_history_completed(tmp_path, monkeypatch) -> None:
    settings, task_dir = _prepare_draft_task(tmp_path)
    task_manager = _RecordingTaskManager()
    history_updates: list[tuple[str, dict]] = []
    history_progress: list[tuple[str, dict]] = []

    monkeypatch.setattr("app.draft.service.DraftService", _SuccessfulDraftService)
    monkeypatch.setattr(
        history_service,
        "update_record",
        lambda task_id, **kwargs: history_updates.append((task_id, kwargs)),
    )
    monkeypatch.setattr(
        history_service,
        "update_record_progress",
        lambda task_id, **kwargs: history_progress.append((task_id, kwargs)),
    )

    PaperService(settings, task_manager).run_task(TASK_ID)

    completed = next(update for update in task_manager.updates if update.get("status") == TaskStatus.completed)
    assert completed["task_id"] == TASK_ID
    assert completed["progress"] == 100
    assert completed["message"] == "大纲草稿已生成，请确认大纲后进入正文编辑器"
    assert "draft.json" in completed["files"]
    assert (task_dir / "draft.json").is_file()
    assert (TASK_ID, {"status": "completed", "error": None, "completed": True}) in history_updates
    assert (TASK_ID, {"current_stage": "completed", "progress": 100}) in history_progress


def test_draft_build_failure_marks_task_failed(tmp_path, monkeypatch) -> None:
    settings, _ = _prepare_draft_task(tmp_path)
    task_manager = _RecordingTaskManager()
    history_updates: list[tuple[str, dict]] = []

    monkeypatch.setattr("app.draft.service.DraftService", _FailingDraftService)
    monkeypatch.setattr(
        history_service,
        "update_record",
        lambda task_id, **kwargs: history_updates.append((task_id, kwargs)),
    )

    PaperService(settings, task_manager).run_task(TASK_ID)

    failed = next(update for update in task_manager.updates if update.get("status") == TaskStatus.failed)
    assert failed["task_id"] == TASK_ID
    assert failed["error"] == "RuntimeError: 草稿构建异常"
    assert (TASK_ID, {"status": "failed", "error": "RuntimeError: 草稿构建异常"}) in history_updates


def test_completed_draft_task_is_not_requeued_on_recovery(tmp_path, monkeypatch) -> None:
    settings = SimpleNamespace(output_dir=tmp_path, task_workers=0)
    original_manager = TaskManager(settings, lambda task_id: None)
    original_manager.create(TASK_ID)
    original_manager.update(TASK_ID, progress=100, status=TaskStatus.completed)
    task_dir = tmp_path / TASK_ID
    (task_dir / "draft.json").write_text('{"sections": []}', encoding="utf-8")

    restarted_manager = TaskManager(settings, lambda task_id: None)
    recovered: list[str] = []
    monkeypatch.setattr(restarted_manager, "submit", recovered.append)

    restarted_manager._recover_unfinished()

    assert recovered == []
