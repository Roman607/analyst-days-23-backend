"""Run on the public address after Compose has restarted the services."""
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip("/")


def fetch(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    try:
        response = urlopen(Request(base + path, data=data, headers=headers), timeout=20)
    except HTTPError as error:
        response = error
    with response:
        body = response.read()
        if response.headers.get_content_type() == "application/json":
            body = json.loads(body)
        return response.status, response.headers, body


status, _, landing = fetch("/")
assert status == 200 and "Выбрать траекторию" in landing.decode()
assert fetch("/api/health")[::2] == (200, {"status": "ok"})
status, _, program = fetch("/api/program")
assert status == 200 and program["days"] == ["2026-11-20", "2026-11-21"]
assert {entry["day"] for entry in program["entries"]} == set(program["days"])
status, _, docs = fetch("/api/docs")
assert status == 200 and b"Swagger UI" in docs and b"/api/openapi.json" in docs
status, _, schema = fetch("/api/openapi.json")
assert status == 200 and set(schema["paths"]) == {
    "/api/health", "/api/program", "/api/trajectory/preview",
}
ai = next(topic["id"] for topic in program["topics"] if topic["name"] == "ИИ")
example = {
    entry["id"] for entry in program["entries"]
    if entry["day"] == "2026-11-21" and entry["starts_at"] == "16:30"
    and entry["room_id"] in ("A", "B")
}
assert len(example) == 2
status, headers, result = fetch("/api/trajectory/preview", {
    "revision": program["revision"], "topic_ids": [ai], "actions": [],
})
assert status == 200 and headers["Cache-Control"] == "no-store"
alternatives = {item["entry_id"]: item for item in result["items"] if item["entry_id"] in example}
assert alternatives.keys() == example
for key, item in alternatives.items():
    assert item["state"] == "alternative" and example - {key} <= set(item["conflicts_with"])
status, _, failure = fetch("/api/trajectory/preview", {"topic_ids": [ai], "actions": []})
assert status == 422 and failure["code"] == "invalid_request"
print(f"HTTPS: лендинг, health, {len(program['entries'])} карточек, Swagger и варианты ИИ прошли проверку")
