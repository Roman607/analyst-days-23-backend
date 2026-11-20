from app.models import SELECTABLE, Entry, ErrorCode, Preview, PreviewItem, PreviewRequest, Program

ERRORS = {
    "invalid_request": (422, "Проверьте поля и формат запроса."),
    "unknown_topic": (422, "Тема отсутствует в текущей программе."),
    "unknown_entry": (422, "Карточка отсутствует в текущей программе."),
    "not_selectable": (422, "Это событие не участвует в подборе."),
    "not_continuation": (422, "Пропустить можно только продолжение мастер-класса."),
    "stale_program": (409, "Программа обновилась. Загрузите её заново."),
    "program_unavailable": (503, "Программа временно недоступна."),
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code


def overlaps(left: Entry, right: Entry) -> bool:
    return (
        left.day == right.day
        and left.starts_at < right.ends_at
        and right.starts_at < left.ends_at
    )


def preview(program: Program, request: PreviewRequest) -> Preview:
    if request.revision != program.revision:
        raise ApiError("stale_program")
    topics = set(request.topic_ids)
    if not topics.issubset(topic.id for topic in program.topics):
        raise ApiError("unknown_topic")
    by_id = {entry.id: entry for entry in program.entries}
    successors = {
        entry.previous_part_id: entry.id
        for entry in program.entries
        if entry.previous_part_id is not None
    }
    baseline = {
        entry.id for entry in program.entries
        if entry.kind in SELECTABLE
        and entry.previous_part_id is None
        and topics.intersection(entry.topic_ids)
    }
    included = baseline.copy()

    def remove_chain(entry_id: str) -> None:
        included.discard(entry_id)
        while entry_id in successors:
            entry_id = successors[entry_id]
            included.discard(entry_id)

    for action in request.actions:
        entry = by_id.get(action.entry_id)
        if entry is None:
            raise ApiError("unknown_entry")
        if entry.kind not in SELECTABLE:
            raise ApiError("not_selectable")
        if action.op == "skip_continuation":
            if entry.previous_part_id is None:
                raise ApiError("not_continuation")
            remove_chain(entry.id)
            continue

        chain = [entry]
        while chain[-1].previous_part_id is not None:
            chain.append(by_id[chain[-1].previous_part_id])
        for part in reversed(chain):
            for other_id in included.copy():
                if other_id != part.id and overlaps(part, by_id[other_id]):
                    remove_chain(other_id)
            included.add(part.id)

    visible = [entry for entry in program.entries if entry.id in included]
    items = []
    for entry in visible:
        conflicts = [other.id for other in visible if other.id != entry.id and overlaps(entry, other)]
        items.append(PreviewItem(
            entry_id=entry.id,
            state="alternative" if conflicts else "selected",
            conflicts_with=conflicts,
        ))
    # Statuses and conflicts are determined by the membership of the visible set.
    return Preview(revision=program.revision, items=items, is_custom=included != baseline)
