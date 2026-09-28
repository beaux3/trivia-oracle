"""Custom questions: validating submission files and loading them into a database shaped like the qbreader copy."""
import json
import os
import tempfile
import unittest
from unittest import mock

from trivia_oracle_backend.custom import add
from trivia_oracle_backend.local.db import connect, connect_readonly

LEAD = ("Kepler's second law, the equal-areas law, follows from the conservation of this quantity for a planet "
        "orbiting the Sun.")
MIDDLE = [
    "Its SI units are kilogram meters squared per second, the same units as those of Planck's constant.",
    "For a point particle, it is the cross product of the position vector with the particle's mass times velocity.",
    "It is conserved in the absence of external torques, so a figure skater spins faster after pulling in her arms.",
]
GIVEAWAY = "For 10 points, name this rotational counterpart of mass times velocity."
QUESTION = " ".join([LEAD, *MIDDLE, GIVEAWAY])


def question(*extra):
    """QUESTION with more clues before the giveaway, for a different but still valid question."""
    return " ".join([LEAD, *MIDDLE, *extra, GIVEAWAY])


def record(**overrides):
    base = {
        "category": "Science", "subcategory": "Physics", "alternate_subcategory": None, "difficulty": 5,
        "question": QUESTION, "answer": "<b><u>angular momentum</u></b> [prompt on <u>momentum</u>]",
    }
    return {**base, **overrides}


EXTRA = "Noether's theorem ties its conservation to the rotational symmetry of space."
OTHER_ANSWER = "<b><u>moment of inertia</u></b>"


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


class QuestionRulesTest(unittest.TestCase):
    """CONTRIBUTING.md's writing rules for the question, as validate() reports them."""

    def assertFlags(self, question, fragment):
        problems = add.validate(record(question=question))
        self.assertTrue(any(fragment in p for p in problems), f"no problem mentions {fragment!r}: {problems}")

    def test_the_example_question_passes(self):
        self.assertEqual(add.question_problems(QUESTION), [])
        self.assertEqual(add.question_problems(question(EXTRA)), [])

    def test_four_to_seven_sentences(self):
        self.assertFlags(" ".join([LEAD, MIDDLE[0], GIVEAWAY]), "3 sentences")
        self.assertFlags(question(*[EXTRA] * 4), "9 sentences")

    def test_sentence_length(self):
        long_clue = "It appears in " + ", ".join(["the orbit of a planet"] * 9) + " alike."
        self.assertFlags(question(long_clue), "keep each clue to at most 40")
        self.assertFlags(question("It is conserved."), "has only 3 words")

    def test_total_length(self):
        short = ("This quantity is conserved for planets. Its units are kilogram meters squared per second. "
                 "A skater spins faster with it. For 10 points, name this quantity.")
        self.assertFlags(short, "a tossup has 60 to 200")

    def test_giveaway_is_the_last_sentence_only(self):
        self.assertFlags(" ".join([LEAD, GIVEAWAY, *MIDDLE]), "must be the giveaway")
        self.assertFlags(" ".join([LEAD, *MIDDLE, "Name this rotational counterpart of mass times velocity."]),
                         "must be the giveaway")
        self.assertFlags(question(GIVEAWAY), "must be the giveaway")

    def test_giveaway_points_at_the_answer(self):
        self.assertFlags(" ".join([LEAD, *MIDDLE, "For 10 points, a skater's spin shows it clearly."]),
                         "giveaway must point at the answer")
        self.assertEqual(add.question_problems(" ".join(
            [LEAD, *MIDDLE, "For 10 points, give the two-word name of the rotational counterpart of velocity."])), [])

    def test_lead_points_at_the_answer(self):
        vague = "Kepler's second law, the equal-areas law, follows from a conservation law for planets orbiting the Sun."
        self.assertFlags(" ".join([vague, *MIDDLE, GIVEAWAY]), "first sentence never points at the answer")
        for lead in ("Its conservation explains Kepler's second law, the equal-areas law, for planets orbiting the Sun.",
                     "Kepler's second law here follows from a conservation law for planets orbiting the Sun."):
            with self.subTest(lead):
                self.assertEqual(add.question_problems(" ".join([lead, *MIDDLE, GIVEAWAY])), [])

    def test_sentence_boundary_traps(self):
        self.assertFlags(question('A physicist once wrote "It is everywhere. Nobody escapes it" in a letter to a friend.'),
                         "inside a quotation")
        self.assertFlags(question("A deficiency of vitamin C. Sailors lacking it suffered from scurvy on long voyages."),
                         "takes 'C.' for an initial")
        self.assertEqual(add.question_problems(question("A song by J. Cole uses it as a metaphor for his rising career.")),
                         [])

    def test_quotes(self):
        self.assertFlags(question("One textbook calls it 'the spin quantity' in a chapter on rigid bodies."),
                         "single quotes")
        self.assertFlags(question('One textbook calls it "the spin quantity” in a chapter on rigid bodies.'),
                         "opens a quote with")
        self.assertFlags(question('One textbook calls it "the spin quantity in a chapter on rigid bodies.'),
                         "never closed")

    def test_plain_text(self):
        for bad in ("TOSSUP: " + QUESTION, "1. " + QUESTION, QUESTION.replace("this quantity", "**this quantity**"),
                    question("It is explained at https://example.com in a long article about physics."),
                    QUESTION.replace("Its SI", "Its  SI"), QUESTION.replace("Its SI", "Its​SI"), QUESTION + " ",
                    QUESTION.rstrip(".")):
            with self.subTest(bad):
                self.assertTrue(add.question_problems(bad))
        blank = question('A textbook exercise asks students to complete the phrase "conservation of ___" in class.')
        self.assertEqual(add.question_problems(blank), [])


class AnswerRulesTest(unittest.TestCase):
    """CONTRIBUTING.md's rules for the answerline, as validate() reports them."""

    def assertFlags(self, answer, fragment):
        problems = add.answer_problems(answer)
        self.assertTrue(any(fragment in p for p in problems), f"no problem mentions {fragment!r}: {problems}")

    def test_the_example_answer_passes(self):
        self.assertEqual(add.answer_problems(record()["answer"]), [])

    def test_only_emphasis_tags(self):
        self.assertFlags("<b><u>angular momentum</u></b><br>", "only <b>, <u>")
        self.assertFlags("<b><u>angular momentum</b></u>", "unclosed or mismatched tag")
        self.assertFlags("<b><u>angular momentum</u>", "unclosed or mismatched tag")
        self.assertFlags("<b><u>angular momentum</u></b> [or <b><u>L</u></b>", "unbalanced")

    def test_instructions_for_a_human_are_rejected(self):
        self.assertFlags("<b><u>angular momentum</u></b> [prompt on partial answer]", "'partial'")
        self.assertFlags("<b><u>angular momentum</u></b> [or equivalents like <b><u>spin momentum</u></b>]",
                         "'equivalents'")
        for fine in ("<b><u>angular momentum</u></b> [accept word forms like <b><u>angular momenta</u></b>]",
                     "<b><u>angular</u></b> <b><u>momentum</u></b> [accept either underlined portion]",
                     "<b><u>angular momentum</u></b> [prompt on <u>momentum</u> by asking \"Which kind, any idea?\"]",
                     "<b><u>angular momentum</u></b> (any similar description is a comment, not a directive)"):
            with self.subTest(fine):
                self.assertEqual(add.answer_problems(fine), [])

    def test_answer_length(self):
        self.assertFlags("<b><u>angular momentum</u></b> [" + "; ".join(["or <b><u>L</u></b>"] * 30) + "]",
                         "at most 400")
        quote = "<b><u>I know what I have to do but I don't know if I have the strength</u></b>"
        self.assertFlags(quote, "more than 30 characters")
        self.assertEqual(add.answer_problems(quote + " [or <b><u>the strength to do it</u></b>]"), [])
        self.assertEqual(add.answer_problems("I know what I have to do but I don't know if I have the "
                                             "<b><u>strength</u></b>"), [])

    def test_a_latin_alphabet_answer(self):
        self.assertFlags("<b><u>元婴</u></b>", "Latin alphabet")
        self.assertEqual(add.answer_problems("<b><u>元婴</u></b> [or <b><u>Nascent Soul</u></b>]"), [])

    def test_the_answer_checker_reads_the_answerline_as_written(self):
        # "Among Us" is a typo away from "Amogus", so the checker accepts it and the prompt never happens.
        self.assertFlags("<b><u>Amogus</u></b> [prompt on <u>Among Us</u>]", "does not prompt on 'among us'")


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

    def test_prompted_words_are_reported_separately(self):
        # The answerline only prompts on "momentum": not an accepted answer, but still a leak.
        leaky = record(question=question("Unlike linear momentum, it depends on the choice of origin."))
        self.assertIsNone(add.leaked_phrase(leaky))
        self.assertEqual(add.leaked_phrase(leaky, "prompt"), "momentum")
        self.assertIsNone(add.leaked_phrase(record(), "prompt"))
        self.assertEqual(add.leak_problems(leaky), ["the question contains 'momentum', which the answerline prompts on"])

    def test_a_rejected_near_miss_is_not_a_leak(self):
        near_miss = record(question="Its operators said official releases made it pointless for the average reader.",
                           answer="<b><u>Reaper</u></b> Scans")
        self.assertEqual(add.leaked_phrase(near_miss), "reader")  # typo tolerance: one letter from "Reaper"
        near_miss["answer"] += " [do not accept “reader”]"
        self.assertIsNone(add.leaked_phrase(near_miss))

    def test_repeated_answers_within_the_file_and_in_other_files(self):
        numbered = [(1, record()), (3, record(question=question(EXTRA))), (4, record(answer="<u>torque</u>"))]
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
        path = self.write("mine.jsonl", [record(), record(question=question(EXTRA), answer=OTHER_ANSWER)])
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
        first, second = record(), record(question=question(EXTRA), answer=OTHER_ANSWER)
        path = self.write("mine.jsonl", [first, second])
        add.main(["--db", self.db, path])
        conn = connect(self.db)
        self.assertEqual(conn.execute("SELECT good_votes, bad_votes FROM tossups").fetchall(), [(0, 0), (0, 0)])
        conn.execute("UPDATE tossups SET good_votes = good_votes + 3, bad_votes = bad_votes + 1 WHERE number = 1")
        conn.commit()
        conn.close()
        # The file changes: question 1 stays, question 2 is replaced by a new one.
        another = question("A gyroscope resists tipping over because of the large amount of it stored in its rotor.")
        path = self.write("mine.jsonl", [first, record(question=another, answer="<b><u>precession</u></b>")])
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

    def test_a_leaked_answer_is_an_error_with_or_without_check(self):
        path = self.write("leaky.jsonl", [record(answer="<b><u>torque</u></b>")])
        records, errors, warnings = add.load_file(path)
        self.assertEqual((records, warnings), ([], []))
        self.assertEqual(errors, [f"{path}:1: the question gives away its own answer: 'torques'"])
        self.assertEqual(add.main(["--check", path]), 1)
        self.assertEqual(add.main(["--db", self.db, path]), 1)
        self.assertEqual(connect_readonly(self.db).execute("SELECT COUNT(*) FROM tossups").fetchone(), (0,))

    def test_one_run_reports_a_leak_alongside_other_problems(self):
        _, errors, _ = add.load_file(self.write("two.jsonl", [record(answer="<b><u>torque</u></b>", difficulty=0)]))
        self.assertEqual(len(errors), 2)

    def test_repeated_answer_is_only_a_warning(self):
        path = self.write("repeat.jsonl", [record(), record(question=question(EXTRA))])
        records, errors, warnings = add.load_file(path)
        self.assertEqual((len(records), errors), (2, []))
        self.assertEqual(warnings, [f"{path}:2: warning: same answer as line 1"])

    def test_check_writes_nothing(self):
        path = self.write("ok.jsonl", [record()])
        self.assertEqual(add.main(["--check", "--db", self.db, path]), 0)
        self.assertFalse(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
