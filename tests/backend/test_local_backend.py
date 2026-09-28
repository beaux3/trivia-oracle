"""The local SQLite backend: storing synced sets and drawing filtered tossups."""
import asyncio
import os
import sqlite3
import tempfile
import unittest

from trivia_oracle_backend import QuestionFilters
from trivia_oracle_backend.api import _VENDOR_DIR  # noqa: F401  (puts vendor/ on sys.path)
from trivia_oracle_backend.local import LocalQuestionSource
from trivia_oracle_backend.local import question_source as local_source
from trivia_oracle_backend.local.db import connect, replace_set, synced_set_names
from trivia_oracle_backend.local.sync import sync_set

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

    def test_unrated_tossups_are_drawn_before_rated_ones(self):
        # Every tossup but "drama" gets a vote, so a matching draw should always be "drama"
        # until it's the only one left unrated too.
        self.conn.execute("UPDATE tossups SET good_votes = 1 WHERE id != 'drama'")
        self.conn.commit()
        for _ in range(20):
            self.assertEqual(asyncio.run(self.source.random_tossup(QuestionFilters())).id, "drama")

    def test_once_everything_matching_is_rated_a_rated_one_is_still_drawn(self):
        self.conn.execute("UPDATE tossups SET bad_votes = 1")
        self.conn.commit()
        tossup = asyncio.run(self.source.random_tossup(QuestionFilters(subcategories=["Biology"])))
        self.assertIn(tossup.id, {"bio-easy", "bio-hard"})

    def test_no_filters_matches_everything(self):
        self.assertEqual(self._matching_ids(QuestionFilters()), {t["_id"] for t in TOSSUPS})

    def test_subcategory_and_difficulty_filters_combine(self):
        self.assertEqual(self._matching_ids(QuestionFilters(subcategories=["Biology"])), {"bio-easy", "bio-hard"})
        self.assertEqual(self._matching_ids(QuestionFilters(difficulties=["2", "3"])), {t["_id"] for t in TOSSUPS} - {"bio-hard"})

    def test_several_subcategories_are_a_union_not_an_intersection(self):
        # Two categories in the same filter are OR'd (IN (...)): picking "Biology" and
        # "European Literature" together must draw from both, not neither.
        self.assertEqual(self._matching_ids(QuestionFilters(subcategories=["Biology", "European Literature"])),
                          {"bio-easy", "bio-hard", "lit-plain"})
        draws = {asyncio.run(self.source.random_tossup(
            QuestionFilters(subcategories=["Biology", "European Literature"]))).id for _ in range(30)}
        self.assertEqual(draws, {"bio-easy", "bio-hard", "lit-plain"})

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
        with self.assertRaisesRegex(FileNotFoundError, "backend.local.sync"):
            asyncio.run(source.random_tossup(QuestionFilters()))

    def test_replace_set_overwrites_and_records_the_set(self):
        replace_set(self.conn, "Test Set", 2, TOSSUPS[:2])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tossups").fetchone()[0], 2)
        row = self.conn.execute("SELECT id, year, standard, packet_count, tossup_count FROM sets").fetchone()
        self.assertEqual(row, ("set-Test Set", 2024, 1, 2, 2))
        self.assertEqual(synced_set_names(self.conn), {"Test Set"})


class BalancedDrawTest(unittest.TestCase):
    """The custom-question draw: categories in turn, played ids skipped, least-played first."""

    CUSTOM = [
        _tossup("meme-1", "Memes", "Memes"), _tossup("meme-2", "Memes", "Memes"),
        _tossup("meme-3", "Memes", "Memes"), _tossup("meme-4", "Memes", "Memes"),
        _tossup("sg-1", "Singapore", "Singapore"),
        _tossup("jp-1", "Japan", "Japan"), _tossup("jp-2", "Japan", "Japan"),
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "custom_questions.db")
        conn = connect(self.db_path)
        replace_set(conn, "Custom", 1, self.CUSTOM, custom=True)
        conn.close()
        self.source = LocalQuestionSource(self.db_path)

    def draw(self, exclude=(), subcategories=None):
        return asyncio.run(self.source.random_tossup(
            QuestionFilters(subcategories=subcategories, exclude_ids=list(exclude), balanced=True)))

    def session(self, draws):
        played = []
        for _ in range(draws):
            played.append(self.draw(played).id)
        return played

    def test_a_session_plays_every_question_before_any_repeats(self):
        for _ in range(20):
            self.assertEqual(sorted(self.session(7)), sorted(t["_id"] for t in self.CUSTOM))

    def test_categories_take_turns_until_they_run_out(self):
        category = lambda id: id.split("-")[0]
        for _ in range(20):
            played = [category(id) for id in self.session(7)]
            self.assertEqual(sorted(played[:3]), ["jp", "meme", "sg"])
            self.assertEqual(sorted(played[3:5]), ["jp", "meme"])  # Singapore has no second question
            self.assertEqual(played[5:], ["meme", "meme"])

    def test_the_least_played_question_in_the_category_comes_first(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE tossups SET times_played = 3 WHERE id IN ('meme-1', 'meme-2', 'meme-4')")
        conn.execute("UPDATE tossups SET times_played = 1 WHERE id = 'meme-3'")
        conn.commit()
        conn.close()
        for _ in range(10):
            self.assertEqual(self.draw(subcategories=["Memes"]).id, "meme-3")
        # Once it has been played this session, the rest are tied and drawn at random.
        self.assertIn(self.draw(["meme-3"], subcategories=["Memes"]).id, {"meme-1", "meme-2", "meme-4"})

    def test_once_everything_is_played_it_starts_over(self):
        everything = [t["_id"] for t in self.CUSTOM]
        self.assertIn(self.draw(everything).id, everything)
        self.assertEqual(self.draw(["sg-1"], subcategories=["Singapore"]).id, "sg-1")

    def test_nothing_matching_is_a_lookup_error(self):
        with self.assertRaises(LookupError):
            self.draw(subcategories=["Anime"])


class AltSubcategoryParentsTest(unittest.TestCase):
    def test_matches_the_vendored_qbreader_client(self):
        for alt in local_source.ALT_SUBCATEGORY_PARENTS:
            category, subcategory = _api_utils.category_correspondence(AlternateSubcategory(alt))
            expected = (category and category.value, subcategory and subcategory.value)
            self.assertEqual(local_source.ALT_SUBCATEGORY_PARENTS[alt], expected, alt)


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


OLD_SCHEMA = """
CREATE TABLE sets (name TEXT PRIMARY KEY, id TEXT, year INTEGER, standard INTEGER,
                   packet_count INTEGER NOT NULL, tossup_count INTEGER NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE tossups (id TEXT PRIMARY KEY, set_name TEXT NOT NULL, packet_number INTEGER NOT NULL, number INTEGER,
                      category TEXT, subcategory TEXT, alternate_subcategory TEXT, difficulty INTEGER,
                      question_sanitized TEXT NOT NULL, answer TEXT NOT NULL, answer_sanitized TEXT NOT NULL,
                      updated_at TEXT);
INSERT INTO tossups (id, set_name, packet_number, question_sanitized, answer, answer_sanitized)
VALUES ('old', 'S', 1, 'q', 'a', 'a');
"""


class ColumnsAddedLaterTest(unittest.TestCase):
    def test_connect_upgrades_an_older_database_and_keeps_its_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "questions.db")
            old = sqlite3.connect(path)
            old.executescript(OLD_SCHEMA)
            old.close()
            conn = connect(path)
            self.assertEqual(conn.execute("SELECT good_votes, bad_votes, is_custom FROM tossups").fetchall(), [(0, 0, 0)])
            conn.execute("SELECT is_custom FROM sets")
            connect(path).close()  # a second connect finds the columns and changes nothing
            conn.close()

    def test_a_migrated_database_can_still_be_drawn_from_read_only(self):
        # Regression: random_tossup's ORDER BY references good_votes/bad_votes on every query
        # (LocalBackendTest.test_unrated_tossups_are_drawn_before_rated_ones), so a questions.db
        # synced before those columns existed fails every single draw until connect() migrates
        # it — connect_readonly() (used at request time) never alters the schema itself.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "questions.db")
            old = sqlite3.connect(path)
            old.executescript(OLD_SCHEMA)
            old.close()
            connect(path).close()
            tossup = asyncio.run(LocalQuestionSource(path).random_tossup(QuestionFilters()))
            self.assertEqual(tossup.id, "old")

    def test_replace_set_keeps_votes_and_qbreader_sets_are_not_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(os.path.join(tmp, "questions.db"))
            replace_set(conn, "S", 1, [_tossup("a", "Science", "Biology", set_name="S")])
            conn.execute("UPDATE tossups SET good_votes = 2, bad_votes = 1 WHERE id = 'a'")
            conn.commit()
            replace_set(conn, "S", 1, [_tossup("a", "Science", "Biology", set_name="S"),
                                       _tossup("b", "Science", "Physics", set_name="S")])
            self.assertEqual(
                conn.execute("SELECT id, good_votes, bad_votes, is_custom FROM tossups ORDER BY id").fetchall(),
                [("a", 2, 1, 0), ("b", 0, 0, 0)],
            )
            self.assertEqual(conn.execute("SELECT is_custom FROM sets").fetchall(), [(0,)])
            conn.close()


if __name__ == "__main__":
    unittest.main()
