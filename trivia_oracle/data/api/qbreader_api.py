from qbreader.asynchronous import Async

from ..base import QuestionFilters


class QbreaderQuestionSource:
    """Draws tossups from qbreader's /random-tossup endpoint."""

    async def random_tossup(self, filters: QuestionFilters):
        async with await Async.create() as qb:
            tossups = await qb.random_tossup(
                number=1,
                subcategories=filters.subcategories,
                alternate_subcategories=filters.alternate_subcategories,
                difficulties=filters.difficulties,
            )
        return tossups[0]


class QbreaderAnswerJudge:
    """Judges answers with qbreader's /check-answer endpoint."""

    async def check(self, answerline: str, given: str):
        async with await Async.create() as qb:
            return await qb.check_answer(answerline, given)
