import shutil

from app.config import settings
from app.services.task_manager import TaskManager


def test_remove_drops_deleted_task_from_memory_and_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    manager = TaskManager(settings, lambda _task_id: None)
    task_id = "deleted-task"

    manager.create(task_id)
    assert manager.get(task_id) is not None

    # 模拟 history_service.delete_record 删除 outputs/<task_id>。
    shutil.rmtree(tmp_path / task_id)
    manager.remove(task_id)

    assert manager.get(task_id) is None
