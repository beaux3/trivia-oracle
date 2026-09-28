"""A custom question with new wording should not repeat an answer in one session."""
import unittest
from unittest import mock

from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.questions import Tossup


def _custom(question, answer, tossup_id):
    return Tossup(
        question_sanitized=question,
        answer=f"<b><u>{answer}</u></b>",
        answer_sanitized=answer,
        custom=True,
        category="Memes",
        id=tossup_id,
    )


class QuestionSessionTest(unittest.TestCase):
    def test_paraphrased_custom_question_is_retried(self):
        first = _custom("Richard throws a disc across the road.", "What the fuck, Richard?!", "1")
        repeat = _custom("A disc golfer named Richard misses the basket.", "What the fuck, Richard?", "2")
        fresh = _custom("Name this dancing crab meme.", "Crab Rave", "3")
        session = {}

        with mock.patch.object(rnd, "_rating_still_required", return_value=False), \
             mock.patch.object(rnd.threading, "Thread"), \
             mock.patch.object(rnd, "_fetch_tossup", new=mock.AsyncMock(side_effect=[first, repeat, fresh])) as fetch:
            try:
                self.assertEqual(rnd.start_round(lambda _: None, "Next: /next", session), rnd.StartResult.STARTED)
                rnd.round_lock.release()  # the mocked round thread did not run
                self.assertEqual(rnd.start_round(lambda _: None, "Next: /next", session), rnd.StartResult.STARTED)
            finally:
                if rnd.round_lock.locked():
                    rnd.round_lock.release()
                rnd.current_round["active"] = False

        self.assertEqual(fetch.await_count, 3)
        self.assertIn(("custom_id", "1"), session["seen_tossups"])
        self.assertIn(("custom_id", "3"), session["seen_tossups"])
        self.assertNotIn(("custom_id", "2"), session["seen_tossups"])
        # The played id goes to the backend, and so does the reworded one turned down for the retry.
        self.assertEqual([c.args[0] for c in fetch.await_args_list], [[], ["1"], ["1", "2"]])


if __name__ == "__main__":
    unittest.main()
