"""Clue splitting must break on sentence ends, not on the periods inside abbreviations."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

from trivia_oracle_bot.game.sentences import split_sentences


class SplitSentencesTest(unittest.TestCase):
    def test_splits_ordinary_sentences(self):
        self.assertEqual(
            split_sentences("This river is long. It flows north! Name it? For ten points."),
            ["This river is long.", "It flows north!", "Name it?", "For ten points."],
        )

    def test_keeps_a_single_sentence_whole(self):
        self.assertEqual(split_sentences("Name this river."), ["Name this river."])

    def test_ignores_blank_input(self):
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences("   "), [])

    def test_does_not_split_after_st(self):
        # The case from the bug report: "St." / "Louis" was sent as two clues.
        text = "For 10 points, name this river which joins with the Mississippi River near St. Louis."
        self.assertEqual(split_sentences(text), [text])

    def test_does_not_split_after_titles_and_place_abbreviations(self):
        for text in (
            "Name this man, called Dr. Livingstone by Stanley.",
            "Mr. Darcy proposes to Elizabeth Bennet.",
            "Mrs. Dalloway plans a party.",
            "Ms. Havisham was jilted at the altar.",
            "This ship sailed to Mt. Ararat.",
            "He served as Gen. Grant's aide.",
            "Sen. Joseph McCarthy led the hearings.",
            "This city near Ft. Worth hosts a rodeo.",
            "Prof. Moriarty is Holmes's nemesis.",
            "This is a saint from Sts. Peter and Paul.",
            "Rev. Dimmesdale hides a scarlet mark.",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])

    def test_does_not_split_inside_dotted_acronyms(self):
        for text in (
            "This U.S. president signed the act.",
            "The U.S. Army fought in this war.",
            "The U.K. left the European Union.",
            "This U.S.S.R. leader was born in Georgia.",
            "Name this Ph.D. thesis by Einstein.",
            "It happened at 5 p.m. on Tuesday.",
            "This U.S. Steel founder was Scottish-born.",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])

    def test_does_not_split_after_initials(self):
        text = "This author of The Hobbit is J. R. R. Tolkien."
        self.assertEqual(split_sentences(text), [text])
        text = "T. S. Eliot wrote The Waste Land."
        self.assertEqual(split_sentences(text), [text])

    def test_does_not_split_after_other_common_abbreviations(self):
        for text in (
            "Name this painting, Fig. 3 in the catalogue.",
            "Lyndon B. Johnson signed the act.",
            "This is No. 5 on the charts.",
            "Deere & Co. makes tractors.",
            "Team A vs. team B played on Sunday.",
            "Martin Luther King Jr. gave a famous speech.",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])

    def test_still_splits_after_an_abbreviation_that_ends_a_sentence(self):
        self.assertEqual(
            split_sentences("This river flows through the U.S. It joins the Mississippi."),
            ["This river flows through the U.S.", "It joins the Mississippi."],
        )
        self.assertEqual(
            split_sentences("He collected stamps, coins, etc. The collection is now in a museum."),
            ["He collected stamps, coins, etc.", "The collection is now in a museum."],
        )

    def test_splits_normally_around_abbreviations_in_a_longer_clue(self):
        text = (
            "This river joins the Mississippi near St. Louis. "
            "It is longer than any other river in the U.S. "
            "Its explorers Lewis and Clark set out from Mr. Jefferson's purchase. "
            "For 10 points, name this Missouri River."
        )
        self.assertEqual(split_sentences(text), [
            "This river joins the Mississippi near St. Louis.",
            "It is longer than any other river in the U.S.",
            "Its explorers Lewis and Clark set out from Mr. Jefferson's purchase.",
            "For 10 points, name this Missouri River.",
        ])

    def test_does_not_split_decimals_or_ellipses_mid_sentence(self):
        text = "It measures 3.5 metres and then... fades away."
        self.assertEqual(split_sentences(text), [text])

    def test_a_period_before_a_lowercase_word_is_not_a_boundary(self):
        text = "The Dr. who wrote this played in the Prof. lounge."
        self.assertEqual(split_sentences(text), [text])

    def test_splits_after_a_sentence_end_inside_quotes_or_brackets(self):
        for text, expected in (
            ('He called it "the Rock." Name this island.', ['He called it "the Rock."', "Name this island."]),
            ("He called it “the Rock.” Name this island.", ["He called it “the Rock.”", "Name this island."]),
            ("He called it ‘the Rock.’ Name this island.", ["He called it ‘the Rock.’", "Name this island."]),
            ("It is a gas (like neon.) Name it.", ["It is a gas (like neon.)", "Name it."]),
            ('He asked "why?" Then he left.', ['He asked "why?"', "Then he left."]),
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), expected)

    def test_quotes_and_brackets_mid_sentence_are_not_boundaries(self):
        for text in (
            'He called it "the Rock" and left.',
            "The students' union met (in 1968) at noon.",
            'This poem, "Break of Day." is short.',
            "This happened in the U.S.) and stopped.",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])

    def test_splits_after_a_single_capital_letter_that_ends_a_sentence(self):
        for text, expected in (
            ("It is vitamin C. This vitamin prevents scurvy.", ["It is vitamin C.", "This vitamin prevents scurvy."]),
            ("He fought in World War I. Name him.", ["He fought in World War I.", "Name him."]),
            ("They adopted Plan B. It failed.", ["They adopted Plan B.", "It failed."]),
        ):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), expected)

    def test_initials_before_a_sentence_starter_word_stay_together(self):
        for text in ("A. A. Milne wrote Winnie-the-Pooh.", "The architect I. M. Pei designed it.",
                     "It was built c. 1850 by masons."):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])

    def test_does_not_split_after_month_abbreviations(self):
        for text in ("It opened on Sept. 11 in Paris.", "It was founded in Jan. 1901 by him.",
                     "The treaty was signed on Nov. 3, 1903."):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])
        self.assertEqual(
            split_sentences("It was signed in Dec. The war ended."),
            ["It was signed in Dec.", "The war ended."],
        )

    def test_a_question_or_exclamation_mark_before_a_lowercase_word_is_not_a_boundary(self):
        for text in ("The musical Oklahoma! premiered in 1943.",
                     "This author of Who's Afraid of Virginia Woolf? was born in 1928."):
            with self.subTest(text=text):
                self.assertEqual(split_sentences(text), [text])


class StartRoundSentencesTest(unittest.TestCase):
    """The real round must use the same splitting."""

    def test_round_clues_keep_st_louis_together(self):
        from trivia_oracle_bot.game import round as rnd

        question = ("For 10 points, name this river which joins with the Mississippi River near St. Louis. "
                    "It is longer than any other river in the U.S. Name it.")
        tossup = SimpleNamespace(question_sanitized=question, answer_sanitized="Missouri", answer="Missouri")
        fetch = mock.AsyncMock(return_value=tossup)
        try:
            with mock.patch.object(rnd, "_fetch_tossup", fetch), \
                 mock.patch.object(rnd.threading, "Thread"):
                rnd.start_round(mock.Mock(), "", {})
            self.assertEqual(rnd.current_round["sentences"], [
                "For 10 points, name this river which joins with the Mississippi River near St. Louis.",
                "It is longer than any other river in the U.S.",
                "Name it.",
            ])
            self.assertEqual(rnd.current_round["hourglasses"], 3)
        finally:
            if rnd.round_lock.locked():
                rnd.round_lock.release()
            rnd.current_round["active"] = False


if __name__ == "__main__":
    unittest.main()
