import json
import sqlite3
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.program import ROOT, ProgramStore, import_program

PREVIEW = "/api/trajectory/preview"
NEVEROV = "talk-150073"
BONAREVA = "talk-151071"


@pytest.fixture
def snapshot(tmp_path):
    target = tmp_path / "program.sqlite3"
    import_program(ROOT / "data/program.json", target)
    return target


@pytest.fixture
def client(snapshot):
    return TestClient(create_app(snapshot))


def action(entry_id, op="choose"):
    return {"op": op, "entry_id": entry_id}


def preview(client, program, topics=None, actions=()):
    response = client.post(PREVIEW, json={
        "revision": program["revision"], "topic_ids": topics or [], "actions": list(actions),
    })
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def items(result):
    return {item["entry_id"]: (item["state"], item["conflicts_with"]) for item in result["items"]}


def four_tables(db_path):
    with sqlite3.connect(db_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("entry", "room", "topic", "entry_topic")
        }


def test_ai_choice_reset_and_read_only(client, snapshot):
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/api/program")
    assert response.status_code == 200
    program = response.json()
    assert program["days"] == ["2026-11-20", "2026-11-21"]
    assert program["timezone"] == "Europe/Moscow"
    assert {room["id"] for room in program["rooms"]} == set("ABCD")
    assert len(program["topics"]) == 15
    assert Counter(entry["day"] for entry in program["entries"]) == {
        "2026-11-20": 45, "2026-11-21": 45,
    }
    entries = {entry["id"]: entry for entry in program["entries"]}
    assert list(entries) == sorted(entries, key=lambda key: (
        entries[key]["day"], entries[key]["starts_at"], entries[key]["room_id"] or "", key,
    ))
    before = four_tables(snapshot)
    blank = preview(client, program)
    assert blank["items"] == [] and blank["is_custom"] is False
    automatic = preview(client, program, ["ai"])
    assert automatic["is_custom"] is False
    assert items(automatic)[NEVEROV] == ("alternative", [BONAREVA])
    assert items(automatic)[BONAREVA] == ("alternative", [NEVEROV])

    chosen = preview(client, program, ["ai"], [action(BONAREVA)])
    assert chosen["is_custom"] is True
    assert NEVEROV not in items(chosen)
    assert items(chosen)[BONAREVA] == ("selected", [])
    day_one = {key for key, entry in entries.items() if entry["day"] == program["days"][0]}
    assert {key: value for key, value in items(chosen).items() if key in day_one} == {
        key: value for key, value in items(automatic).items() if key in day_one
    }
    assert preview(client, program, ["ai"], [action(BONAREVA), action(BONAREVA)]) == chosen
    assert preview(client, program, ["ai"]) == automatic
    assert four_tables(snapshot) == before
    assert client.get("/api/program").json()["revision"] == program["revision"]
    with ProgramStore(snapshot).engine.connect() as read_only:
        with pytest.raises(OperationalError, match="readonly"):
            read_only.exec_driver_sql("DELETE FROM entry_topic")


def test_blitz_boundaries_and_direct_conflicts(client):
    program = client.get("/api/program").json()
    first, second = "talk-151176", "talk-150470"
    baseline = items(preview(client, program, ["ai", "3433", "3430"]))
    assert second not in baseline[first][1]
    assert first not in baseline[second][1]
    assert {first, second} <= set(baseline[BONAREVA][1])
    selected = items(preview(client, program, actions=[action(first), action(second)]))
    assert selected == {first: ("selected", []), second: ("selected", [])}
    replaced = items(preview(client, program, actions=[action(first), action(second), action(BONAREVA)]))
    assert replaced == {BONAREVA: ("selected", [])}


def test_workshop_chain_keeps_gap_and_loses_dependent_parts(client, tmp_path):
    program = client.get("/api/program").json()
    first = "talk-150660"
    second = first + "-2"
    normal = items(preview(client, program, ["ai"]))
    assert first in normal and second not in normal
    # A synthetic talk fills the gap left between the official workshop's two slots.
    data = json.loads((ROOT / "data/program.json").read_text())
    template = next(entry for entry in data["entries"] if entry["id"] == first)
    data["entries"].append({
        **template, "id": "gap", "kind": "talk", "title": "Доклад в паузе",
        "starts_at": "12:20", "ends_at": "12:50", "room_id": "A",
    })
    source = tmp_path / "gap.json"
    target = tmp_path / "gap.sqlite3"
    source.write_text(json.dumps(data), encoding="utf-8")
    import_program(source, target)
    client = TestClient(create_app(target))
    program = client.get("/api/program").json()

    chosen = [action(second)]
    result = items(preview(client, program, ["ai"], chosen))
    assert {first, second, "gap"} <= set(result)
    assert all(result[key] == ("selected", []) for key in (first, second, "gap"))
    skip = action(second, "skip_continuation")
    skipped = preview(client, program, ["ai"], [*chosen, skip])
    assert first in items(skipped) and second not in items(skipped)
    assert preview(client, program, ["ai"], [*chosen, skip, skip]) == skipped
    replaced = items(preview(client, program, ["ai"], [*chosen, action("talk-151097")]))
    assert first not in replaced and second not in replaced and "gap" in replaced


def test_errors_are_atomic_and_stale_takes_precedence(client):
    program = client.get("/api/program").json()
    payload = {"revision": program["revision"], "topic_ids": [], "actions": []}
    cases = [
        (422, "invalid_request", {key: value for key, value in payload.items() if key != "revision"}),
        (422, "invalid_request", {**payload, "extra": True}),
        (422, "invalid_request", {**payload, "revision": 0}),
        (422, "invalid_request", {**payload, "topic_ids": ["ai", "ai"]}),
        (422, "invalid_request", {**payload, "actions": [action(BONAREVA, "drop")]}),
        (422, "invalid_request", {**payload, "actions": [dict(action(BONAREVA), extra=True)]}),
        (409, "stale_program", {**payload, "revision": "old", "topic_ids": ["gone"], "actions": [action("gone")]}),
        (422, "unknown_topic", {**payload, "topic_ids": ["gone"]}),
        (422, "unknown_entry", {**payload, "actions": [action(BONAREVA), action("gone")]}),
        (422, "not_selectable", {**payload, "actions": [action("event-20-0900-all")]}),
        (422, "not_continuation", {**payload, "actions": [action(BONAREVA, "skip_continuation")]}),
    ]
    for status, code, body in cases:
        response = client.post(PREVIEW, json=body)
        assert response.status_code == status, response.text
        assert set(response.json()) == {"code", "message"}
        assert response.json()["code"] == code and response.json()["message"]

    for data in (b"{", b"\xff"):
        malformed = client.post(PREVIEW, content=data, headers={"Content-Type": "application/json"})
        assert malformed.status_code == 422 and malformed.json()["code"] == "invalid_request"
    assert preview(client, program)["items"] == []


@pytest.mark.parametrize("corrupt", [False, True])
def test_unavailable_snapshot(tmp_path, corrupt):
    target = tmp_path / "missing.sqlite3"
    if corrupt:
        target.write_bytes(b"unusable")
    client = TestClient(create_app(target))
    for response in [
        client.get("/api/health"),
        client.get("/api/program"),
        client.post(PREVIEW, json={"revision": "old", "topic_ids": [], "actions": []}),
    ]:
        assert response.status_code == 503
        assert response.json()["code"] == "program_unavailable"


def test_invalid_import_preserves_previous_snapshot_and_revision(tmp_path, snapshot):
    store = ProgramStore(snapshot)
    before = snapshot.read_bytes()
    original = store.read()
    source = tmp_path / "source.json"
    payload = json.loads((ROOT / "data/program.json").read_text())
    continuation = next(entry for entry in payload["entries"] if entry["previous_part_id"])
    previous = continuation["previous_part_id"]
    continuation["previous_part_id"] = NEVEROV
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Неверная связь"):
        import_program(source, snapshot)
    assert snapshot.read_bytes() == before
    assert store.read().revision == original.revision

    continuation["previous_part_id"] = previous
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert import_program(source, snapshot).revision == original.revision
    next(entry for entry in payload["entries"] if entry["id"] == BONAREVA)["speakers"] += " (Сбер)"
    source.write_text(json.dumps(payload), encoding="utf-8")
    updated = import_program(source, snapshot)
    assert updated.revision != original.revision
    assert store.read() == updated
