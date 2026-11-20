CREATE TABLE room (
    id TEXT NOT NULL PRIMARY KEY CHECK (id IN ('A', 'B', 'C', 'D')),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);

CREATE TABLE topic (
    id TEXT NOT NULL PRIMARY KEY CHECK (length(id) > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE entry (
    id TEXT NOT NULL PRIMARY KEY CHECK (length(id) > 0),
    kind TEXT NOT NULL CHECK (kind IN (
        'talk', 'blitz', 'workshop', 'discussion', 'break', 'service', 'hackathon'
    )),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    speakers TEXT,
    day TEXT NOT NULL CHECK (day IN ('2026-11-20', '2026-11-21')),
    starts_at TEXT NOT NULL CHECK (
        starts_at GLOB '[0-2][0-9]:[0-5][0-9]' AND starts_at <= '23:59'
    ),
    ends_at TEXT NOT NULL CHECK (
        ends_at GLOB '[0-2][0-9]:[0-5][0-9]' AND ends_at <= '23:59'
    ),
    room_id TEXT REFERENCES room(id),
    previous_part_id TEXT UNIQUE REFERENCES entry(id),
    CHECK (starts_at < ends_at),
    CHECK (room_id IS NOT NULL OR kind IN ('break', 'service', 'hackathon')),
    CHECK (previous_part_id IS NULL OR (kind = 'workshop' AND previous_part_id <> id))
);

CREATE TABLE entry_topic (
    entry_id TEXT NOT NULL REFERENCES entry(id),
    topic_id TEXT NOT NULL REFERENCES topic(id),
    PRIMARY KEY (entry_id, topic_id)
);
