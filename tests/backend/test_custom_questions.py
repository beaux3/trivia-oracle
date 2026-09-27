"""Custom questions: validating submission files and loading them into a database shaped like the qbreader copy."""
import json
import os
import tempfile
import unittest

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

    def test_missing_field(self):
        incomplete = record()
        del incomplete["answer"]
        self.assertIn("missing", add.validate(incomplete)[0])


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "custom.db")

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
        _, errors = add.load_file(self.write("dup.jsonl", [record(), record()]))
        self.assertTrue(any("duplicate of line 1" in e for e in errors))

    def test_check_writes_nothing(self):
        path = self.write("ok.jsonl", [record()])
        self.assertEqual(add.main(["--check", "--db", self.db, path]), 0)
        self.assertFalse(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
