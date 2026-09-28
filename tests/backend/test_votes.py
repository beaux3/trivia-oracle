"""Player votes on custom questions: how they are written into the database's good_votes / bad_votes."""
import asyncio
import os
import tempfile
import unittest

from trivia_oracle_backend.local import LocalQuestionSource
import sqlite3

from trivia_oracle_backend.local.db import connect, connect_readonly, record_play, record_vote, replace_set
from tests.integration.support import tossup


class VoteDatabaseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "custom.db")
        conn = connect(self.path)
        replace_set(conn, "Custom Set", 1, [tossup("merlion"), tossup("laksa")], custom=True)
        replace_set(conn, "qbreader Set", 1, [tossup("mitosis", set_name="qbreader Set")])
        conn.close()

    def votes(self, tossup_id):
        conn = connect_readonly(self.path)
        try:
            return conn.execute("SELECT good_votes, bad_votes FROM tossups WHERE id = ?", (tossup_id,)).fetchone()
        finally:
            conn.close()


class RecordVoteTest(VoteDatabaseCase):
    def test_a_first_vote_adds_one_to_that_side_and_returns_the_totals(self):
        self.assertEqual(record_vote(self.path, "merlion", "good"), (1, 0))
        self.assertEqual(record_vote(self.path, "laksa", "bad"), (0, 1))
        self.assertEqual(self.votes("merlion"), (1, 0))
        self.assertEqual(self.votes("laksa"), (0, 1))

    def test_votes_from_different_players_add_up(self):
        for _ in range(3):
            record_vote(self.path, "merlion", "good")
        record_vote(self.path, "merlion", "bad")
        self.assertEqual(self.votes("merlion"), (3, 1))

    def test_changing_a_vote_moves_it_to_the_other_side(self):
        record_vote(self.path, "merlion", "good")
        self.assertEqual(record_vote(self.path, "merlion", "bad", previous="good"), (0, 1))
        self.assertEqual(record_vote(self.path, "merlion", "good", previous="bad"), (1, 0))

    def test_changing_a_vote_leaves_other_players_votes_alone(self):
        for _ in range(2):
            record_vote(self.path, "merlion", "good")
        record_vote(self.path, "merlion", "bad")
        self.assertEqual(record_vote(self.path, "merlion", "bad", previous="good"), (1, 2))

    def test_a_count_never_goes_below_zero(self):
        self.assertEqual(record_vote(self.path, "merlion", "bad", previous="good"), (0, 1))

    def test_other_questions_are_untouched(self):
        record_vote(self.path, "merlion", "good")
        self.assertEqual(self.votes("laksa"), (0, 0))
        self.assertEqual(self.votes("mitosis"), (0, 0))

    def test_only_custom_questions_can_be_rated(self):
        with self.assertRaises(LookupError):
            record_vote(self.path, "mitosis", "good")
        self.assertEqual(self.votes("mitosis"), (0, 0))

    def test_unknown_question_is_a_lookup_error(self):
        with self.assertRaises(LookupError):
            record_vote(self.path, "nope", "good")

    def test_bad_ratings_are_refused_and_change_nothing(self):
        for rating, previous in (("great", None), ("good", "great"), (None, None), ("good", "")):
            with self.subTest(rating=rating, previous=previous):
                with self.assertRaises(ValueError):
                    record_vote(self.path, "merlion", rating, previous)
        self.assertEqual(self.votes("merlion"), (0, 0))

    def test_a_missing_database_is_not_created(self):
        missing = os.path.join(self._tmp.name, "missing.db")
        with self.assertRaises(FileNotFoundError):
            record_vote(missing, "merlion", "good")
        self.assertFalse(os.path.exists(missing))


class RecordPlayTest(VoteDatabaseCase):
    def stats(self, tossup_id):
        conn = connect_readonly(self.path)
        try:
            return conn.execute(
                "SELECT times_played, times_answered, avg_num_clues_left_when_answered FROM tossups WHERE id = ?",
                (tossup_id,),
            ).fetchone()
        finally:
            conn.close()

    def test_a_new_question_has_no_plays_and_no_average(self):
        self.assertEqual(self.stats("merlion"), (0, 0, None))

    def test_an_answered_play_counts_and_starts_the_average(self):
        self.assertEqual(record_play(self.path, "merlion", 3), (1, 1, 3.0))
        self.assertEqual(self.stats("merlion"), (1, 1, 3.0))

    def test_the_average_is_the_mean_of_every_answered_play(self):
        for clues_left in (3, 0, 2, 1):
            record_play(self.path, "merlion", clues_left)
        self.assertEqual(self.stats("merlion"), (4, 4, 1.5))

    def test_an_unanswered_play_counts_but_leaves_the_average_alone(self):
        record_play(self.path, "merlion", 4)
        self.assertEqual(record_play(self.path, "merlion", None), (2, 1, 4.0))
        self.assertEqual(record_play(self.path, "merlion", 1), (3, 2, 2.5))
        self.assertEqual(record_play(self.path, "laksa", None), (1, 0, None))

    def test_other_questions_and_votes_are_untouched(self):
        record_vote(self.path, "merlion", "good")
        record_play(self.path, "merlion", 2)
        self.assertEqual(self.votes("merlion"), (1, 0))
        self.assertEqual(self.stats("laksa"), (0, 0, None))

    def test_only_custom_questions_are_counted(self):
        with self.assertRaises(LookupError):
            record_play(self.path, "mitosis", 1)
        with self.assertRaises(LookupError):
            record_play(self.path, "nope", 1)
        self.assertEqual(self.stats("mitosis"), (0, 0, None))

    def test_bad_clue_counts_are_refused_and_change_nothing(self):
        for clues_left in (-1, 1.5, "2", True):
            with self.subTest(clues_left=clues_left):
                with self.assertRaises(ValueError):
                    record_play(self.path, "merlion", clues_left)
        self.assertEqual(self.stats("merlion"), (0, 0, None))

    def test_a_missing_database_is_not_created(self):
        missing = os.path.join(self._tmp.name, "missing.db")
        with self.assertRaises(FileNotFoundError):
            record_play(missing, "merlion", 1)
        self.assertFalse(os.path.exists(missing))

    def test_reloading_a_set_keeps_play_stats_and_votes(self):
        record_vote(self.path, "merlion", "bad")
        record_play(self.path, "merlion", 2)
        record_play(self.path, "merlion", None)
        conn = connect(self.path)
        # tossup() files rows under its own set name, "Test Set", whatever replace_set was told.
        replace_set(conn, "Test Set", 1, [tossup("merlion"), tossup("durian")], custom=True)
        conn.close()
        self.assertEqual(self.votes("merlion"), (0, 1))
        self.assertEqual(self.stats("merlion"), (2, 1, 2.0))
        self.assertEqual(self.stats("durian"), (0, 0, None))

    def test_an_older_database_without_the_columns_gets_them_and_keeps_its_votes(self):
        path = os.path.join(self._tmp.name, "older.db")
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("CREATE TABLE sets (name TEXT PRIMARY KEY, is_custom INTEGER NOT NULL DEFAULT 0)")
            conn.execute(
                "CREATE TABLE tossups (id TEXT PRIMARY KEY, good_votes INTEGER NOT NULL DEFAULT 0,"
                " bad_votes INTEGER NOT NULL DEFAULT 0, is_custom INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute("INSERT INTO tossups VALUES ('merlion', 5, 1, 1)")
        conn.close()
        self.assertEqual(record_play(path, "merlion", 1), (1, 1, 1.0))
        conn = sqlite3.connect(path)
        try:
            self.assertEqual(conn.execute("SELECT good_votes, bad_votes FROM tossups").fetchone(), (5, 1))
        finally:
            conn.close()


class LocalQuestionSourceRatingTest(VoteDatabaseCase):
    def test_rate_tossup_writes_the_vote(self):
        source = LocalQuestionSource(self.path)
        self.assertEqual(asyncio.run(source.rate_tossup("merlion", "good", None)), (1, 0))
        self.assertEqual(asyncio.run(source.rate_tossup("merlion", "bad", "good")), (0, 1))
        self.assertEqual(self.votes("merlion"), (0, 1))

    def test_record_play_writes_the_stats(self):
        source = LocalQuestionSource(self.path)
        self.assertEqual(asyncio.run(source.record_play("merlion", 2)), (1, 1, 2.0))
        self.assertEqual(asyncio.run(source.record_play("merlion", None)), (2, 1, 2.0))

    def test_drawn_tossups_carry_the_id_a_vote_needs(self):
        from trivia_oracle_backend import QuestionFilters
        tossup_drawn = asyncio.run(LocalQuestionSource(self.path).random_tossup(QuestionFilters()))
        self.assertIn(tossup_drawn.id, {"merlion", "laksa", "mitosis"})


if __name__ == "__main__":
    unittest.main()
