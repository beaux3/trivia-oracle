"""QuestionSource that draws tossups from the local SQLite database."""
from dataclasses import dataclass
from typing import Optional

from ..base import QuestionFilters
from .db import connect_readonly, record_vote

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


class LocalQuestionSource:
    """Draws tossups from the database that sync.py builds."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def random_tossup(self, filters: QuestionFilters) -> LocalTossup:
        where, params = build_where(filters)
        conn = connect_readonly(self.db_path)
        try:
            row = conn.execute(
                "SELECT id, question_sanitized, answer, answer_sanitized, category, subcategory, difficulty, set_name"
                f" FROM tossups WHERE {where} ORDER BY RANDOM() LIMIT 1",
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
