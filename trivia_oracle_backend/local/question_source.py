"""QuestionSource that draws tossups from the local SQLite database."""
import random
from dataclasses import dataclass
from typing import Optional

from ..base import QuestionFilters
from .db import connect_readonly, record_play, record_vote

# Parent (category, subcategory) of each alternate subcategory. The qbreader
# client adds these to a /random-tossup request whenever an alternate
# subcategory is selected (trivia_oracle_backend/vendor/qbreader/_api_utils.py: category_correspondence),
# so the local query adds them too.
ALT_SUBCATEGORY_PARENTS = {
    **dict.fromkeys(
        ["Astronomy", "Computer Science", "Math", "Earth Science", "Engineering", "Misc Science"],
        (None, "Other Science"),
    ),
    **dict.fromkeys(
        ["Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts"],
        (None, "Other Fine Arts"),
    ),
    **dict.fromkeys(
        ["Anthropology", "Economics", "Linguistics", "Psychology", "Sociology", "Other Social Science"],
        (None, "Social Science"),
    ),
    **dict.fromkeys(
        ["Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature"],
        ("Literature", None),
    ),
    **dict.fromkeys(["Beliefs", "Practices"], (None, None)),
}


@dataclass(frozen=True)
class LocalTossup:
    id: str
    question_sanitized: str
    answer: str
    answer_sanitized: str
    category: Optional[str]
    subcategory: Optional[str]
    difficulty: Optional[int]
    set_name: str


def _in(column: str, values) -> tuple:
    return f"{column} IN ({', '.join('?' for _ in values)})", list(values)


def build_where(filters: QuestionFilters) -> tuple:
    """
    Translate filters into a SQL WHERE clause and its parameters.

    Mirrors qbreader's /random-tossup: every filter is ANDed, and an
    alternate-subcategory filter also admits tossups that have no alternate
    subcategory at all. So selecting only "Drama" draws from all of
    Literature except tossups tagged with a different alternate subcategory.
    """
    alts = list(filters.alternate_subcategories or [])
    categories = []
    subcategories = list(filters.subcategories or [])
    for alt in alts:
        category, subcategory = ALT_SUBCATEGORY_PARENTS[alt]
        if category:
            categories.append(category)
        if subcategory:
            subcategories.append(subcategory)

    clauses, params = [], []
    if filters.difficulties:
        clause, values = _in("difficulty", [int(d) for d in filters.difficulties])
        clauses.append(clause)
        params += values
    if alts:
        clause, values = _in("alternate_subcategory", alts)
        clauses.append(f"({clause} OR alternate_subcategory IS NULL)")
        params += values
    if categories:
        clause, values = _in("category", categories)
        clauses.append(clause)
        params += values
    if subcategories:
        clause, values = _in("subcategory", subcategories)
        clauses.append(clause)
        params += values
    return (" AND ".join(clauses) or "1"), params


_COLUMNS = "id, question_sanitized, answer, answer_sanitized, category, subcategory, difficulty, set_name"


def _balanced_tossup(conn, where: str, params: list, exclude_ids) -> LocalTossup:
    """
    The draw for custom questions within a session. `exclude_ids` are the questions the session
    has already played. Subcategories take turns: a question comes from a subcategory that has
    the fewest excluded questions and still has one left, chosen at random among the ties. Within
    it, the least-played questions (times_played) come first, then random. Once every match is
    excluded, the exclusion is dropped (a new cycle) and any subcategory may be drawn.
    """
    excluded = list(dict.fromkeys(exclude_ids))
    is_excluded, ex_params = _in("id", excluded) if excluded else ("0", [])
    counts = conn.execute(
        f"SELECT subcategory, SUM({is_excluded}), SUM(NOT {is_excluded}) FROM tossups WHERE {where}"
        " GROUP BY subcategory",
        ex_params + ex_params + params,
    ).fetchall()
    if not counts:
        raise LookupError("No tossups in the local database match the selected categories and difficulties.")
    fresh = [(subcategory, seen) for subcategory, seen, unseen in counts if unseen]
    if fresh:
        fewest = min(seen for _, seen in fresh)
        subcategory = random.choice([s for s, seen in fresh if seen == fewest])
        where, params = f"{where} AND NOT {is_excluded}", params + ex_params
    else:
        subcategory = random.choice([s for s, _, _ in counts])
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tossups)")}
    least_played = "times_played, " if "times_played" in columns else ""  # an older file may lack it
    return LocalTossup(*conn.execute(
        f"SELECT {_COLUMNS} FROM tossups WHERE {where} AND subcategory IS ?"
        f" ORDER BY {least_played}RANDOM() LIMIT 1",
        params + [subcategory],
    ).fetchone())


class LocalQuestionSource:
    """Draws tossups from the database that sync.py builds."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def random_tossup(self, filters: QuestionFilters) -> LocalTossup:
        where, params = build_where(filters)
        conn = connect_readonly(self.db_path)
        if filters.balanced:
            try:
                return _balanced_tossup(conn, where, params, filters.exclude_ids or [])
            finally:
                conn.close()
        try:
            # Prefer a tossup nobody has rated yet (good_votes + bad_votes = 0) over one that
            # already has a vote; random within each of those two groups. The server draws custom
            # questions balanced instead (_balanced_tossup), and every qbreader-sourced row stays
            # at 0/0, so in practice this is a plain random draw.
            row = conn.execute(
                "SELECT id, question_sanitized, answer, answer_sanitized, category, subcategory, difficulty, set_name"
                f" FROM tossups WHERE {where}"
                " ORDER BY (good_votes + bad_votes > 0), RANDOM() LIMIT 1",
                params,
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise LookupError("No tossups in the local database match the selected categories and difficulties.")
        return LocalTossup(*row)

    async def rate_tossup(self, tossup_id: str, rating: str, previous: Optional[str] = None) -> tuple:
        """Record a player's "good" / "bad" vote on a custom question; returns its new (good, bad) totals."""
        return record_vote(self.db_path, tossup_id, rating, previous)

    async def record_play(self, tossup_id: str, clues_left: Optional[int]) -> tuple:
        """Count a finished round of a custom question; returns (times_played, times_answered, average)."""
        return record_play(self.db_path, tossup_id, clues_left)
