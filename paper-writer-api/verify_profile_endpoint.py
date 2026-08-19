from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

project = Path(r"D:\paper-writer-platform-main\paper-writer-platform-main\paper-writer-api")
fixture = project / "_profile_endpoint_fixture.csv"
fixture.write_text("year,investment,agility\n2021,41,56\n2022,53,61\n", encoding="utf-8")
try:
    boundary = uuid.uuid4().hex
    content = fixture.read_bytes()
    chunks = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{fixture.name}"\r\n'.encode(),
        b"Content-Type: text/csv\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = Request(
        "http://127.0.0.1:8000/api/chart-data/profile",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["row_count"] == 2, payload
    assert [column["name"] for column in payload["columns"]] == ["year", "investment", "agility"], payload
    print(json.dumps(payload, ensure_ascii=False))
finally:
    fixture.unlink(missing_ok=True)
