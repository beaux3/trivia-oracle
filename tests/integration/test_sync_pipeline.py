"""sync -> questions.db -> backend service -> bot client: what a sync run makes playable."""
import asyncio
import os
import tempfile
import unittest

from tests.integration.support import BackendServer, ScriptedJudge, tossup

from trivia_oracle_backend.local import LocalQuestionSource
from trivia_oracle_backend.local.db import connect, synced_set_names
from trivia_oracle_backend.local.sync import sync_set
from trivia_oracle_bot.questions import BackendQuestionSource, QuestionFilters


class FakeQbreader:
    """The three /set-list-adjacent calls sync_set makes, served from memory."""

    def __init__(self, sets):
        self.sets = sets  # {set name: [packet tossup lists]}

    def packet_count(self, set_name):
        return len(self.sets[set_name])

    def packet_tossups(self, set_name, packet_number):
        return self.sets[set_name][packet_number - 1]


class SyncPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "data", "questions.db")  # sync creates the directory
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.client = FakeQbreader({
            "HS Set": [
                [tossup("hs-bio", "Science", "Biology", difficulty=3, set_name="HS Set")],
                [tossup("hs-hist", "History", "American History", difficulty=2, set_name="HS Set", packet=2)],
            ],
            "College Set": [
                [tossup("col-phys", "Science", "Physics", difficulty=9, set_name="College Set")],
            ],
        })

    def serve(self):
        server = BackendServer(LocalQuestionSource(self.db_path), ScriptedJudge()).start()
        self.addCleanup(server.stop)
        return BackendQuestionSource(server.url)

    def draws(self, source, filters, times=40):
        return {asyncio.run(source.random_tossup(filters)).answer_sanitized for _ in range(times)}

    def test_synced_sets_become_drawable_through_the_bot_client(self):
        sync_set(self.client, self.conn, "HS Set")
        sync_set(self.client, self.conn, "College Set")
        source = self.serve()

        self.assertEqual(self.draws(source, QuestionFilters(difficulties=["2", "3"])), {"hs-bio", "hs-hist"})
        self.assertEqual(self.draws(source, QuestionFilters(difficulties=["9"])), {"col-phys"})
        self.assertEqual(self.draws(source, QuestionFilters(subcategories=["Physics"])), {"col-phys"})

    def test_difficulty_with_no_synced_set_raises_lookup_error_until_that_set_is_synced(self):
        sync_set(self.client, self.conn, "College Set")
        source = self.serve()
        hs = QuestionFilters(difficulties=["2", "3"])
        with self.assertRaises(LookupError):
            asyncio.run(source.random_tossup(hs))

        # A later sync is visible to the already-running service: it opens the DB per request.
        sync_set(self.client, self.conn, "HS Set")
        self.assertEqual(self.draws(source, hs), {"hs-bio", "hs-hist"})

    def test_resyncing_a_set_replaces_it_instead_of_duplicating(self):
        sync_set(self.client, self.conn, "HS Set")
        self.client.sets["HS Set"] = [[tossup("hs-new", "Science", "Chemistry", difficulty=3, set_name="HS Set")]]
        sync_set(self.client, self.conn, "HS Set")
        source = self.serve()

        self.assertEqual(self.draws(source, QuestionFilters()), {"hs-new"})
        self.assertEqual(synced_set_names(self.conn), {"HS Set"})

    def test_backend_serves_read_only_and_never_alters_the_database(self):
        sync_set(self.client, self.conn, "HS Set")
        before = self.conn.execute("SELECT COUNT(*), MAX(synced_at) FROM sets").fetchone()
        self.draws(self.serve(), QuestionFilters())
        self.assertEqual(self.conn.execute("SELECT COUNT(*), MAX(synced_at) FROM sets").fetchone(), before)


if __name__ == "__main__":
    unittest.main()
