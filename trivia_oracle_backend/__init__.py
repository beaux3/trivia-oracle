"""
Question data for trivia games: where tossups come from and who judges answers.

Independent of the Telegram bot; nothing in this package may import
`telegram` or `trivia_oracle_bot`. Backends:
  api/   — qbreader.org through the vendored client
  local/ — a SQLite copy of qbreader, built by `python -m trivia_oracle_backend.local.sync`,
           and an answer checker that runs in-process (no network)
"""
from .api import QbreaderAnswerJudge, QbreaderQuestionSource
from .base import AnswerJudge, Judgement, QuestionFilters, QuestionSource, Tossup
from .local import LocalAnswerJudge, LocalQuestionSource

__all__ = [
    "AnswerJudge", "Judgement", "QuestionFilters", "QuestionSource", "Tossup",
    "QbreaderAnswerJudge", "QbreaderQuestionSource", "LocalAnswerJudge", "LocalQuestionSource",
]
