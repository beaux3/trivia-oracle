"""Custom questions: validating submission files and loading them into a database shaped like the qbreader copy."""
import json
import os
import tempfile
import unittest
from unittest import mock

from trivia_oracle_backend.custom import add
from trivia_oracle_backend.local.db import connect, connect_readonly

QUESTION = (
    "This quantity is conserved in the absence of external torques. Its SI units are kilogram meters squared "
    "per second. For 10 points, name this rotational analogue of linear momentum."
)


def record(**overrides):
    base = {
        "category": "Science", "subcategory": "Physics", "alternate_subcategory": None, "difficulty": 5,
        "question": QUESTION, "answer": "<b><u>angular momentum</u></b> [prompt on <u>momentum</u>]",
    }
    return {**base, **overrides}


class ValidateTest(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(add.validate(record()), [])

    def test_alternate_subcategory_needs_its_parent(self):
        self.assertEqual(add.validate(record(subcategory="Other Science", alternate_subcategory="Math")), [])
        self.assertTrue(add.validate(record(subcategory="Physics", alternate_subcategory="Math")))

    def test_rejects_bad_fields(self):
        for overrides in (
            {"category": "Sports"},
            {"subcategory": "American History"},
            {"difficulty": 0},
            {"difficulty": "5"},
            {"question": "Too short."},
            {"question": QUESTION + " <b>bold</b>"},
            {"answer": "  "},
            {"extra": 1},
        ):
            with self.subTest(overrides):
                self.assertTrue(add.validate(record(**overrides)))

    def test_singapore_is_a_category_of_its_own(self):
        self.assertEqual(add.validate(record(category="Singapore", subcategory="Singapore")), [])
        self.assertTrue(add.validate(record(category="Singapore", subcategory="Geography")))

    def test_snowsports_is_a_category_of_its_own(self):
        self.assertEqual(add.validate(record(category="Snowsports", subcategory="Snowsports")), [])
        self.assertTrue(add.validate(record(category="Snowsports", subcategory="Sports")))

    def test_memes_is_a_category_of_its_own(self):
        self.assertEqual(add.validate(record(category="Memes", subcategory="Memes")), [])
        self.assertTrue(add.validate(record(category="Memes", subcategory="Other Pop Culture")))

    def test_japan_is_a_category_of_its_own(self):
        self.assertEqual(add.validate(record(category="Japan", subcategory="Japan")), [])
        self.assertTrue(add.validate(record(category="Japan", subcategory="Geography")))

    def test_anime_is_a_custom_category_of_its_own(self):
        self.assertEqual(add.validate(record(category="Anime", subcategory="Anime")), [])
        self.assertTrue(add.validate(record(category="Anime", subcategory="Television")))
        self.assertTrue(add.validate(record(category="Anime", subcategory="Anime", alternate_subcategory="Film")))

    def test_cultivation_returner_slop_is_a_custom_category_of_its_own(self):
        genre = "Cultivation / Returner Slop"
        self.assertEqual(add.validate(record(category=genre, subcategory=genre)), [])
        self.assertTrue(add.validate(record(category=genre, subcategory="Anime")))
        self.assertTrue(add.validate(record(category="Anime", subcategory=genre)))

    def test_missing_field(self):
        incomplete = record()
        del incomplete["answer"]
        self.assertIn("missing", add.validate(incomplete)[0])


class AnswerCheckTest(unittest.TestCase):
    def test_finds_an_answer_given_away_in_the_question(self):
        # QUESTION mentions "external torques", which the judge accepts for "torque".
        self.assertEqual(add.leaked_phrase(record(answer="<b><u>torque</u></b>")), "torques")

    def test_finds_a_long_title_with_several_articles(self):
        title = "Legend of the Swordsmen of the Mountains of Shu"
        leaky = record(question=f"This novel is {title}. " + QUESTION, answer=f"<b><u>{title}</u></b>")
        self.assertIsNotNone(add.leaked_phrase(leaky))

    def test_finds_an_answer_split_into_two_words(self):
        leaky = record(question="Gas Light is the 1944 film behind this term. " + QUESTION,
                       answer="<b><u>gaslighting</u></b> [or <b><u>gaslight</u></b>]")
        self.assertEqual(add.leaked_phrase(leaky), "Gas Light")

    def test_prompted_words_are_not_leaks(self):
        # QUESTION says "linear momentum"; the answerline only prompts on "momentum".
        self.assertIsNone(add.leaked_phrase(record()))

    def test_a_rejected_near_miss_is_not_a_leak(self):
        near_miss = record(question="Its operators said official releases made it pointless for the average reader.",
                           answer="<b><u>Reaper</u></b> Scans")
        self.assertEqual(add.leaked_phrase(near_miss), "reader")  # typo tolerance: one letter from "Reaper"
        near_miss["answer"] += " [do not accept “reader”]"
        self.assertIsNone(add.leaked_phrase(near_miss))

    def test_repeated_answers_within_the_file_and_in_other_files(self):
        numbered = [(1, record()), (3, record(question=QUESTION + " Extra clue.")), (4, record(answer="<u>torque</u>"))]
        index = {"angular momentum": [("theirs.jsonl", 7)], "torque": [("mine.jsonl", 9)]}
        self.assertEqual(add.repeated_answers("mine.jsonl", numbered, index), [
            (1, "same answer as theirs.jsonl:7"),
            (3, "same answer as line 1"),
            (3, "same answer as theirs.jsonl:7"),
        ])  # mine.jsonl's own entry in the index (torque) is the same set, not a repeat


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "custom.db")
        # main() indexes every submission file for repeated answers; keep that to this test's own files.
        patcher = mock.patch.object(add, "SUBMISSIONS_DIR", self.dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, lines):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as f:
            f.write("\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n")
        return path

    def test_loads_into_the_qbreader_schema_and_is_repeatable(self):
        path = self.write("mine.jsonl", [record(), record(question=QUESTION + " Extra clue.", answer="<u>torque</u>")])
        for _ in range(2):
            self.assertEqual(add.main(["--db", self.db, path]), 0)
        conn = connect_readonly(self.db)
        self.assertEqual(conn.execute("SELECT name, packet_count, tossup_count FROM sets").fetchall(), [("mine", 1, 2)])
        rows = conn.execute(
            "SELECT set_name, number, category, subcategory, difficulty, answer_sanitized FROM tossups ORDER BY number"
        ).fetchall()
        self.assertEqual(rows[0], ("mine", 1, "Science", "Physics", 5, "angular momentum [prompt on momentum]"))
        self.assertEqual(rows[1][1], 2)

    def test_votes_start_at_zero_and_survive_a_reload(self):
        first, second = record(), record(question=QUESTION + " Extra clue.", answer="<u>torque</u>")
        path = self.write("mine.jsonl", [first, second])
        add.main(["--db", self.db, path])
        conn = connect(self.db)
        self.assertEqual(conn.execute("SELECT good_votes, bad_votes FROM tossups").fetchall(), [(0, 0), (0, 0)])
        conn.execute("UPDATE tossups SET good_votes = good_votes + 3, bad_votes = bad_votes + 1 WHERE number = 1")
        conn.commit()
        conn.close()
        # The file changes: question 1 stays, question 2 is replaced by a new one.
        path = self.write("mine.jsonl", [first, record(question=QUESTION + " Another clue.", answer="<u>spin</u>")])
        add.main(["--db", self.db, path])
        rows = connect_readonly(self.db).execute(
            "SELECT number, good_votes, bad_votes FROM tossups ORDER BY number").fetchall()
        self.assertEqual(rows, [(1, 3, 1), (2, 0, 0)])

    def test_sets_and_tossups_are_marked_custom(self):
        add.main(["--db", self.db, self.write("mine.jsonl", [record()])])
        conn = connect_readonly(self.db)
        self.assertEqual(conn.execute("SELECT is_custom FROM sets").fetchall(), [(1,)])
        self.assertEqual(conn.execute("SELECT is_custom FROM tossups").fetchall(), [(1,)])

    def test_invalid_file_is_not_loaded(self):
        path = self.write("bad.jsonl", [record(), "not json", record(difficulty=99)])
        self.assertEqual(add.main(["--db", self.db, path]), 1)
        conn = connect_readonly(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tossups").fetchone(), (0,))

    def test_duplicate_question_is_reported(self):
        _, errors, _ = add.load_file(self.write("dup.jsonl", [record(), record()]))
        self.assertTrue(any("duplicate of line 1" in e for e in errors))

    def test_check_fails_a_leaked_answer_but_loading_only_warns(self):
        path = self.write("leaky.jsonl", [record(answer="<b><u>torque</u></b>")])
        _, errors, _ = add.load_file(path, strict=True)
        self.assertEqual(errors, [f"{path}:1: the question gives away its own answer: 'torques'"])
        records, errors, warnings = add.load_file(path)
        self.assertEqual((len(records), errors), (1, []))
        self.assertEqual(warnings, [f"{path}:1: warning: the question gives away its own answer: 'torques'"])
        self.assertEqual(add.main(["--check", path]), 1)

    def test_repeated_answer_is_only_a_warning(self):
        path = self.write("repeat.jsonl", [record(), record(question=QUESTION + " Extra clue.")])
        records, errors, warnings = add.load_file(path, strict=True)
        self.assertEqual((len(records), errors), (2, []))
        self.assertEqual(warnings, [f"{path}:2: warning: same answer as line 1"])

    def test_check_writes_nothing(self):
        path = self.write("ok.jsonl", [record()])
        self.assertEqual(add.main(["--check", "--db", self.db, path]), 0)
        self.assertFalse(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
