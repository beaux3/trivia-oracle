"""
Client for the question backend service (trivia_oracle_backend), over HTTP.

The bot and the backend never import each other; the JSON wire format
described in trivia_oracle_backend/server.py is the whole contract. The game
uses `question_source`, `answer_judge` and `QuestionFilters` only.
"""
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

import aiohttp

from .config import BACKEND_URL

__all__ = ["QuestionFilters", "Tossup", "Judgement", "question_source", "answer_judge"]

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


@dataclass(frozen=True)
class QuestionFilters:
    """Which tossups may be drawn. None on a field means "no filter"."""
    subcategories: Optional[Sequence[str]] = None
    alternate_subcategories: Optional[Sequence[str]] = None
    difficulties: Optional[Sequence[str]] = None  # qbreader numeric strings, "0"–"10"
    # Custom questions ignore the three filters above: "exclude" never draws one, "only" always
    # does, and "include" mixes them in with the others (the backend picks).
    custom: str = "exclude"
    # Restricts a custom draw to these custom-only category names (config.CUSTOM_CATEGORIES);
    # None draws from the whole custom database regardless of category.
    custom_subcategories: Optional[Sequence[str]] = None


@dataclass(frozen=True)
class Tossup:
    question_sanitized: str  # question text, no HTML
    answer: str              # answerline with HTML; the judge needs the <b>/<u> tags
    answer_sanitized: str    # answerline, no HTML (shown to players)
    custom: bool = False               # a hand-written question from the custom database
    category: Optional[str] = None     # only sent for custom questions
    id: Optional[str] = None           # only sent for custom questions: what a vote is recorded against


@dataclass(frozen=True)
class Judgement:
    directive: str                   # "accept" | "reject" | "prompt"
    directed_prompt: Optional[str]   # set only for directed prompts
    final: bool = False              # the backend's verdict is exact; do not apply extra leniency to a reject


class BackendClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def _post(self, path: str, payload: dict) -> dict:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.post(self.base_url + path, json=payload) as response:
                if response.status == 404:
                    raise LookupError((await response.json()).get("error", "Not found"))
                if response.status != 200:
                    raise RuntimeError(f"Question backend {path} returned {response.status}: {(await response.text())[:200]}")
                return await response.json()


class BackendQuestionSource(BackendClient):
    async def random_tossup(self, filters: QuestionFilters) -> Tossup:
        return Tossup(**await self._post("/random-tossup", asdict(filters)))


    async def rate_tossup(self, tossup_id: str, rating: str, previous: Optional[str]) -> tuple:
        """
        Record one player's "good" / "bad" vote on a custom question; returns its new (good, bad) totals.

        `previous` is that player's earlier vote on it, if any, which the backend withdraws.
        Raises LookupError if the question is unknown or not a custom one.
        """
        body = await self._post("/rate-tossup", {"id": tossup_id, "rating": rating, "previous": previous})
        return body["good_votes"], body["bad_votes"]


class BackendAnswerJudge(BackendClient):
    async def check(self, answerline: str, given: str) -> Judgement:
        return Judgement(**await self._post("/check-answer", {"answerline": answerline, "given": given}))


question_source = BackendQuestionSource(BACKEND_URL)
answer_judge = BackendAnswerJudge(BACKEND_URL)
