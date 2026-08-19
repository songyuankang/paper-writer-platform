from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from app.services import material_service


def _upload(filename: str = "notes.txt") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO("资料内容".encode("utf-8")))


@pytest.mark.parametrize("kind", ["开题报告", "仿写论文", "其他资料"])
def test_materials_are_saved_under_allowed_category_directories(tmp_path, kind):
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    result = material_service.save_and_extract([_upload()], [kind], task_dir)

    assert result[0]["kind"] == kind
    assert Path(result[0]["path"]) == Path("materials") / kind / "notes.txt"
    assert (task_dir / result[0]["path"]).is_file()


@pytest.mark.parametrize(
    "malicious_kind",
    ["../outside", "..\\outside", "nested/category", "/absolute/path", "  ../outside  "],
)
def test_path_like_material_kinds_fall_back_without_escaping_task_directory(
    tmp_path,
    malicious_kind,
):
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    result = material_service.save_and_extract(
        [_upload()], [malicious_kind], task_dir
    )

    stored = task_dir / result[0]["path"]
    assert result[0]["kind"] == material_service.DEFAULT_MATERIAL_KIND
    assert stored.is_file()
    assert stored.resolve().is_relative_to(task_dir.resolve())
    assert malicious_kind not in result[0]["path"]


def test_missing_or_unknown_kind_uses_existing_default_category(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    result = material_service.save_and_extract([_upload()], ["自定义分类"], task_dir)

    assert result[0]["kind"] == "其他资料"
    assert Path(result[0]["path"]) == Path("materials") / "其他资料" / "notes.txt"
