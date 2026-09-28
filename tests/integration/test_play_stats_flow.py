"""
Custom question play stats end to end: rounds played through game.round and the bot's HTTP client,
against the real backend writing times_played / times_answered / avg_num_clues_left_when_answered
into a real (temporary) custom_questions.db seeded with a dummy question.
"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from tests.integration.support import LocalStack, tossup, wait_until

from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.game import scores as score_store
from trivia_oracle_bot.game.round import StartResult
from trivia_oracle_bot.game.settings import settings
from trivia_oracle_bot.questions import BackendAnswerJudge, BackendQuestionSource

# The dummy custom question: four clues, answered with "dummyanswer".
DUMMY = tossup(
    "dummy-custom", "Singapore", "Singapore", difficulty=1, answer="dummyanswer",
    question="Dummy clue one. Dummy clue two. Dummy clue three. Dummy clue four.",
)


class PlayStatsFlowTest(unittest.TestCase):
    def setUp(self):
        # A fresh database per test, so every test starts from 0 plays.
        self.stack = LocalStack([tossup("mitosis")], custom_tossups=[DUMMY])
        self.addCleanup(self.stack.close)

        saved = dict(vars(settings))
        self.addCleanup(lambda: (vars(settings).clear(), vars(settings).update(saved)))
        settings.custom_all = True
        settings.selected_categories = set()  # custom only, so every round is the dummy question
        settings.sentence_interval = 0.4
        settings.answer_wait = 0.1

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patches = [
            mock.patch.object(rnd, "question_source", BackendQuestionSource(self.stack.url)),
            mock.patch.object(rnd, "answer_judge", BackendAnswerJudge(self.stack.url)),
            mock.patch.object(score_store, "SCORES_FILE", os.path.join(self._tmp.name, "scores.md")),
            mock.patch.object(rnd, "RATING_GRACE_PERIOD", 0),  # back-to-back rounds without rating each one
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        score_store.scores.clear()
        self.messages = []

    def tearDown(self):
        wait_until(lambda: not rnd.round_lock.locked())
        score_store.scores.clear()
        rnd.current_round["rating"] = None
        rnd.current_round["ended_at"] = None

    def stats(self, tossup_id="dummy-custom"):
        conn = sqlite3.connect(self.stack.custom_db_path)
        try:
            return conn.execute(
                "SELECT times_played, times_answered, avg_num_clues_left_when_answered FROM tossups WHERE id = ?",
                (tossup_id,),
            ).fetchone()
        finally:
            conn.close()

    def play(self, answer_on_clue=None, answer="dummyanswer"):
        """Play one round of the dummy question; answer while clue `answer_on_clue` (1-4) is showing, or never."""
        self.messages.clear()
        self.assertEqual(rnd.start_round(self.messages.append, "", {}), StartResult.STARTED)
        if answer_on_clue is not None:
            marker = "🎯" * answer_on_clue + "\n"
            self.assertTrue(wait_until(lambda: any(m.startswith(marker) for m in self.messages)),
                            f"clue {answer_on_clue} was never shown")
            rnd.submit_answer(1, "Ada", answer, lambda _: None)
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")

    def test_the_dummy_question_starts_with_no_stats(self):
        self.assertEqual(self.stats(), (0, 0, None))

    def test_answering_on_the_first_clue_records_three_clues_left(self):
        self.play(answer_on_clue=1)
        self.assertIn("Congrats Ada answered correctly!", "\n".join(self.messages))
        self.assertEqual(self.stats(), (1, 1, 3.0))

    def test_answering_on_the_third_clue_records_one_clue_left(self):
        self.play(answer_on_clue=3)
        self.assertEqual(self.stats(), (1, 1, 1.0))

    def test_answering_on_the_last_clue_records_zero(self):
        self.play(answer_on_clue=4)
        self.assertEqual(self.stats(), (1, 1, 0.0))

    def test_an_unanswered_round_counts_as_played_but_not_answered(self):
        self.play()
        self.assertIn("nobody answered correctly", "\n".join(self.messages))
        self.assertEqual(self.stats(), (1, 0, None))

    def test_a_wrong_answer_is_not_an_answer(self):
        self.play(answer_on_clue=1, answer="banana")
        self.assertEqual(self.stats(), (1, 0, None))

    def test_the_average_is_over_answered_rounds_only(self):
        self.play(answer_on_clue=1)  # 3 left
        self.play()                  # unanswered: played, not in the average
        self.play(answer_on_clue=4)  # 0 left
        self.play(answer_on_clue=3)  # 1 left
        played, answered, average = self.stats()
        self.assertEqual((played, answered), (4, 3))
        self.assertAlmostEqual(average, (3 + 0 + 1) / 3)

    def test_ordinary_questions_are_not_tracked(self):
        settings.custom_all = False
        settings.selected_categories = {"Biology"}
        settings.selected_difficulties = {"College ⭐⭐⭐ (8)"}  # tossup()'s default difficulty
        self.play()
        conn = sqlite3.connect(self.stack.db_path)
        try:
            row = conn.execute(
                "SELECT times_played, times_answered, avg_num_clues_left_when_answered FROM tossups WHERE id = 'mitosis'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, (0, 0, None))
        self.assertEqual(self.stats(), (0, 0, None))


if __name__ == "__main__":
    unittest.main()
