"""
The local answer checker end to end: answerline HTML and a typed answer in, verdict out.

Every case is (answerline, what the player typed, expected directive). The answerlines are
real ones in the shape qbreader's editors write them.
"""
import asyncio
import socket
import unittest
from unittest import mock

from trivia_oracle_backend.local import LocalAnswerJudge, judge

A, R, P = "accept", "reject", "prompt"

CONSTANTINE = (
    "<b><u>Constantine</u></b> the <b><u>Great</u></b> [or <b><u>Constantine I</u></b>; "
    "prompt on <u>Constantine</u>; do not accept or prompt on “Constantine II”]"
)
MOMENTUM = (
    "<b><u>angular momentum</u></b> [accept <b><u>rotational momentum</u></b> or spin "
    "<b><u>angular momentum</u></b> prompt on <u>L</u>, do not accept “momentum” or “linear momentum”]"
)
GRANT = "Ulysses S. <b><u> Grant</u></b> (or Ulysses Simpson <b><u> Grant</u></b> ; or Hiram Ulysses <b><u> Grant</u></b> )"
ADSORPTION = "<b><u>adsorption</u></b> [do not accept or prompt on “absorption”]"
HAMM = "<b><u>Hamm</u></b> (“ham” or hahm) [accept Paul Elbert <b><u>Hamm</u></b> or Mia <b><u>Hamm</u> </b>or Mariel Margaret <b><u>Hamm</u></b>-Garciaparra]"
SHIPS = "<b><u>ship</u></b>s [or <b><u>boat</u></b>s, accept specific sorts of ships]"
NAPOLEONIC = (
    "<b><u>Napoleonic</u></b> Wars [or <b><u>French Revolutionary</u></b> Wars; prompt on <u>Anglo-French</u> War; "
    'anti-prompt on the War of <u>1812</u> by asking "what broader set of wars was that part of?"]'
)
INVISIBLE_MAN = "<i><b><u>Invisible Man</u></b></i> [do NOT accept or prompt on “The Invisible Man”]"
TEMPEST = "<i>A</i> <i><b><u>Tempest</u></b></i> [or <i>Une</i> <i><b><u>Tempête</u></b></i>; reject “The Tempest”]"
C_LANGUAGE = "<b><u>C</u></b> [reject “C++” or “C#”]"
C_PLUS_PLUS = "<b><u>C++</u></b> (“C-plus-plus”) [reject “C” or “C sharp” or “Objective-C”]"
INDIRA = "<b><u>I</u></b>ndira Priyadarshini <b><u>Gandhi</u></b> [or <b><u>I</u></b>ndira Priyadarshini <b><u>Nehru</u></b>; prompt on <u>Gandhi</u>]"
PLAIN = "Sid Meier's Civilization"
FEYNMAN = "Richard <b><u>Feynman</u></b> (“FINE-mun”) [or Richard Phillips <b><u>Feynman</u></b>; accept <b><u>Feynman</u></b> diagrams]"
ITALIAN = "<b><u>Italian</u></b> (accept word forms like <b><u>Italy</u></b>; accept lingua <b><u>italiana</u></b>)"
EITHER = "<b><u>Philippe II</u></b>, <b><u>Duke of Orléans</u></b> [accept either underlined portion]"
NEGATIVE_ONE = '<b><u>-1</u></b> ("negative one") [accept answers like <b><u>minus 1</u></b>; do not accept or prompt on "1"]'
TANG = "<b><u>Tang</u></b> Dynasty"
KING_LEAR = "<i><b><u>King Lear</u></b></i>"
HENRY = "Henry <b><u>VIII</u></b>"
MOON = "the <b><u>moon</u></b> [accept <b><u>moon</u></b>cakes]"
NATIONAL_ANTHEMS = "<b><u> national anthem</u></b> s (or <b><u> national song</u></b> s; prompt on <u> anthem</u> , <u> song</u> , or <u> poem</u> )"


class Cases(unittest.TestCase):
    def check(self, cases):
        for answerline, given, expected in cases:
            with self.subTest(answerline=answerline[:60], given=given):
                self.assertEqual(judge(answerline, given).directive, expected)


class UnderlinedPartTest(Cases):
    def test_the_whole_answer_or_just_the_underlined_part_is_accepted(self):
        self.check([
            (GRANT, "Ulysses S. Grant", A),
            (GRANT, "Grant", A),
            (GRANT, "ulysses grant", A),
            (GRANT, "Ulysses Simpson Grant", A),
            (KING_LEAR, "King Lear", A),
        ])

    def test_every_underlined_word_is_needed(self):
        self.check([
            (CONSTANTINE, "Constantine the Great", A),
            (CONSTANTINE, "constantine great", A),
            (CONSTANTINE, "Great", R),
            (MOMENTUM, "angular momentum", A),
            (MOMENTUM, "angular", R),
        ])

    def test_foreign_words_spoil_a_partial_answer(self):
        self.check([
            (GRANT, "Grant Wood", R),
            (GRANT, "President Grant", R),
            (GRANT, "Ulysses", R),
            (GRANT, "Ulysses Grant Sherman", R),
        ])

    def test_an_answerline_without_underlining_needs_all_of_it(self):
        self.check([
            (PLAIN, "Sid Meier's Civilization", A),
            (PLAIN, "sid meiers civilization", A),
            (PLAIN, "Civilization", R),
            (PLAIN, "Sid Meier", R),
        ])

    def test_an_underline_that_stops_mid_word_still_wants_the_whole_word(self):
        self.check([
            (INDIRA, "Indira Gandhi", A),
            (INDIRA, "Indira Priyadarshini Gandhi", A),
            (INDIRA, "Indira Nehru", A),
            (INDIRA, "Gandhi", P),
            (INDIRA, "Indira", R),
            (INDIRA, "Rajiv Gandhi", R),
        ])

    def test_the_underlined_stem_of_a_word_is_enough(self):
        self.check([
            (SHIPS, "ship", A),
            (SHIPS, "ships", A),
            (MOON, "moon", A),
            (MOON, "mooncakes", A),
            (NATIONAL_ANTHEMS, "national anthem", A),
            (NATIONAL_ANTHEMS, "national anthems", A),
        ])


class AlternativesTest(Cases):
    def test_bracketed_alternatives_are_accepted(self):
        self.check([
            (CONSTANTINE, "Constantine I", A),
            (MOMENTUM, "rotational momentum", A),
            (MOMENTUM, "spin angular momentum", A),
            (SHIPS, "boat", A),
            (SHIPS, "boats", A),
            (NAPOLEONIC, "French Revolutionary Wars", A),
            (HAMM, "Paul Hamm", A),
            (HAMM, "Mia Hamm", A),
        ])

    def test_alternatives_are_found_in_round_brackets_too(self):
        self.check([(GRANT, "Hiram Ulysses Grant", A), (NATIONAL_ANTHEMS, "national song", A)])

    def test_pronunciation_guides_are_not_answers(self):
        self.check([(HAMM, "ham", R), (HAMM, "hahm", R), (FEYNMAN, "fine mun", R), (FEYNMAN, "Feynman", A)])

    def test_alternatives_with_extra_words(self):
        self.check([(FEYNMAN, "Feynman diagrams", A), (FEYNMAN, "Richard Phillips Feynman", A)])

    def test_descriptive_instructions_cannot_be_typed_as_answers(self):
        self.check([(SHIPS, "sorts", R), (SHIPS, "specific", R), (SHIPS, "any ship", R)])


class PromptTest(Cases):
    def test_prompt_on_asks_for_more(self):
        self.check([(CONSTANTINE, "Constantine", P), (MOMENTUM, "L", P), (MOMENTUM, "l", P), (NAPOLEONIC, "Anglo-French War", P)])

    def test_prompt_uses_the_answerlines_own_wording_when_it_has_one(self):
        verdict = judge(NAPOLEONIC, "War of 1812")
        self.assertEqual(verdict.directive, P)
        self.assertEqual(verdict.directed_prompt, "what broader set of wars was that part of?")

    def test_a_plain_prompt_has_no_message(self):
        self.assertIsNone(judge(CONSTANTINE, "Constantine").directed_prompt)

    def test_an_accepted_answer_wins_over_a_prompt_that_also_fits(self):
        self.assertEqual(judge(CONSTANTINE, "Constantine the Great").directive, A)

    def test_prompt_lists_are_split_on_commas_and_or(self):
        self.check([(NATIONAL_ANTHEMS, "anthem", P), (NATIONAL_ANTHEMS, "song", P), (NATIONAL_ANTHEMS, "poem", P)])


class RejectTest(Cases):
    def test_do_not_accept_beats_everything(self):
        self.check([
            (MOMENTUM, "momentum", R),
            (MOMENTUM, "linear momentum", R),
            (CONSTANTINE, "Constantine II", R),
            (ADSORPTION, "absorption", R),
        ])

    def test_a_typo_of_the_answer_is_not_caught_by_a_rejection_of_a_neighbour(self):
        self.check([(ADSORPTION, "adsorption", A), (ADSORPTION, "adsorbtion", A)])

    def test_rejecting_a_title_with_an_article_only_rejects_that_form(self):
        self.check([
            (INVISIBLE_MAN, "Invisible Man", A),
            (INVISIBLE_MAN, "The Invisible Man", R),
            (TEMPEST, "Tempest", A),
            (TEMPEST, "The Tempest", R),
        ])

    def test_symbols_keep_similar_answers_apart(self):
        self.check([
            (C_LANGUAGE, "C", A),
            (C_LANGUAGE, "C++", R),
            (C_LANGUAGE, "C#", R),
            (C_PLUS_PLUS, "C++", A),
            (C_PLUS_PLUS, "C plus plus", A),
            (C_PLUS_PLUS, "C", R),
            (C_PLUS_PLUS, "C sharp", R),
        ])

    def test_an_answer_that_is_also_listed_as_rejected_stays_accepted(self):
        # "do not accept House Mouse, Senate Mouse": the comma must not reject the answer itself.
        answerline = "house <b><u>mouse</u></b> [or laboratory <b><u>mouse</u></b>; do not accept <i>House Mouse, Senate Mouse</i>]"
        self.check([(answerline, "house mouse", A), (answerline, "laboratory mouse", A)])


class ForgivenessTest(Cases):
    def test_case_accents_punctuation_and_articles_do_not_matter(self):
        self.check([
            (GRANT, "GRANT", A),
            ("<b><u>Joséphine</u></b>", "josephine", A),
            ("<b><u>Bahá’í</u></b>", "bahai", A),
            ("<b><u>The Hague</u></b>", "Hague", A),
            ("<b><u>Hague</u></b>", "the hague", A),
            ("<b><u>Jean-Paul Sartre</u></b>", "jean paul sartre", A),
            ("<b><u>Jean-Paul Sartre</u></b>", "Jean Paul   Sartre!!", A),
            ("<b><u>Norway</u></b>", "  norway  ", A),
            ("<b><u>Kaiser Søze</u></b>", "kaiser soze", A),
            ("<b><u>Ångström</u></b>", "angstrom", A),
            ("<b><u>Straße</u></b>", "strasse", A),
        ])

    def test_html_entities_in_the_answerline_are_read(self):
        self.check([("<b><u>Pride &amp; Prejudice</u></b>", "Pride and Prejudice", A), ("<b><u>Ben&nbsp;Jonson</u></b>", "Ben Jonson", A)])

    def test_words_typed_together_or_apart(self):
        self.check([("<b><u>New York</u></b>", "newyork", A), ("<b><u>Newyork</u></b>", "new york", A)])

    def test_typos_in_longer_words_are_forgiven(self):
        self.check([
            (CONSTANTINE, "Constantin the Great", A),
            (CONSTANTINE, "Constantinne the Great", A),
            (MOMENTUM, "anglar momentum", A),
            (MOMENTUM, "angular momentun", A),
            ("<b><u>Nietzsche</u></b>", "Nietzche", A),
            ("<b><u>Mississippi</u></b>", "Missisippi", A),
            ("<b><u>Mississippi</u></b>", "Missisipi", R),  # two edits in an 11-letter word
        ])

    def test_two_edits_do_not_turn_one_word_into_another(self):
        """Neighbours that differ by two letters are different answers (qbreader rejects these too)."""
        self.check([
            ("<b><u>reflection</u></b>", "refraction", R),
            ("<b><u>reflection</u></b>", "reflection", A),
            ("<b><u>Conservation</u></b> of Energy", "conversation", R),
            ("<b><u>conservation</u></b>", "conversation", R),
            ("<b><u>conservation</u></b>", "conservaton", A),
            ("<b><u>Catalan</u></b>", "Catalonia", R),
            ("<b><u>retarded</u></b>", "regarded", A),  # one edit, and qbreader accepts it too
        ])

    def test_partial_names_follow_the_underlining(self):
        self.check([
            ("<b><u>Johann Strauss</u></b> II", "Strauss", R),
            ("Johann <u>Strauss</u> II", "Strauss", A),
            ("<b><u>Wolfgang Amadeus Mozart</u></b>", "Mozart", R),
            ("Wolfgang Amadeus <u>Mozart</u>", "Mozart", A),
        ])

    def test_swapped_neighbouring_letters_count_as_one_typo(self):
        self.check([("<b><u>Kepler</u></b>", "Keplre", A), ("<b><u>Dostoevsky</u></b>", "Dostoevksy", A)])

    def test_short_words_must_be_exact(self):
        self.check([
            (TANG, "Tang Dynasty", A),
            (TANG, "Han Dynasty", R),
            ("<b><u>Kant</u></b>", "Kent", R),
            ("<b><u>Mali</u></b>", "Mail", R),
            ("<b><u>Bach</u></b>", "Bash", R),
        ])

    def test_a_typo_cannot_change_the_first_letter(self):
        self.check([("Triumphal <b><u>Arches</u></b>", "marches", R)])

    def test_typos_are_judged_word_by_word(self):
        self.check([("<b><u>Han</u></b> Dynasty", "Tang Dynasty", R), ("<b><u>Song</u></b> Dynasty", "Ming Dynasty", R)])


class NumbersTest(Cases):
    def test_numbers_must_match_exactly(self):
        self.check([
            (HENRY, "Henry VIII", A),
            (HENRY, "Henry 8", A),
            (HENRY, "Henry 7", R),
            (HENRY, "Henry VII", R),
            ("<b><u>1812</u></b>", "1813", R),
            ("<b><u>1984</u></b>", "1984", A),
        ])

    def test_roman_numerals_and_digits_are_interchangeable(self):
        self.check([
            (CONSTANTINE, "Constantine 1", A),
            ("<b><u>Louis XIV</u></b>", "louis 14", A),
            ("<b><u>Louis 14</u></b>", "Louis XIV", A),
            ("<b><u>Louis XIV</u></b>", "louis xvi", R),
            ("<b><u>Elizabeth II</u></b>", "Elizabeth 2", A),
            ("<b><u>Elizabeth II</u></b>", "Elizabeth I", R),
        ])

    def test_negative_numbers_are_not_positive_ones(self):
        self.check([(NEGATIVE_ONE, "-1", A), (NEGATIVE_ONE, "negative one", R), (NEGATIVE_ONE, "1", R)])


class SpecialDirectivesTest(Cases):
    def test_word_forms_are_accepted_when_the_answerline_asks(self):
        self.check([
            (ITALIAN, "Italian", A),
            (ITALIAN, "Italy", A),
            (ITALIAN, "italiana", A),
            ("<b><u>donate</u></b> [accept word forms]", "donating", A),
            ("<b><u>donate</u></b>", "donating", R),
        ])

    def test_either_underlined_portion(self):
        self.check([
            (EITHER, "Philippe II", A),
            (EITHER, "Duke of Orléans", A),
            (EITHER, "Philippe II Duke of Orléans", A),
            (EITHER, "Duke", R),
            (EITHER, "Philippe", R),
        ])

    def test_timing_conditions_are_ignored(self):
        self.check([
            ("<b><u>Hermes</u></b> [accept <b><u>Mercury</u></b> until “Iliad” is read]", "Mercury", A),
            ("<b><u>Andromeda</u></b> [prompt on <u>Local Group</u> before the first “galaxy”]", "Local Group", P),
            ("<b><u>charity</u></b> [accept <b><u>zakat</u></b> until read]", "zakat", A),
        ])

    def test_do_not_prompt_on_rejects_and_also_accept_accepts(self):
        answerline = "<b><u>chlorine</u></b> [also accept <b><u>Cl</u></b>; do not prompt on “hydrochloric acid”]"
        self.check([(answerline, "Cl", A), (answerline, "hydrochloric acid", R)])

    def test_bare_bracket_text_is_an_alternative(self):
        self.check([("<b><u>Kyiv</u></b> [<b><u>Kiev</u></b>]", "Kiev", A)])

    def test_directive_words_inside_quotes_are_just_text(self):
        answerline = '<b><u>Stop</u></b> [accept "please accept or reject"]'
        self.check([(answerline, "please accept or reject", A), (answerline, "reject", R)])

    def test_or_inside_an_item_after_a_comma(self):
        self.check([("<b><u>ocean waves</u></b> [accept <b><u>wind waves</u></b>, or <b><u>gravity</u></b> <b><u>waves</u></b>]", "gravity waves", A)])


class HostileInputTest(Cases):
    def test_empty_and_blank_answers_are_rejected(self):
        for given in ("", " ", "\n\t", "...", "?!", "🙂"):
            with self.subTest(given=given):
                self.assertEqual(judge(GRANT, given).directive, R)

    def test_an_empty_answerline_accepts_nothing(self):
        for answerline in ("", "   ", "<b></b>", "[accept]", "()"):
            with self.subTest(answerline=answerline):
                self.assertEqual(judge(answerline, "anything").directive, R)
                self.assertEqual(judge(answerline, "").directive, R)

    def test_very_long_answers_are_rejected_quickly(self):
        self.assertEqual(judge(GRANT, "Grant " * 2000).directive, R)
        self.assertEqual(judge(GRANT, "a" * 100000).directive, R)

    def test_a_sentence_containing_the_answer_is_not_the_answer(self):
        self.check([(GRANT, "I think it was Grant", R), (GRANT, "is it Grant?", R)])

    def test_markup_and_control_characters_in_the_answer_are_harmless(self):
        self.check([
            (GRANT, "Grant\x00", A),
            (GRANT, "Gr​ant", A),  # zero-width space, as pasted from some apps
            (GRANT, "Gr­ant", A),  # soft hyphen
            (GRANT, "<script>alert(1)</script>", R),
            (GRANT, "<b>Wood</b>", R),
        ])

    def test_regex_and_sql_lookalikes_are_just_text(self):
        for given in (".*", "(?i)grant", "'; DROP TABLE tossups; --", "\\", "[", "]]]", "((("):
            with self.subTest(given=given):
                self.assertEqual(judge(GRANT, given).directive, R)

    def test_malformed_answerlines_do_not_crash(self):
        for answerline in (
            "<b><u>Grant", "Grant</u></b>", "<<>>", "Grant [accept", "Grant ]accept[", "Grant ((()", "Grant [[[[",
            "Grant [accept “unterminated", 'Grant [prompt on X by asking "', "Grant [;;;,,, or or or]", "&notanentity; Grant",
            "\x00", "Grant [accept " + "or " * 500 + "]",
        ):
            with self.subTest(answerline=answerline):
                self.assertIn(judge(answerline, "Grant").directive, (A, R, P))

    def test_non_latin_scripts_are_compared_as_text(self):
        self.check([("<b><u>Ελλάδα</u></b>", "ελλαδα", A), ("<b><u>東京</u></b>", "東京", A), ("<b><u>東京</u></b>", "京都", R)])

    def test_many_options_in_one_answerline(self):
        options = "; ".join(f"accept <b><u>option{i}</u></b>" for i in range(300))
        answerline = f"<b><u>main</u></b> [{options}]"
        self.assertEqual(judge(answerline, "option299").directive, A)
        self.assertEqual(judge(answerline, "option300").directive, R)


class NoNetworkTest(unittest.TestCase):
    """The local judge must never reach qbreader, and has no fallback that does."""

    def test_judging_needs_no_network(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the local judge opened a network connection")

        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse), \
                mock.patch.object(socket, "create_connection", refuse):
            for given, expected in (("Grant", A), ("Wood", R), ("", R)):
                self.assertEqual(judge(GRANT, given).directive, expected)
            self.assertEqual(asyncio.run(LocalAnswerJudge().check(GRANT, "Grant")).directive, A)

    def test_the_local_judge_does_not_import_the_qbreader_client(self):
        import trivia_oracle_backend.local.answer_judge as module
        import trivia_oracle_backend.local.answerline as answerline_module
        import trivia_oracle_backend.local.matching as matching_module

        for m in (module, answerline_module, matching_module):
            with self.subTest(module=m.__name__):
                self.assertNotIn("qbreader", " ".join(vars(m)).lower())
                self.assertNotIn("aiohttp", vars(m))
                self.assertNotIn("requests", vars(m))


class AsyncWrapperTest(unittest.IsolatedAsyncioTestCase):
    async def test_check_returns_the_wire_fields(self):
        verdict = await LocalAnswerJudge().check(NAPOLEONIC, "war of 1812")
        self.assertEqual((verdict.directive, verdict.directed_prompt), (P, "what broader set of wars was that part of?"))

    async def test_many_checks_at_once_all_get_their_own_answer(self):
        judge_ = LocalAnswerJudge()
        givens = ["Grant", "Wood", "Ulysses Grant", "", "Sherman"] * 40
        verdicts = await asyncio.gather(*(judge_.check(GRANT, g) for g in givens))
        self.assertEqual([v.directive for v in verdicts], [{"Grant": A, "Ulysses Grant": A}.get(g, R) for g in givens])


if __name__ == "__main__":
    unittest.main()
