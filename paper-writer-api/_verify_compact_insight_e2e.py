import json
from urllib.request import Request, urlopen

TASK_ID = "3ee5f16549fc4b8d91ebd8a921ac8eb1"
BLOCK_ID = "insight_d0bbd2613d9d"
request = Request(
    f"http://127.0.0.1:8000/api/draft/{TASK_ID}/insight/{BLOCK_ID}/regenerate",
    data=json.dumps({"scope": "full_paper", "intent": "auto"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=45) as response:
    assert response.status == 200
    block = json.loads(response.read().decode("utf-8"))

assert block["id"] == BLOCK_ID
assert block["kind"] == "comparison_table", block["kind"]
assert block["source_status"] == "text_synthesis", block["source_status"]
table = block["table"]
assert table["style"] == "three_line"
assert len(table["headers"]) == 3
assert 1 <= len(table["rows"]) <= 3, len(table["rows"])
assert all(len(row) == 3 for row in table["rows"])
assert all(row[1].strip() and row[2].strip() for row in table["rows"]), table["rows"]
assert all(len(row[2]) <= 56 for row in table["rows"]), table["rows"])
assert "紧凑" in block["caption"], block["caption"]
assert len(block["evidence"]) >= 1
assert "chart" not in block
print("COMPACT_INSIGHT_E2E_OK")
print("BLOCK_ID=" + block["id"])
print("ROWS=" + str(len(table["rows"])))
print("CAPTION=" + block["caption"])
print("ROW_LENGTHS=" + ",".join(str(len(row[2])) for row in table["rows"]))
