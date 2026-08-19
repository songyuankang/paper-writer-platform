from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_API = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
TASK_ID = "de59766e89a6449cacca3fbea9a84dd2"
TASK_DIR = PROJECT_API / "outputs" / TASK_ID
sys.path.insert(0, str(PROJECT_API))

from app.draft.service import DraftService


def main() -> None:
    old_docx = TASK_DIR / "论文.docx"
    backup = TASK_DIR / "论文.导出前未含图表.bak.docx"
    if old_docx.exists() and not backup.exists():
        shutil.copy2(old_docx, backup)

    service = DraftService(TASK_ID, TASK_DIR)
    files = service.export()
    if not old_docx.exists():
        raise RuntimeError(f"重新导出后未找到 Word 文件：{files}")

    with zipfile.ZipFile(old_docx) as archive:
        embedded = [name for name in archive.namelist() if name.startswith("word/media/")]
    if len(embedded) < 3:
        raise RuntimeError(f"重新导出的 Word 未嵌入预期 3 张图表：{embedded}")

    print(f"DOCX={old_docx}")
    print(f"BACKUP={backup if backup.exists() else 'none'}")
    print(f"FILES={len(files)}")
    print(f"EMBEDDED_MEDIA={len(embedded)}")


if __name__ == "__main__":
    main()
