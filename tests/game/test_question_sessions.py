"""No question, custom or ordinary, should repeat within one session."""
import asyncio
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


class FreshTossupTest(unittest.TestCase):
    """_fetch_fresh_tossup: what counts as a repeat within a session, and when custom questions start over."""

    def fetch(self, seen, *tossups):
        with mock.patch.object(rnd, "_fetch_tossup", new=mock.AsyncMock(side_effect=list(tossups))) as fetch:
            tossup, seen = asyncio.run(rnd._fetch_fresh_tossup(set(seen)))
        return tossup, seen, [sorted(c.args[0]) for c in fetch.await_args_list]

    def test_every_played_custom_id_is_sent_to_the_backend(self):
        a, b = _custom("Clue A.", "Alpha", "a"), _custom("Clue B.", "Bravo", "b")
        c = _custom("Clue C.", "Charlie", "c")
        seen = {"An ordinary clue.", *rnd._session_keys(a), *rnd._session_keys(b)}
        tossup, _, sent = self.fetch(seen, c)
        self.assertIs(tossup, c)
        self.assertEqual(sent, [["a", "b"]])

    def test_a_repeated_custom_id_starts_the_custom_questions_over_but_not_the_ordinary_ones(self):
        a, b = _custom("Clue A.", "Alpha", "a"), _custom("Clue B.", "Bravo", "b")
        seen = {"An ordinary clue.", *rnd._session_keys(a), *rnd._session_keys(b)}
        # The backend only sends a played id back once every custom question it could draw is played.
        tossup, seen, _ = self.fetch(seen, a)
        self.assertIs(tossup, a)
        self.assertEqual(seen, {"An ordinary clue."})

    def test_the_same_custom_question_under_another_id_is_a_repeat(self):
        first = _custom("Name this dancing crab meme.", "Crab Rave", "1")
        copy = _custom("Name this dancing crab meme.", "Crab Rave (song)", "9")
        fresh = _custom("Name this dog meme.", "Doge", "3")
        tossup, _, sent = self.fetch(rnd._session_keys(first), copy, fresh)
        self.assertIs(tossup, fresh)
        self.assertEqual(sent, [["1"], ["1", "9"]])

    def test_an_ordinary_repeat_is_redrawn(self):
        tossup, _, _ = self.fetch({"First clue."}, _ordinary("First clue."), _ordinary("Second clue."))
        self.assertEqual(tossup.question_sanitized, "Second clue.")

    def test_running_out_of_attempts_returns_nothing_rather_than_a_repeat(self):
        first = _custom("Richard throws a disc.", "What the fuck, Richard?!", "1")
        rewordings = [_custom(f"Richard, take {i}.", "What the fuck, Richard?", str(i + 10))
                      for i in range(rnd.QUESTION_FETCH_ATTEMPTS)]
        seen = set(rnd._session_keys(first))
        tossup, after, sent = self.fetch(seen, *rewordings)
        self.assertIsNone(tossup)
        self.assertEqual(after, seen)
        self.assertEqual(len(sent), rnd.QUESTION_FETCH_ATTEMPTS)
        self.assertEqual(sent[-1], sorted(["1"] + [t.id for t in rewordings[:-1]]))


def _ordinary(question):
    return Tossup(question_sanitized=question, answer="<b><u>Answer</u></b>", answer_sanitized="Answer")


if __name__ == "__main__":
    unittest.main()
