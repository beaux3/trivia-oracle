"""A live chat should not see the same tossup twice within its session."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

from trivia_oracle import round as rnd


def _tossup(question):
    return SimpleNamespace(question_sanitized=question, answer_sanitized="Answer", answer="Answer")


class QuestionSessionTest(unittest.TestCase):
    def setUp(self):
        self.bot = mock.Mock(username="TriviaOracleBot")
        self.chat_data = {}
        self.update = SimpleNamespace(effective_chat=SimpleNamespace(id=-100))
        self.context = SimpleNamespace(bot=self.bot, chat_data=self.chat_data)

    def tearDown(self):
        if rnd.round_lock.locked():
            rnd.round_lock.release()
        rnd.current_round["active"] = False

    def _next(self, at, *questions, context=None):
        fetch = mock.AsyncMock(side_effect=[_tossup(q) for q in questions])
        with mock.patch.object(rnd, "_fetch_tossup", fetch), \
             mock.patch.object(rnd.time, "monotonic", return_value=at), \
             mock.patch.object(rnd.threading, "Thread") as thread:
            rnd.start_round(self.update, context or self.context)
        if rnd.round_lock.locked():
            rnd.round_lock.release()  # the mocked round thread did not run
        return fetch.await_count, thread.call_count

    def test_retries_seen_question_then_resets_after_inactivity(self):
        self.assertEqual(self._next(0, "First clue."), (1, 1))
        self.assertEqual(self._next(60, "First clue.", "Second clue."), (2, 1))
        self.assertEqual(self.chat_data["seen_tossups"], {"First clue.", "Second clue."})

        self.assertEqual(self._next(60 + rnd.SESSION_TIMEOUT, "First clue."), (1, 1))
        self.assertEqual(self.chat_data["seen_tossups"], {"First clue."})

    def test_sessions_are_per_chat_and_exhausted_retries_do_not_repeat(self):
        self._next(0, "First clue.")
        other_chat = SimpleNamespace(bot=self.bot, chat_data={})
        self.assertEqual(self._next(10, "First clue.", context=other_chat), (1, 1))

        attempts = ("First clue.",) * rnd.QUESTION_FETCH_ATTEMPTS
        self.assertEqual(self._next(20, *attempts), (rnd.QUESTION_FETCH_ATTEMPTS, 0))
        self.assertEqual(self.chat_data["last_next"], 0)
        self.assertEqual(self.chat_data["seen_tossups"], {"First clue."})
        self.assertIn("Could not find a new question", self.bot.send_message.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
