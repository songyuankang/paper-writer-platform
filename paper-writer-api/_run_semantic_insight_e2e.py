import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

TASK_ID = "3ee5f16549fc4b8d91ebd8a921ac8eb1"
SECTION_ID = "1-2-1"
root = Path.cwd()
draft_path = root / "outputs" / TASK_ID / "draft.json"
backup_path = draft_path.with_name("draft.before_semantic_e2e_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
shutil.copy2(draft_path, backup_path)

body = json.dumps({
    "scope": "full_paper",
    "intent": "auto",
    "placement": "section_end",
}).encode("utf-8")
request = Request(
    f"http://127.0.0.1:8000/api/draft/{TASK_ID}/section/{SECTION_ID}/insight",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=45) as response:
    assert response.status == 200, response.status
    block = json.loads(response.read().decode("utf-8"))

assert block["type"] == "insight"
assert block["kind"] == "comparison_table", block["kind"]
assert block["source_status"] == "text_synthesis", block["source_status"]
assert "chart" not in block, "text-only evidence must not become a chart"
assert block["table"]["style"] == "three_line"
assert len(block["table"]["headers"]) >= 2
assert len(block["table"]["rows"]) >= 1
assert len(block["evidence"]) >= 1
assert all("illustrative" not in str(value).lower() for value in block.values())
print("SEMANTIC_E2E_OK")
print("BLOCK_ID=" + block["id"])
print("KIND=" + block["kind"])
print("EVIDENCE_COUNT=" + str(len(block["evidence"])))
print("BACKUP=" + str(backup_path))
