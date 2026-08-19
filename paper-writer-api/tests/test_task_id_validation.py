import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import draft as draft_api
from app.api import generate as generate_api
from app.models.task import TaskStatus


VALID_TASK_ID = "a" * 32


def test_task_id_validator_accepts_generated_uuid_hex_format():
    assert generate_api._validate_task_id(VALID_TASK_ID) == VALID_TASK_ID


@pytest.mark.parametrize(
    "task_id",
    [
        "",
        "../outside",
        "..\\outside",
        "a" * 31,
        "a" * 33,
        "g" * 32,
        f"{VALID_TASK_ID}/child",
    ],
)
def test_generate_api_rejects_malformed_or_path_like_task_ids(task_id):
    with pytest.raises(HTTPException) as exc_info:
        generate_api._task_dir(task_id)
    assert exc_info.value.status_code == 400


def test_status_and_sse_reject_invalid_task_ids_before_accessing_state():
    request = SimpleNamespace()
    with pytest.raises(HTTPException) as status_exc:
        asyncio.run(generate_api.status("../outside", request))
    assert status_exc.value.status_code == 400

    with pytest.raises(HTTPException) as stream_exc:
        asyncio.run(generate_api.stream_status("../outside", request))
    assert stream_exc.value.status_code == 400


def test_draft_service_rejects_invalid_task_id_before_building_path():
    with pytest.raises(HTTPException) as exc_info:
        draft_api._service("../outside", SimpleNamespace())
    assert exc_info.value.status_code == 400


def test_download_rejects_sibling_directory_prefix_bypass(tmp_path, monkeypatch):
    output_dir = tmp_path / "outputs"
    task_dir = output_dir / VALID_TASK_ID
    sibling_dir = output_dir / f"{VALID_TASK_ID}_sibling"
    task_dir.mkdir(parents=True)
    sibling_dir.mkdir()
    (sibling_dir / "outside.txt").write_text("outside", encoding="utf-8")
    monkeypatch.setattr(generate_api.settings, "output_dir", output_dir)

    manager = SimpleNamespace(
        get=lambda _task_id: SimpleNamespace(
            status=TaskStatus.completed,
            created_at=datetime.now(timezone.utc),
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(task_manager=manager))
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            generate_api.download(
                VALID_TASK_ID,
                request,
                file=f"../{VALID_TASK_ID}_sibling/outside.txt",
            )
        )
    assert exc_info.value.status_code == 400
