import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.models import DAYS, SELECTABLE, TIMEZONE, Entry, Program, ProgramContent

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/program.sqlite3"
ROOMS = set("ABCD")


class SnapshotUnavailable(Exception):
    pass


def _read_program(connection: Connection) -> Program:
    if (
        connection.exec_driver_sql("PRAGMA quick_check").scalars().all() != ["ok"]
        or connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None
    ):
        raise ValueError("Нарушена целостность SQLite")

    def rows(query: str) -> list[dict]:
        return [dict(row) for row in connection.execute(text(query)).mappings()]

    links = defaultdict(list)
    for row in rows("SELECT entry_id, topic_id FROM entry_topic ORDER BY entry_id, topic_id"):
        links[row["entry_id"]].append(row["topic_id"])

    content = ProgramContent(
        timezone=TIMEZONE,
        days=list(DAYS),
        rooms=rows("SELECT id, name FROM room ORDER BY id"),
        topics=rows("SELECT id, name FROM topic ORDER BY id"),
        entries=[
            {**row, "topic_ids": links[row["id"]]}
            for row in rows("""
                SELECT id, kind, title, speakers, day, starts_at, ends_at, room_id, previous_part_id
                FROM entry ORDER BY day, starts_at, room_id, id
            """)
        ],
    )
    _validate_program(content)
    payload = content.model_dump()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Program(**payload, revision=hashlib.sha256(encoded.encode()).hexdigest())


def _validate_program(program: ProgramContent) -> None:
    entries = {entry.id: entry for entry in program.entries}
    topics = {topic.id for topic in program.topics}
    if (
        {room.id for room in program.rooms} != ROOMS
        or {entry.room_id for entry in program.entries if entry.kind in SELECTABLE} != ROOMS
        or {entry.day for entry in program.entries} != set(DAYS)
        or not topics
    ):
        raise ValueError("Снимок должен содержать оба дня, четыре зала и темы")

    used_predecessors = set()
    for entry in program.entries:
        if (
            entry.starts_at >= entry.ends_at
            or (entry.kind in SELECTABLE and entry.room_id not in ROOMS)
            or len(entry.topic_ids) != len(set(entry.topic_ids))
            or not topics.issuperset(entry.topic_ids)
        ):
            raise ValueError(f"Неверная карточка {entry.id}")

        if entry.previous_part_id is not None:
            previous = entries.get(entry.previous_part_id)
            if (
                previous is None
                or entry.kind != "workshop"
                or previous.kind != "workshop"
                or previous.day != entry.day
                or previous.room_id != entry.room_id
                or previous.title != entry.title
                or previous.ends_at > entry.starts_at
                or previous.id in used_predecessors
            ):
                raise ValueError(f"Неверная связь частей мастер-класса {entry.id}")
            used_predecessors.add(previous.id)


class ProgramStore:
    def __init__(self, path: Path):
        uri = path.resolve().as_uri() + "?mode=ro"

        def connect():
            return sqlite3.connect(uri, uri=True)

        # Each request opens the current file after a publisher's atomic replacement.
        self.engine = create_engine("sqlite://", creator=connect, poolclass=NullPool)

    def read(self) -> Program:
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
                return _read_program(connection)
        except (SQLAlchemyError, ValueError) as error:
            raise SnapshotUnavailable from error


def import_program(source: Path, target: Path) -> Program:
    payload = json.loads(source.read_text(encoding="utf-8"))
    rooms = payload["rooms"]
    topics = payload["topics"]
    entries = [Entry.model_validate(row) for row in payload["entries"]]
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / "data/schema.sql").read_text(encoding="utf-8")
    # Build on the same filesystem so existing readers and interrupted imports are safe.
    with tempfile.TemporaryDirectory(prefix=".program-", dir=target.parent) as staging:
        temporary = Path(staging) / target.name
        engine = create_engine(f"sqlite:///{temporary}", poolclass=NullPool)
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            for statement in schema.split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            connection.execute(text("INSERT INTO room VALUES (:id, :name)"), rooms)
            connection.execute(text("INSERT INTO topic VALUES (:id, :name)"), topics)
            connection.execute(
                text("""
                    INSERT INTO entry VALUES
                    (:id, :kind, :title, :speakers, :day, :starts_at, :ends_at, :room_id, :previous_part_id)
                """),
                [entry.model_dump(exclude={"topic_ids"}) for entry in entries],
            )
            links = [
                {"entry": entry.id, "topic": topic}
                for entry in entries for topic in entry.topic_ids
            ]
            if links:
                connection.execute(text("INSERT INTO entry_topic VALUES (:entry, :topic)"), links)
            program = _read_program(connection)
        with temporary.open("rb") as snapshot:
            os.fsync(snapshot.fileno())
        os.replace(temporary, target)
    return program


def main() -> None:
    parser = argparse.ArgumentParser(description="Собрать проверенный снимок программы")
    parser.add_argument("--source", type=Path, default=ROOT / "data/program.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_DB)
    options = parser.parse_args()
    program = import_program(options.source, options.output)
    print(f"{len(program.entries)} карточек · {program.revision}")


if __name__ == "__main__":
    main()
