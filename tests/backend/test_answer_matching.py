"""The building blocks of the local answer checker: folding text, comparing words, Phrase."""
import unittest

from trivia_oracle_backend.local.matching import (
    Phrase, allowed_errors, clean_tokens, edit_distance, fold_char, same_stem, strings_match, words_match,
)


def fold(text):
    return "".join(fold_char(c) for c in text)


class FoldTest(unittest.TestCase):
    def test_letters_are_lowercased_and_stripped_of_accents(self):
        self.assertEqual(fold("Ångström"), "angstrom")
        self.assertEqual(fold("ÉCOLE"), "ecole")
        self.assertEqual(fold("Straße Øl Æther"), "strasse ol aether")

    def test_apostrophes_join_and_other_punctuation_separates(self):
        self.assertEqual(fold("Meier's"), "meiers")
        self.assertEqual(fold("don’t"), "dont")
        self.assertEqual(fold("Jean-Paul"), "jean paul")
        self.assertEqual(fold("a.b,c"), "a b c")

    def test_symbols_that_change_an_answer_are_spelled_out(self):
        self.assertEqual(fold("C++").split(), ["c", "plus", "plus"])
        self.assertEqual(fold("C#").split(), ["c", "sharp"])
        self.assertEqual(fold("Q&A").split(), ["q", "and", "a"])
        self.assertEqual(fold("100%").split(), ["100", "percent"])

    def test_invisible_format_characters_vanish(self):
        self.assertEqual(fold("a​b­c﻿"), "abc")

    def test_non_latin_letters_survive(self):
        self.assertEqual(fold("Ελλάδα"), "ελλαδα")
        self.assertEqual(fold("東京"), "東京")


class CleanTokensTest(unittest.TestCase):
    def words(self, *tokens):
        return [(t, False) for t in tokens]

    def texts(self, *tokens):
        return [t for t, _ in clean_tokens(self.words(*tokens))]

    def test_the_goes_everywhere_but_a_and_an_only_at_the_start(self):
        self.assertEqual(self.texts("the", "cat", "in", "the", "hat"), ["cat", "in", "hat"])
        self.assertEqual(self.texts("a", "tale"), ["tale"])
        self.assertEqual(self.texts("vitamin", "a"), ["vitamin", "a"])

    def test_a_lone_article_stays(self):
        self.assertEqual(self.texts("the"), ["the"])
        self.assertEqual(self.texts("a"), ["a"])
        self.assertEqual(self.texts("an"), ["an"])

    def test_roman_numerals_become_digits(self):
        self.assertEqual(self.texts("henry", "viii"), ["henry", "8"])
        self.assertEqual(self.texts("louis", "xiv"), ["louis", "14"])
        self.assertEqual(self.texts("world", "war", "i"), ["world", "war", "1"])

    def test_words_that_only_look_roman_are_left_alone(self):
        self.assertEqual(self.texts("mix", "civil", "did", "vivid", "dim", "mild"), ["mix", "civil", "did", "vivid", "dim", "mild"])

    def test_flags_travel_with_their_words(self):
        self.assertEqual(clean_tokens([("the", True), ("hague", True)]), [("hague", True)])


class EditDistanceTest(unittest.TestCase):
    def test_distances(self):
        cases = [("kitten", "sitting", 3), ("abc", "abc", 0), ("", "abc", 3), ("abc", "", 3), ("ab", "ba", 1), ("abcd", "acbd", 1), ("abc", "xyz", 3)]
        for left, right, expected in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(edit_distance(left, right, 10), expected)

    def test_beyond_the_limit_is_limit_plus_one(self):
        self.assertEqual(edit_distance("abcdef", "uvwxyz", 2), 3)
        self.assertEqual(edit_distance("a", "abcdefgh", 2), 3)

    def test_symmetric(self):
        for left, right in [("dostoevsky", "dostoevksy"), ("nietzsche", "nietzche"), ("abc", "cab")]:
            self.assertEqual(edit_distance(left, right, 5), edit_distance(right, left, 5))


class AllowedErrorsTest(unittest.TestCase):
    def test_short_words_get_no_typos(self):
        self.assertEqual([allowed_errors(n) for n in range(0, 6)], [0] * 6)

    def test_longer_words_get_more(self):
        self.assertEqual([allowed_errors(n) for n in (5, 6, 12, 14, 15, 20, 21, 40)], [0, 1, 1, 1, 2, 2, 3, 3])


class WordsMatchTest(unittest.TestCase):
    def test_typos_and_their_limits(self):
        self.assertTrue(words_match("sartre", "sarte"))
        self.assertTrue(words_match("kepler", "keplre"))
        self.assertFalse(words_match("kant", "kent"))
        self.assertFalse(words_match("hegel", "hegal"))
        self.assertFalse(words_match("sartre", "sartor" + "xx"))

    def test_the_first_letter_must_agree(self):
        self.assertFalse(words_match("arches", "marches"))
        self.assertFalse(words_match("iceland", "xceland"))

    def test_numbers_are_exact(self):
        self.assertFalse(words_match("1812", "1813"))
        self.assertFalse(words_match("mp3", "mp4"))
        self.assertTrue(words_match("1812", "1812"))

    def test_typos_can_be_switched_off(self):
        self.assertFalse(words_match("constantine", "constantin", typos=False))
        self.assertTrue(words_match("constantine", "constantine", typos=False))

    def test_word_forms_share_a_stem(self):
        self.assertTrue(same_stem("italy", "italian"))
        self.assertTrue(same_stem("donating", "donate"))
        self.assertFalse(same_stem("cat", "cats"))          # too short to judge
        self.assertFalse(same_stem("chair", "chemistry"))
        self.assertFalse(same_stem("1234", "1235"))
        self.assertTrue(words_match("italy", "italian", forms=True))
        self.assertFalse(words_match("italy", "italian"))


class StringsMatchTest(unittest.TestCase):
    def test_numbers_must_be_identical(self):
        self.assertFalse(strings_match("henry7", "henry8"))
        self.assertTrue(strings_match("henry8", "henry8"))

    def test_empty_never_matches(self):
        self.assertFalse(strings_match("", ""))
        self.assertFalse(strings_match("a", ""))


class PhraseTest(unittest.TestCase):
    def phrase(self, markup_pairs):
        return Phrase.from_styled(markup_pairs)

    def test_plain_text(self):
        p = Phrase.from_text("The Sid Meier's  Civilization!")
        self.assertEqual(p.tokens, ("sid", "meiers", "civilization"))
        self.assertEqual((p.required, p.core), ((), ()))
        self.assertEqual(p.literal, ("the", "sid", "meiers", "civilization"))

    def test_underlined_words_are_required(self):
        pairs = [(c, False) for c in "Kingdom of "] + [(c, True) for c in "Spain"]
        p = Phrase.from_styled(pairs)
        self.assertEqual(p.tokens, ("kingdom", "of", "spain"))
        self.assertEqual(p.required, ("spain",))
        self.assertEqual(p.core, ("spain",))

    def test_a_partly_underlined_word_is_required_whole_but_core_is_the_underlined_part(self):
        pairs = [(c, True) for c in "ship"] + [("s", False)]
        p = Phrase.from_styled(pairs)
        self.assertEqual(p.tokens, ("ships",))
        self.assertEqual(p.required, ("ships",))
        self.assertEqual(p.core, ("ship",))

    def test_separate_underlined_runs_are_separate_chunks(self):
        pairs = [(c, True) for c in "Constantine"] + [(c, False) for c in " the "] + [(c, True) for c in "Great"]
        p = Phrase.from_styled(pairs)
        self.assertEqual(p.core, ("constantine", "great"))

    def test_empty_and_symbol_only_text_is_falsy(self):
        for text in ("", "   ", "...", "?!", "🙂"):
            with self.subTest(text=text):
                self.assertFalse(Phrase.from_text(text))

    def test_a_leading_minus_is_a_word(self):
        self.assertEqual(Phrase.from_text("-1").tokens, ("minus", "1"))
        self.assertEqual(Phrase.from_text("well-1").tokens, ("well", "1"))

    def test_accepts_is_symmetric_for_plain_phrases(self):
        a, b = Phrase.from_text("Sid Meier's Civilization"), Phrase.from_text("sid meiers civilization")
        self.assertTrue(a.accepts(b) and b.accepts(a))

    def test_an_empty_phrase_accepts_nothing_and_is_accepted_by_nothing(self):
        empty, full = Phrase.from_text(""), Phrase.from_text("Grant")
        self.assertFalse(empty.accepts(full))
        self.assertFalse(full.accepts(empty))
        self.assertFalse(empty.accepts(empty))

    def test_is_exactly_is_word_for_word_but_ignores_case_and_spacing(self):
        reject = Phrase.from_text("The Invisible Man")
        self.assertTrue(reject.is_exactly(Phrase.from_text("the  invisible-man!")))
        self.assertFalse(reject.is_exactly(Phrase.from_text("Invisible Man")))
        self.assertFalse(Phrase.from_text("").is_exactly(Phrase.from_text("")))


if __name__ == "__main__":
    unittest.main()
