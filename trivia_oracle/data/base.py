"""
The two interfaces the game depends on for question data.

Any backend (the qbreader API today, a local SQLite database later) provides
a QuestionSource and an AnswerJudge. The game never imports a backend directly.
"""
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence


@dataclass(frozen=True)
class QuestionFilters:
    """Which tossups may be drawn. None on a field means "no filter"."""
    subcategories: Optional[Sequence[str]] = None
    alternate_subcategories: Optional[Sequence[str]] = None
    difficulties: Optional[Sequence[str]] = None  # qbreader numeric strings, "0"–"10"


class Tossup(Protocol):
    question_sanitized: str  # question text, no HTML
    answer: str              # answerline with HTML; judges need the <b>/<u> tags
    answer_sanitized: str    # answerline, no HTML (shown to players)


class Judgement(Protocol):
    directive: str                   # "accept" | "reject" | "prompt"
    directed_prompt: Optional[str]   # set only for directed prompts


class QuestionSource(Protocol):
    async def random_tossup(self, filters: QuestionFilters) -> Tossup: ...


class AnswerJudge(Protocol):
    async def check(self, answerline: str, given: str) -> Judgement: ...
