"""Reading answerline HTML into accepted / prompted / rejected phrases."""
import unittest

from trivia_oracle_backend.local.answerline import parse_answerline


def words(phrases):
    return [" ".join(p.tokens) for p in phrases]


def required(phrases):
    return [" ".join(p.required) for p in phrases]


class MainAnswerTest(unittest.TestCase):
    def test_underlined_text_is_required(self):
        line = parse_answerline("Ulysses S. <b><u>Grant</u></b>")
        self.assertEqual(words(line.accepted), ["ulysses s grant"])
        self.assertEqual(required(line.accepted), ["grant"])

    def test_bold_alone_or_underline_alone_counts(self):
        for markup in ("<b>Grant</b>", "<u>Grant</u>", "<strong>Grant</strong>", "<i><b><u>Grant</u></b></i>"):
            with self.subTest(markup=markup):
                self.assertEqual(required(parse_answerline("Ulysses " + markup).accepted), ["grant"])

    def test_italics_alone_do_not(self):
        self.assertEqual(required(parse_answerline("Ulysses <i>Grant</i>").accepted), [""])

    def test_unbalanced_and_stray_tags_are_tolerated(self):
        self.assertEqual(required(parse_answerline("<b><u>Grant").accepted), ["grant"])
        self.assertEqual(words(parse_answerline("Grant</u></b></u>").accepted), ["grant"])
        self.assertEqual(words(parse_answerline("<<>> Grant <").accepted), ["grant"])

    def test_entities_and_nbsp(self):
        self.assertEqual(words(parse_answerline("Pride&nbsp;&amp;&nbsp;Prejudice").accepted), ["pride and prejudice"])

    def test_no_text_means_nothing_is_accepted(self):
        for markup in ("", "   ", "<b></b>", "[accept]", "()", "[]"):
            with self.subTest(markup=markup):
                self.assertEqual(parse_answerline(markup).accepted, ())


class GroupTest(unittest.TestCase):
    def test_square_brackets_hold_directives(self):
        line = parse_answerline("<u>Grant</u> [or Ulysses <u>Grant</u>; prompt on <u>General</u>; reject “Wood”]")
        self.assertEqual(words(line.accepted), ["grant", "ulysses grant"])
        self.assertEqual(words(p.phrase for p in line.prompts), ["general"])
        self.assertEqual(words(line.rejected), ["wood"])

    def test_round_brackets_are_directives_only_when_they_open_with_one(self):
        self.assertEqual(words(parse_answerline("Grant (or U. S. Grant)").accepted), ["grant", "u s grant"])
        self.assertEqual(words(parse_answerline("Grant (accept Sam)").accepted), ["grant", "sam"])
        self.assertEqual(words(parse_answerline("Grant (also accept Sam)").accepted), ["grant", "sam"])
        self.assertEqual(words(parse_answerline("Grant (rhymes with ant)").accepted), ["grant"])
        self.assertEqual(words(parse_answerline("Grant (“ham” or hahm)").accepted), ["grant"])
        self.assertEqual(words(parse_answerline("Grant (order matters)").accepted), ["grant"])

    def test_text_after_the_brackets_is_not_part_of_the_answer(self):
        line = parse_answerline("Grant [or Sam] (The unnamed poem is “Break of Day”.)")
        self.assertEqual(words(line.accepted), ["grant", "sam"])

    def test_nested_brackets_stay_inside_their_group(self):
        line = parse_answerline("Grant [accept Sam (the general) or [Ulysses]; prompt on Wood]")
        self.assertEqual(words(p.phrase for p in line.prompts), ["wood"])
        self.assertEqual(len(line.accepted), 3)

    def test_an_unclosed_group_runs_to_the_end(self):
        line = parse_answerline("Grant [accept Sam; prompt on Wood")
        self.assertEqual(words(line.accepted), ["grant", "sam"])
        self.assertEqual(words(p.phrase for p in line.prompts), ["wood"])

    def test_a_stray_closer_is_plain_text(self):
        self.assertEqual(words(parse_answerline("Grant] Sam)").accepted), ["grant sam"])

    def test_bare_bracket_text_is_an_alternative(self):
        self.assertEqual(words(parse_answerline("Kyiv [Kiev]").accepted), ["kyiv", "kiev"])


class DirectiveTest(unittest.TestCase):
    def test_directive_words_without_separators(self):
        line = parse_answerline("A [accept B or C prompt on D do not accept E]")
        self.assertEqual(words(line.accepted), ["a", "b", "c"])
        self.assertEqual(words(p.phrase for p in line.prompts), ["d"])
        self.assertEqual(words(line.rejected), ["e"])

    def test_all_the_reject_spellings(self):
        for directive in ("reject", "do not accept", "do not accept or prompt on", "do NOT accept or prompt on",
                          "DO NOT ACCEPT", "don't accept", "do not prompt on", "never accept"):
            with self.subTest(directive=directive):
                line = parse_answerline(f"Grant [{directive} “Wood” or “Oak”]")
                self.assertEqual(words(line.rejected), ["wood", "oak"])
                self.assertEqual(words(line.accepted), ["grant"])

    def test_prompt_spellings(self):
        for directive in ("prompt on", "prompt", "Prompt On", "also prompt on"):
            with self.subTest(directive=directive):
                self.assertEqual(words(p.phrase for p in parse_answerline(f"Grant [{directive} Sam]").prompts), ["sam"])

    def test_a_directive_word_inside_a_longer_word_is_not_a_directive(self):
        line = parse_answerline("Grant [accept Acceptance Speech; or Promptly Done; or Rejection Letter]")
        self.assertEqual(words(line.accepted), ["grant", "acceptance speech", "promptly done", "rejection letter"])
        self.assertEqual((line.prompts, line.rejected), ((), ()))

    def test_directive_words_and_separators_inside_quotes_are_text(self):
        line = parse_answerline('Grant [accept "Sam, or Jim; prompt on none"]')
        self.assertEqual(words(line.accepted), ["grant", "sam or jim prompt on none"])
        self.assertEqual(line.prompts, ())

    def test_the_kind_carries_over_commas_and_or(self):
        line = parse_answerline("Grant [prompt on A, B, or C]")
        self.assertEqual(words(p.phrase for p in line.prompts), ["a", "b", "c"])

    def test_or_needs_to_be_a_word(self):
        line = parse_answerline("Grant [or Oreo; or Corn; or Sensibility]")
        self.assertEqual(words(line.accepted), ["grant", "oreo", "corn", "sensibility"])

    def test_directed_prompt_text(self):
        line = parse_answerline('Grant [prompt on Sam by asking "which Sam, or which Jim?"; accept Jim]')
        self.assertEqual([(words([p.phrase])[0], p.message) for p in line.prompts], [("sam", "which Sam, or which Jim?")])
        self.assertEqual(words(line.accepted), ["grant", "jim"])

    def test_anti_prompt_is_a_prompt(self):
        line = parse_answerline('Grant [anti-prompt on Sam by asking “what first name?”]')
        self.assertEqual([p.message for p in line.prompts], ["what first name?"])

    def test_timing_conditions_are_dropped(self):
        cases = {
            "prompt on A before the first “galaxy”": ["a"],
            "prompt on A until “galaxy” is read": ["a"],
            "prompt on A until read": ["a"],
            "prompt on A after mentioned": ["a"],
            "prompt on Before Sunrise": ["before sunrise"],
            "prompt on After Dark": ["after dark"],
            "prompt on Mr. Deeds Goes After Dark": ["mr deeds goes after dark"],
        }
        for directive, expected in cases.items():
            with self.subTest(directive=directive):
                self.assertEqual(words(p.phrase for p in parse_answerline(f"Grant [{directive}]").prompts), expected)

    def test_timing_after_a_directed_prompt_message_keeps_the_message(self):
        line = parse_answerline('Grant [prompt on A until “x” is read by asking “what?”]')
        self.assertEqual([(words([p.phrase])[0], p.message) for p in line.prompts], [("a", "what?")])

    def test_word_forms_flag(self):
        self.assertTrue(parse_answerline("Grant [accept word forms]").word_forms)
        self.assertTrue(parse_answerline("Grant (accept word form like <u>Italy</u>)").word_forms)
        self.assertFalse(parse_answerline("Grant [accept Sam]").word_forms)

    def test_either_underlined_portion_adds_each_run(self):
        line = parse_answerline("<b><u>Philippe II</u></b>, <b><u>Duke of Orléans</u></b> [accept either underlined portion]")
        self.assertEqual(words(line.accepted[1:]), ["philippe 2", "duke of orleans"])  # and no answer reading "either underlined portion"

    def test_a_rejected_answer_that_is_also_accepted_is_not_rejected(self):
        line = parse_answerline("<u>house mouse</u> [do not accept House Mouse, Senate Mouse]")
        self.assertEqual(words(line.rejected), ["senate mouse"])

    def test_a_rejected_article_variant_is_kept(self):
        line = parse_answerline("<u>Invisible Man</u> [reject “The Invisible Man”]")
        self.assertEqual(len(line.rejected), 1)

    def test_parsing_is_cached_and_immutable(self):
        first = parse_answerline("Grant [or Sam]")
        self.assertIs(first, parse_answerline("Grant [or Sam]"))
        with self.assertRaises(Exception):
            first.accepted = ()


if __name__ == "__main__":
    unittest.main()
