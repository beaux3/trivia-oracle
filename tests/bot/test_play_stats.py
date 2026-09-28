"""After a custom round the bot reports the play to the backend, with how many clues were left when it was answered."""
import unittest
from types import SimpleNamespace
from unittest import mock

from trivia_oracle_bot.game import round as rnd
from tests.bot.test_ratings import END_HINT, _custom, _RoundCase, _tossup

FOUR_CLUES = "Clue one. Clue two. Clue three. Clue four."


class RecordPlayTest(_RoundCase):
    def setUp(self):
        super().setUp()
        self.backend.record_play = mock.AsyncMock(return_value=(1, 1, 2.0))
        for name in ("save_scores",):
            patch = mock.patch.object(rnd, name)
            patch.start()
            self.addCleanup(patch.stop)

    def plays_sent(self):
        return [call.args for call in self.backend.record_play.await_args_list]

    def play_answered_on_clue(self, tossup, clue_number, answers=1):
        """Start `tossup`, have `answers` players answer correctly while clue `clue_number` (1-based) is showing, and end the round."""
        messages = []
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=tossup)), \
             mock.patch.object(rnd.threading, "Thread"):
            rnd.start_round(messages.append, END_HINT, {})
        total = len(rnd.current_round["sentences"])
        rnd.current_round["hourglasses"] = total - (clue_number - 1)
        accept = SimpleNamespace(directive="accept", directed_prompt=None)
        with mock.patch.object(rnd, "_check_answer", mock.AsyncMock(return_value=accept)):
            for user_id in range(1, answers + 1):
                rnd.submit_answer(user_id, f"Player {user_id}", "answer", lambda _: None)
            # A later clue appearing mid-round does not change what the first correct answer recorded.
            rnd.current_round["hourglasses"] = 1
        with mock.patch.object(rnd.time, "sleep"):
            rnd._run_round(messages.append, END_HINT)
        return messages

    def test_an_answer_on_the_second_of_four_clues_leaves_two(self):
        self.play_answered_on_clue(_custom("merlion", question_sanitized=FOUR_CLUES), 2)
        self.assertEqual(self.plays_sent(), [("merlion", 2)])

    def test_an_answer_on_the_last_clue_leaves_none(self):
        self.play_answered_on_clue(_custom("merlion", question_sanitized=FOUR_CLUES), 4)
        self.assertEqual(self.plays_sent(), [("merlion", 0)])

    def test_only_the_first_correct_answer_counts(self):
        self.play_answered_on_clue(_custom("merlion", question_sanitized=FOUR_CLUES), 1, answers=3)
        self.assertEqual(self.plays_sent(), [("merlion", 3)])

    def test_an_unanswered_round_is_still_a_play(self):
        self.play(_custom("merlion"))
        self.assertEqual(self.plays_sent(), [("merlion", None)])

    def test_ordinary_rounds_and_custom_ones_without_an_id_are_not_reported(self):
        self.play(_tossup())
        self.play(_tossup(custom=True, category="Singapore"))
        self.assertEqual(self.plays_sent(), [])

    def test_the_count_is_reset_between_rounds(self):
        self.play_answered_on_clue(_custom("merlion", question_sanitized=FOUR_CLUES), 1)
        rnd.current_round["ended_at"] = None  # skip the rating gate
        self.play(_custom("laksa"))
        self.assertEqual(self.plays_sent(), [("merlion", 3), ("laksa", None)])

    def test_a_backend_failure_does_not_break_the_round(self):
        self.backend.record_play.side_effect = RuntimeError("backend down")
        messages = self.play(_custom("merlion"))
        self.assertTrue(any("[ROUND END]" in m for m in messages))
        self.assertFalse(rnd.current_round["active"])


if __name__ == "__main__":
    unittest.main()
