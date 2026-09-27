"""
Question data for the game: where tossups come from and who judges answers.

The game uses `question_source` and `answer_judge` only. QUESTION_BACKEND
(config.py) picks where tossups come from:
  api   — qbreader.org (questions/api/)
  local — the SQLite database built by questions/local/sync.py
Answers are judged by qbreader.org in both cases for now.
"""
from ..config import QUESTION_BACKEND, QUESTIONS_DB
from .api import QbreaderAnswerJudge, QbreaderQuestionSource
from .base import AnswerJudge, Judgement, QuestionFilters, QuestionSource, Tossup
from .local import LocalQuestionSource

if QUESTION_BACKEND == "api":
    question_source: QuestionSource = QbreaderQuestionSource()
elif QUESTION_BACKEND == "local":
    question_source = LocalQuestionSource(QUESTIONS_DB)
else:
    raise SystemExit(f'QUESTION_BACKEND must be "api" or "local", not "{QUESTION_BACKEND}".')

answer_judge: AnswerJudge = QbreaderAnswerJudge()
