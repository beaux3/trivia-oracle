-- Local copy of qbreader tossups, filled by questions/local/sync.py.
-- Bonuses are not synced; the bot only plays tossups.

CREATE TABLE IF NOT EXISTS sets (
    name          TEXT PRIMARY KEY,   -- qbreader set name, e.g. "2023 ACF Winter"
    id            TEXT,               -- qbreader set _id
    year          INTEGER,
    standard      INTEGER,            -- 1 if qbreader marks the set as standard format
    packet_count  INTEGER NOT NULL,
    tossup_count  INTEGER NOT NULL,
    synced_at     TEXT NOT NULL       -- UTC ISO time; written only once every packet is stored
);

CREATE TABLE IF NOT EXISTS tossups (
    id                     TEXT PRIMARY KEY,   -- qbreader _id
    set_name               TEXT NOT NULL,
    packet_number          INTEGER NOT NULL,
    number                 INTEGER,            -- position within the packet
    category               TEXT,
    subcategory            TEXT,
    alternate_subcategory  TEXT,
    difficulty             INTEGER,            -- 0-10
    question_sanitized     TEXT NOT NULL,      -- question text, no HTML
    answer                 TEXT NOT NULL,      -- answerline with <b>/<u> tags, needed by the judge
    answer_sanitized       TEXT NOT NULL,      -- answerline, no HTML
    updated_at             TEXT                -- qbreader updatedAt
);

CREATE INDEX IF NOT EXISTS tossups_by_set ON tossups (set_name);
CREATE INDEX IF NOT EXISTS tossups_by_subcategory ON tossups (subcategory, difficulty);
