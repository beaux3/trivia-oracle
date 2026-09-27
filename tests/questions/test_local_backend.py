"""The local SQLite backend: storing synced sets and drawing filtered tossups."""
import asyncio
import os
import tempfile
import unittest

from trivia_oracle_bot.config import ALL_ALT_SUBCATEGORIES
from trivia_oracle_bot.questions import QuestionFilters
from trivia_oracle_bot.questions.api import _VENDOR_DIR  # noqa: F401  (puts vendor/ on sys.path)
from trivia_oracle_bot.questions.local import LocalQuestionSource
from trivia_oracle_bot.questions.local import question_source as local_source
from trivia_oracle_bot.questions.local.db import connect, replace_set, synced_set_names
from trivia_oracle_bot.questions.local.sync import sync_set

from qbreader import _api_utils
from qbreader.types import AlternateSubcategory


def _tossup(id, category, subcategory, alt=None, difficulty=3, set_name="Test Set", packet=1):
    return {
        "_id": id,
        "set": {"_id": "set-" + set_name, "name": set_name, "year": 2024, "standard": True},
        "packet": {"_id": f"p{packet}", "name": f"Packet {packet}", "number": packet},
        "number": 1,
        "category": category,
        "subcategory": subcategory,
        "alternate_subcategory": alt,
        "difficulty": difficulty,
        "question": f"<b>{id}</b> question.",
        "question_sanitized": f"{id} question.",
        "answer": f"<b><u>{id}</u></b>",
        "answer_sanitized": id,
        "updatedAt": "2024-01-01T00:00:00.000Z",
    }


TOSSUPS = [
    _tossup("drama", "Literature", "American Literature", alt="Drama"),
    _tossup("poem", "Literature", "British Literature", alt="Poetry"),
    _tossup("lit-plain", "Literature", "European Literature"),
    _tossup("bio-easy", "Science", "Biology", difficulty=2),
    _tossup("bio-hard", "Science", "Biology", difficulty=8),
    _tossup("math", "Science", "Other Science", alt="Math"),
    _tossup("astro", "Science", "Other Science", alt="Astronomy"),
]


class LocalBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "questions.db")
        self.conn = connect(self.db_path)
        replace_set(self.conn, "Test Set", 1, TOSSUPS)
        self.source = LocalQuestionSource(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _matching_ids(self, filters: QuestionFilters) -> set:
        where, params = local_source.build_where(filters)
        return {id for (id,) in self.conn.execute(f"SELECT id FROM tossups WHERE {where}", params)}

    def test_random_tossup_has_the_fields_the_game_uses(self):
        tossup = asyncio.run(self.source.random_tossup(QuestionFilters(subcategories=["Biology"], difficulties=["8"])))
        self.assertEqual(tossup.id, "bio-hard")
        self.assertEqual(tossup.question_sanitized, "bio-hard question.")
        self.assertEqual(tossup.answer, "<b><u>bio-hard</u></b>")
        self.assertEqual(tossup.answer_sanitized, "bio-hard")

    def test_no_filters_matches_everything(self):
        self.assertEqual(self._matching_ids(QuestionFilters()), {t["_id"] for t in TOSSUPS})

    def test_subcategory_and_difficulty_filters_combine(self):
        self.assertEqual(self._matching_ids(QuestionFilters(subcategories=["Biology"])), {"bio-easy", "bio-hard"})
        self.assertEqual(self._matching_ids(QuestionFilters(difficulties=["2", "3"])), {t["_id"] for t in TOSSUPS} - {"bio-hard"})

    def test_alternate_subcategory_matches_like_qbreader(self):
        # qbreader adds the parent subcategory and also admits untagged tossups.
        self.assertEqual(self._matching_ids(QuestionFilters(alternate_subcategories=["Math"])), {"math"})
        # Drama adds category Literature; untagged Literature tossups match too.
        self.assertEqual(self._matching_ids(QuestionFilters(alternate_subcategories=["Drama"])), {"drama", "lit-plain"})

    def test_no_match_raises(self):
        with self.assertRaises(LookupError):
            asyncio.run(self.source.random_tossup(QuestionFilters(subcategories=["Opera"])))

    def test_missing_database_says_how_to_build_it(self):
        source = LocalQuestionSource(os.path.join(self.tmp.name, "missing.db"))
        with self.assertRaisesRegex(FileNotFoundError, "questions.local.sync"):
            asyncio.run(source.random_tossup(QuestionFilters()))

    def test_replace_set_overwrites_and_records_the_set(self):
        replace_set(self.conn, "Test Set", 2, TOSSUPS[:2])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tossups").fetchone()[0], 2)
        row = self.conn.execute("SELECT id, year, standard, packet_count, tossup_count FROM sets").fetchone()
        self.assertEqual(row, ("set-Test Set", 2024, 1, 2, 2))
        self.assertEqual(synced_set_names(self.conn), {"Test Set"})


class AltSubcategoryParentsTest(unittest.TestCase):
    def test_matches_the_vendored_qbreader_client(self):
        for alt in ALL_ALT_SUBCATEGORIES:
            category, subcategory = _api_utils.category_correspondence(AlternateSubcategory(alt))
            expected = (category and category.value, subcategory and subcategory.value)
            self.assertEqual(local_source._ALT_SUBCATEGORY_PARENTS[alt], expected, alt)


class FakeClient:
    def __init__(self, packets):
        self.packets = packets
        self.requested = []

    def packet_count(self, set_name):
        return len(self.packets)

    def packet_tossups(self, set_name, packet_number):
        self.requested.append(packet_number)
        return self.packets[packet_number - 1]


class SyncSetTest(unittest.TestCase):
    def test_stores_every_packet_of_a_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(os.path.join(tmp, "questions.db"))
            client = FakeClient([
                [_tossup("a", "Science", "Biology", set_name="S", packet=1)],
                [_tossup("b", "Science", "Physics", set_name="S", packet=2),
                 _tossup("c", "Science", "Chemistry", set_name="S", packet=2)],
            ])
            self.assertEqual(sync_set(client, conn, "S"), 3)
            self.assertEqual(client.requested, [1, 2])
            self.assertEqual(
                conn.execute("SELECT packet_count, tossup_count FROM sets WHERE name = 'S'").fetchone(), (2, 3),
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
