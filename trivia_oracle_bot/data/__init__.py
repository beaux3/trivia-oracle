"""
Question data for the game: where tossups come from and who judges answers.

The game uses `question_source` and `answer_judge` only. Both are currently
backed by the qbreader API (data/api/); a local backend will sit beside it.
"""
from .api import QbreaderAnswerJudge, QbreaderQuestionSource
from .base import AnswerJudge, Judgement, QuestionFilters, QuestionSource, Tossup

question_source: QuestionSource = QbreaderQuestionSource()
answer_judge: AnswerJudge = QbreaderAnswerJudge()
