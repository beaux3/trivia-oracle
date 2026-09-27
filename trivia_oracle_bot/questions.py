"""
Wires the game to a question backend. QUESTION_BACKEND (config.py) picks it:
  api   — qbreader.org
  local — the SQLite database built by `python -m trivia_questions.local.sync`
Answers are judged by qbreader.org in both cases for now.

The game uses `question_source`, `answer_judge` and `QuestionFilters` only.
"""
from trivia_questions import (
    AnswerJudge, LocalQuestionSource, QbreaderAnswerJudge, QbreaderQuestionSource,
    QuestionFilters, QuestionSource,
)

from .config import QUESTION_BACKEND, QUESTIONS_DB

__all__ = ["QuestionFilters", "question_source", "answer_judge"]

if QUESTION_BACKEND == "api":
    question_source: QuestionSource = QbreaderQuestionSource()
elif QUESTION_BACKEND == "local":
    question_source = LocalQuestionSource(QUESTIONS_DB)
else:
    raise SystemExit(f'QUESTION_BACKEND must be "api" or "local", not "{QUESTION_BACKEND}".')

answer_judge: AnswerJudge = QbreaderAnswerJudge()
