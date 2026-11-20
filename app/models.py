from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DAYS = ("2026-11-20", "2026-11-21")
TIMEZONE = "Europe/Moscow"
SELECTABLE = frozenset({"talk", "blitz", "discussion", "workshop"})

Id = Annotated[str, Field(min_length=1)]
Ids = Annotated[list[Id], Field(json_schema_extra={"uniqueItems": True})]
Clock = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Day = Literal["2026-11-20", "2026-11-21"]
Kind = Literal["talk", "blitz", "workshop", "discussion", "break", "service", "hackathon"]
State = Literal["selected", "alternative"]
InvalidCode = Literal["invalid_request", "unknown_topic", "unknown_entry", "not_selectable", "not_continuation"]
ErrorCode = InvalidCode | Literal["stale_program", "program_unavailable"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Health(StrictModel):
    status: Literal["ok"]


class NamedItem(StrictModel):
    id: Id
    name: Annotated[str, Field(min_length=1)]


class Entry(StrictModel):
    id: Id
    kind: Kind
    title: Annotated[str, Field(min_length=1)]
    speakers: str | None
    day: Day
    starts_at: Clock
    ends_at: Clock
    room_id: str | None
    topic_ids: Ids
    previous_part_id: str | None


class ProgramContent(StrictModel):
    timezone: Literal["Europe/Moscow"]
    days: Annotated[list[Day], Field(json_schema_extra={"const": list(DAYS)})]
    rooms: list[NamedItem]
    topics: list[NamedItem]
    entries: list[Entry]


class Program(ProgramContent):
    revision: Id


class Action(StrictModel):
    op: Literal["choose", "skip_continuation"]
    entry_id: Id


class PreviewRequest(StrictModel):
    revision: Id
    topic_ids: Ids
    actions: list[Action]

    @field_validator("topic_ids")
    @classmethod
    def unique_topics(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Повтор темы")
        return value


class PreviewItem(StrictModel):
    entry_id: Id
    state: State
    conflicts_with: Ids


class Preview(StrictModel):
    revision: Id
    items: list[PreviewItem]
    is_custom: bool


class Error(StrictModel):
    code: ErrorCode
    message: Annotated[str, Field(min_length=1)]


class InvalidRequestError(Error):
    code: InvalidCode


class StaleProgramError(Error):
    code: Literal["stale_program"]


class ProgramUnavailableError(Error):
    code: Literal["program_unavailable"]
