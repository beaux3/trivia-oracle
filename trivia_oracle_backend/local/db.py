"""SQLite access for the local question database (schema in schema.sql)."""
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

_SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

_TOSSUP_COLUMNS = (
    "id", "set_name", "packet_number", "number", "category", "subcategory",
    "alternate_subcategory", "difficulty", "question_sanitized", "answer",
    "answer_sanitized", "updated_at",
)

# Columns that older database files lack; connect() adds them (schema.sql has them for new files).
_ADDED_COLUMNS = {
    "sets": {"is_custom": "INTEGER NOT NULL DEFAULT 0"},
    "tossups": {
        "good_votes": "INTEGER NOT NULL DEFAULT 0",
        "bad_votes": "INTEGER NOT NULL DEFAULT 0",
        "is_custom": "INTEGER NOT NULL DEFAULT 0",
    },
}


def connect(path: str) -> sqlite3.Connection:
    """Open the database for writing, creating the file and tables if needed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    with open(_SCHEMA_FILE) as f:
        conn.executescript(f.read())
    with conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return conn


def connect_readonly(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No question database at {path}. "
            "Run `python -m trivia_oracle_backend.local.sync` to create it."
        )
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


RATINGS = ("good", "bad")


def record_vote(path: str, tossup_id: str, rating: str, previous: Optional[str] = None) -> tuple:
    """
    Add one player's vote to a custom question's good_votes / bad_votes; returns the new (good, bad).

    `previous` is the vote that player gave the same question before, if any: it is withdrawn, so
    changing a vote moves it instead of adding a second one. Only custom questions can be rated
    (LookupError otherwise, and when the id is unknown). The file is never created: a missing one
    is a FileNotFoundError.
    """
    if rating not in RATINGS or (previous is not None and previous not in RATINGS):
        raise ValueError(f"rating and previous must be one of {', '.join(RATINGS)}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No question database at {path}.")
    conn = sqlite3.connect(path, timeout=10)
    try:
        with conn:  # one transaction: the update and the read-back see the same counts
            changes = [f"{rating}_votes = {rating}_votes + 1"]
            if previous and previous != rating:
                changes.append(f"{previous}_votes = MAX({previous}_votes - 1, 0)")
            updated = conn.execute(
                f"UPDATE tossups SET {', '.join(changes)} WHERE id = ? AND is_custom = 1", (tossup_id,)
            ).rowcount
            if not updated:
                raise LookupError(f"No custom question with id {tossup_id!r}.")
            return conn.execute(
                "SELECT good_votes, bad_votes FROM tossups WHERE id = ?", (tossup_id,)
            ).fetchone()
    finally:
        conn.close()


def synced_set_names(conn: sqlite3.Connection) -> set:
    return {name for (name,) in conn.execute("SELECT name FROM sets")}


def tossup_row(tossup: dict) -> tuple:
    """Map a qbreader tossup JSON object to a tossups row."""
    return (
        tossup["_id"],
        tossup["set"]["name"],
        tossup["packet"]["number"],
        tossup.get("number"),
        tossup.get("category"),
        tossup.get("subcategory"),
        tossup.get("alternate_subcategory"),
        tossup.get("difficulty"),
        tossup["question_sanitized"],
        tossup["answer"],
        tossup["answer_sanitized"],
        tossup.get("updatedAt"),
    )


def replace_set(conn: sqlite3.Connection, set_name: str, packet_count: int, tossups: list,
                custom: bool = False) -> int:
    """
    Store one whole set in a single transaction, replacing any earlier copy.

    The sets row is written last, so a set is only ever marked synced with all
    its tossups present. Votes of questions that are still in the set are kept.
    `custom` marks the set and its tossups as hand-written. Returns the number
    of tossups stored.
    """
    rows = [tossup_row(t) + (int(custom),) for t in tossups]
    set_info = tossups[0].get("set", {}) if tossups else {}
    columns = _TOSSUP_COLUMNS + ("is_custom",)
    placeholders = ", ".join("?" for _ in columns)
    with conn:
        votes = conn.execute(
            "SELECT good_votes, bad_votes, id FROM tossups WHERE set_name = ?", (set_name,)
        ).fetchall()
        conn.execute("DELETE FROM tossups WHERE set_name = ?", (set_name,))
        conn.executemany(
            f"INSERT OR REPLACE INTO tossups ({', '.join(columns)}) VALUES ({placeholders})",
            rows,
        )
        conn.executemany("UPDATE tossups SET good_votes = ?, bad_votes = ? WHERE id = ?", votes)
        conn.execute(
            "INSERT OR REPLACE INTO sets (name, id, year, standard, packet_count, tossup_count, synced_at, is_custom)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                set_name,
                set_info.get("_id"),
                set_info.get("year"),
                None if set_info.get("standard") is None else int(set_info["standard"]),
                packet_count,
                len(rows),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                int(custom),
            ),
        )
    return len(rows)
