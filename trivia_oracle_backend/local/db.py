"""SQLite access for the local question database (schema in schema.sql)."""
import os
import sqlite3
from datetime import datetime, timezone

_SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

_TOSSUP_COLUMNS = (
    "id", "set_name", "packet_number", "number", "category", "subcategory",
    "alternate_subcategory", "difficulty", "question_sanitized", "answer",
    "answer_sanitized", "updated_at",
)


def connect(path: str) -> sqlite3.Connection:
    """Open the database for writing, creating the file and tables if needed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    with open(_SCHEMA_FILE) as f:
        conn.executescript(f.read())
    return conn


def connect_readonly(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No question database at {path}. "
            "Run `python -m trivia_oracle_backend.local.sync` to create it."
        )
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


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


def replace_set(conn: sqlite3.Connection, set_name: str, packet_count: int, tossups: list) -> int:
    """
    Store one whole set in a single transaction, replacing any earlier copy.

    The sets row is written last, so a set is only ever marked synced with all
    its tossups present. Returns the number of tossups stored.
    """
    rows = [tossup_row(t) for t in tossups]
    set_info = tossups[0].get("set", {}) if tossups else {}
    placeholders = ", ".join("?" for _ in _TOSSUP_COLUMNS)
    with conn:
        conn.execute("DELETE FROM tossups WHERE set_name = ?", (set_name,))
        conn.executemany(
            f"INSERT OR REPLACE INTO tossups ({', '.join(_TOSSUP_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO sets (name, id, year, standard, packet_count, tossup_count, synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                set_name,
                set_info.get("_id"),
                set_info.get("year"),
                None if set_info.get("standard") is None else int(set_info["standard"]),
                packet_count,
                len(rows),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
    return len(rows)
