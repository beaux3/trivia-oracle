-- Local copy of qbreader tossups, filled by local/sync.py, plus hand-written
-- questions (custom/add.py; is_custom = 1). The same schema is used for both.
-- Bonuses are not synced; the bot only plays tossups.
-- Columns marked (added later) are added to older database files by db.connect().

CREATE TABLE IF NOT EXISTS sets (
    name          TEXT PRIMARY KEY,   -- qbreader set name, e.g. "2023 ACF Winter"
    id            TEXT,               -- qbreader set _id
    year          INTEGER,
    standard      INTEGER,            -- 1 if qbreader marks the set as standard format
    packet_count  INTEGER NOT NULL,
    tossup_count  INTEGER NOT NULL,
    synced_at     TEXT NOT NULL,      -- UTC ISO time; written only once every packet is stored
    is_custom     INTEGER NOT NULL DEFAULT 0  -- (added later) 1 for a set of hand-written questions
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
    updated_at             TEXT,               -- qbreader updatedAt
    good_votes             INTEGER NOT NULL DEFAULT 0,  -- (added later) player feedback; a score is derived from these
    bad_votes              INTEGER NOT NULL DEFAULT 0,  -- (added later)
    is_custom              INTEGER NOT NULL DEFAULT 0   -- (added later) 1 for a hand-written question, 0 for qbreader's
);

CREATE INDEX IF NOT EXISTS tossups_by_set ON tossups (set_name);
CREATE INDEX IF NOT EXISTS tossups_by_subcategory ON tossups (subcategory, difficulty);
