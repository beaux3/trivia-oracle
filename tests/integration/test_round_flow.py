"""
Whole-game flow: game.round and the bot's HTTP client, against the real backend
service reading a real SQLite database. Only the qbreader answer judge is scripted.
"""
import asyncio
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.integration.support import LocalStack, tossup, wait_until

from trivia_oracle_bot.bot import round_handlers
from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.game import scores as score_store
from trivia_oracle_bot.game.round import StartResult
from trivia_oracle_bot.game.settings import settings
from trivia_oracle_bot.questions import BackendAnswerJudge, BackendQuestionSource

COLLEGE_8 = "College ⭐⭐⭐ (8)"
COLLEGE_7 = "College ⭐⭐ (7)"


class GameIntegrationTest(unittest.TestCase):
    TOSSUPS = [tossup("mitosis", difficulty=8)]

    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack(cls.TOSSUPS)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self._saved_settings = dict(vars(settings))
        settings.selected_difficulties = {COLLEGE_8}
        settings.sentence_interval = 0.3
        settings.answer_wait = 0.5

        self._tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(rnd, "question_source", BackendQuestionSource(self.stack.url)),
            mock.patch.object(rnd, "answer_judge", BackendAnswerJudge(self.stack.url)),
            mock.patch.object(score_store, "SCORES_FILE", os.path.join(self._tmp.name, "scores.md")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        score_store.scores.clear()
        self.stack.judge.calls.clear()

        self.messages = []
        self.session = {}

    def tearDown(self):
        wait_until(lambda: not rnd.round_lock.locked())
        vars(settings).clear()
        vars(settings).update(self._saved_settings)
        score_store.scores.clear()
        self._tmp.cleanup()

    def start(self, session=None):
        return rnd.start_round(self.messages.append, "\n\nNext: /next", session if session is not None else self.session)

    def finish_round(self):
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")

    def texts(self):
        return "\n".join(self.messages)

    def test_correct_answer_wins_the_round_and_is_scored(self):
        self.assertEqual(self.start(), StartResult.STARTED)
        prompts = []
        rnd.submit_answer(1, "Ada", "mitosis", prompts.append)
        self.finish_round()

        self.assertEqual(prompts, [])
        self.assertIn("Congrats Ada answered correctly!", self.texts())
        self.assertIn("Answer: mitosis", self.texts())
        self.assertEqual(score_store.scores[1], {"name": "Ada", "score": 10})
        self.assertIn("Ada — 10 pts", self.messages[-1])
        # The answerline reached the judge with its HTML intact, as the checker needs it.
        self.assertEqual(self.stack.judge.calls, [("<b><u>mitosis</u></b>", "mitosis")])

    def test_scores_are_persisted_to_the_scores_file(self):
        self.start()
        rnd.submit_answer(7, "Grace", "mitosis", lambda _: None)
        self.finish_round()
        with open(score_store.SCORES_FILE) as f:
            self.assertIn("| 1 | Grace | 10 | 7 |", f.read())

    def test_unanswered_round_reveals_each_clue_then_the_answer(self):
        self.assertEqual(self.start(), StartResult.STARTED)
        self.finish_round()

        clues = [m for m in self.messages if "clue for mitosis." in m]
        self.assertEqual(len(clues), 2)
        self.assertIn("First clue for mitosis.", clues[0])
        self.assertIn("Second clue for mitosis.", clues[1])
        self.assertIn("nobody answered correctly", self.texts())
        self.assertIn("The answer is actually: mitosis", self.texts())
        self.assertIn("Next: /next", self.texts())
        self.assertEqual(self.messages[-1], "📊 Scoreboard\n\nNo scores yet!")

    def test_directed_prompt_from_the_judge_is_relayed_to_the_player(self):
        self.start()
        prompts = []
        rnd.submit_answer(1, "Ada", "more specific", prompts.append)
        self.assertEqual(prompts, ["the full name"])
        rnd.submit_answer(1, "Ada", "mitosis", prompts.append)
        self.finish_round()
        self.assertIn("Congrats Ada", self.texts())

    def test_wrong_answer_costs_a_point_only_in_wrong_penalty_mode(self):
        self.start()
        rnd.submit_answer(1, "Ada", "photosynthesis", lambda _: None)
        self.finish_round()
        self.assertEqual(score_store.scores[1]["score"], 0)

        settings.scoring_modes = {"wrong_penalty"}
        self.messages.clear()
        self.session = {}
        self.start()
        rnd.submit_answer(1, "Ada", "photosynthesis", lambda _: None)
        self.finish_round()
        self.assertEqual(score_store.scores[1]["score"], -1)
        self.assertIn("-1 pts — Ada", self.texts())

    def test_hourglass_mode_scores_by_clues_remaining(self):
        settings.scoring_modes = {"hourglass"}
        self.start()
        rnd.submit_answer(1, "Ada", "mitosis", lambda _: None)
        self.finish_round()
        # Answered during the first of two clues: 2 hourglasses × 10 points.
        self.assertEqual(score_store.scores[1]["score"], 20)
        self.assertIn("Ada (+20 pts)", self.texts())

    def test_each_player_scores_once_per_round(self):
        self.start()
        rnd.submit_answer(1, "Ada", "mitosis", lambda _: None)
        rnd.submit_answer(1, "Ada", "mitosis", lambda _: None)
        self.finish_round()
        self.assertEqual(score_store.scores[1]["score"], 10)

    def test_answers_outside_a_round_are_ignored(self):
        rnd.submit_answer(1, "Ada", "mitosis", lambda _: None)
        self.assertEqual(score_store.scores, {})
        self.assertEqual(self.stack.judge.calls, [])

    def test_judge_outage_leaves_the_round_playable(self):
        self.start()
        prompts = []
        rnd.submit_answer(1, "Ada", "boom", prompts.append)  # backend answers 502
        self.assertEqual(prompts, [])
        rnd.submit_answer(2, "Bo", "mitosis", prompts.append)
        self.finish_round()
        self.assertIn("Congrats Bo", self.texts())
        self.assertNotIn("Ada", "\n".join(m for m in self.messages if "Congrats" in m))

    def test_second_next_during_a_round_is_busy(self):
        self.assertEqual(self.start(), StartResult.STARTED)
        self.assertEqual(self.start(session={}), StartResult.BUSY)
        self.finish_round()

    def test_a_chat_does_not_get_the_same_tossup_twice_while_a_fresh_one_is_available(self):
        self.assertEqual(self.start(), StartResult.STARTED)
        self.finish_round()
        # A different chat has not seen it yet.
        self.assertEqual(self.start(session={}), StartResult.STARTED)
        self.finish_round()

    def test_a_chat_gets_a_repeat_rather_than_no_question_once_the_pool_is_exhausted(self):
        self.assertEqual(self.start(), StartResult.STARTED)
        self.finish_round()
        # The database holds one tossup, and this chat has already seen it: getting a question
        # out still wins over avoiding the repeat, so the round starts again on the same one.
        self.assertEqual(self.start(), StartResult.STARTED)
        self.assertEqual(rnd.current_round["answer_sanitized"], "mitosis")
        self.finish_round()


class FilterIntegrationTest(unittest.TestCase):
    """The /configure selections must reach the database query through the HTTP hop."""

    TOSSUPS = [
        tossup("mitosis", "Science", "Biology", difficulty=8),
        tossup("enzymes", "Science", "Biology", difficulty=7),
        tossup("orbits", "Science", "Other Science", alt="Astronomy", difficulty=8),
        tossup("sonnet", "Literature", "British Literature", alt="Poetry", difficulty=8),
        tossup("treaty", "History", "European History", difficulty=9),
    ]

    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack(cls.TOSSUPS)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self._saved_settings = dict(vars(settings))
        patch = mock.patch.object(rnd, "question_source", BackendQuestionSource(self.stack.url))
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        vars(settings).clear()
        vars(settings).update(self._saved_settings)

    def draw_answers(self, times=30):
        return {asyncio.run(rnd._fetch_tossup()).answer_sanitized for _ in range(times)}

    def test_all_categories_and_difficulties_draws_from_everything(self):
        settings.selected_difficulties = set(rnd.DIFFICULTIES)
        self.assertEqual(self.draw_answers(150), {t["_id"] for t in self.TOSSUPS})

    def test_difficulty_selection_limits_the_draw(self):
        settings.selected_difficulties = {COLLEGE_7}
        self.assertEqual(self.draw_answers(), {"enzymes"})
        settings.selected_difficulties = {COLLEGE_7, "College ⭐⭐⭐⭐ (9)"}
        self.assertEqual(self.draw_answers(), {"enzymes", "treaty"})

    def test_subcategory_selection_limits_the_draw(self):
        settings.selected_difficulties = set(rnd.DIFFICULTIES)
        settings.selected_categories = {"Biology"}
        self.assertEqual(self.draw_answers(), {"mitosis", "enzymes"})

    def test_alternate_subcategory_selection_limits_the_draw(self):
        settings.selected_difficulties = set(rnd.DIFFICULTIES)
        settings.selected_categories = {"Astronomy"}
        # Astronomy is Science / Other Science; untagged tossups in that parent match too.
        self.assertEqual(self.draw_answers(), {"orbits"})

    def test_categories_and_difficulty_combine(self):
        settings.selected_difficulties = {COLLEGE_8}
        settings.selected_categories = {"Biology"}
        self.assertEqual(self.draw_answers(), {"mitosis"})

    def test_running_out_of_fresh_questions_across_several_categories_keeps_serving_repeats(self):
        # Two categories selected together (Biology + Astronomy) narrow the pool to 3 questions.
        # Ordinary draws are plain random with no server-side exclusion, so a session eventually
        # sees every one of them; from then on, getting a question out matters more than the
        # uniform-randomness rule, so every further draw still succeeds instead of failing once
        # nothing "fresh" is left.
        settings.selected_difficulties = set(rnd.DIFFICULTIES)
        settings.selected_categories = {"Biology", "Astronomy"}
        pool = {"mitosis", "enzymes", "orbits"}
        seen, drawn = set(), set()
        for _ in range(30):
            fetched, seen = asyncio.run(rnd._fetch_fresh_tossup(seen))
            seen.update(rnd._session_keys(fetched))
            drawn.add(fetched.answer_sanitized)
            self.assertIn(fetched.answer_sanitized, pool)
        self.assertEqual(drawn, pool)

    @unittest.expectedFailure
    def test_subcategory_and_alternate_subcategory_selections_are_a_union(self):
        # Known limitation: the two fields are ANDed, so Biology (subcategory) plus
        # Poetry (alternate subcategory of Literature) matches nothing at all.
        settings.selected_difficulties = {COLLEGE_8}
        settings.selected_categories = {"Biology", "Poetry"}
        self.assertEqual(self.draw_answers(), {"mitosis", "sonnet"})

    def test_no_match_is_a_lookup_error_naming_the_cause(self):
        settings.selected_difficulties = {"HS Easy (2)", "HS Regular (3)"}
        with self.assertRaisesRegex(LookupError, "match the selected categories and difficulties"):
            asyncio.run(rnd._fetch_tossup())


class CustomQuestionsIntegrationTest(unittest.TestCase):
    """The Custom category, from the settings through the HTTP hop to a played round."""

    TOSSUPS = [
        tossup("mitosis", "Science", "Biology", difficulty=8),
        tossup("pi", "Science", "Other Science", alt="Math", difficulty=8,
               question="This constant is the ratio of a circle's circumference to its diameter."),
        tossup("nile", "Geography", "Geography", difficulty=8,
               question="This African river is traditionally considered the world's longest."),
    ]
    CUSTOM = [
        tossup("merlion", "Singapore", "Singapore", difficulty=1,
               question="This creature guards a bay. It has a lion head."),
        tossup("laksa", "Singapore", "Singapore", difficulty=9,
               question="This noodle soup is spicy. It has coconut milk."),
        tossup("doge", "Memes", "Memes", difficulty=5,
               question="This meme dog speaks broken English. It says such wow."),
        tossup("sakura", "Japan", "Japan", difficulty=3,
               question="This flower's blossoms are celebrated each spring in Japan."),
    ]

    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack(cls.TOSSUPS, custom_tossups=cls.CUSTOM)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self._saved_settings = dict(vars(settings))
        settings.selected_difficulties = {COLLEGE_8}  # excludes the custom questions' difficulty 1
        settings.sentence_interval = 0.1
        settings.answer_wait = 0.1
        self._tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(rnd, "question_source", BackendQuestionSource(self.stack.url)),
            mock.patch.object(rnd, "answer_judge", BackendAnswerJudge(self.stack.url)),
            mock.patch.object(score_store, "SCORES_FILE", os.path.join(self._tmp.name, "scores.md")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        score_store.scores.clear()
        # The custom database is built once in setUpClass and rating tests leave real votes and
        # plays on it; reset them so a draw-mix test doesn't depend on what an earlier test did.
        conn = sqlite3.connect(self.stack.custom_db_path)
        conn.execute("UPDATE tossups SET good_votes = 0, bad_votes = 0, times_played = 0")
        conn.commit()
        conn.close()

    def tearDown(self):
        wait_until(lambda: not rnd.round_lock.locked())
        vars(settings).clear()
        vars(settings).update(self._saved_settings)
        score_store.scores.clear()
        rnd.current_round["rating"] = None
        rnd.current_round["ended_at"] = None
        self._tmp.cleanup()

    def draw(self, times=40):
        return [asyncio.run(rnd._fetch_tossup()) for _ in range(times)]

    def test_custom_only_draws_every_custom_question_whatever_the_other_filters(self):
        settings.custom_all = True
        settings.selected_categories = set()
        tossups = self.draw(60)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"merlion", "laksa", "doge", "sakura"})
        self.assertTrue(all(t.custom for t in tossups))

    def test_custom_mixed_with_other_categories_draws_from_both(self):
        # All qbreader categories are selected by default (settings.selected_categories),
        # so this also covers "several custom categories mixed with several non-custom ones".
        settings.custom_all = True
        tossups = self.draw(90)
        self.assertEqual({t.answer_sanitized for t in tossups},
                          {"mitosis", "pi", "nile", "merlion", "laksa", "doge", "sakura"})
        self.assertFalse(any(t.custom for t in tossups if t.answer_sanitized in ("mitosis", "pi", "nile")))

    def test_a_session_plays_every_custom_question_once_taking_the_categories_in_turn(self):
        settings.custom_all = True
        settings.selected_categories = set()
        for _ in range(10):
            seen, drawn = set(), []
            for _ in range(4):
                tossup, seen = asyncio.run(rnd._fetch_fresh_tossup(seen))
                seen.update(rnd._session_keys(tossup))
                drawn.append(tossup)
            self.assertEqual(sorted(t.answer_sanitized for t in drawn), ["doge", "laksa", "merlion", "sakura"])
            # Singapore, Memes and Japan once each before Singapore's second question.
            self.assertEqual({t.category for t in drawn[:3]}, {"Singapore", "Memes", "Japan"})
            # All four played: the next draw repeats one and starts the custom questions over.
            tossup, seen = asyncio.run(rnd._fetch_fresh_tossup(seen))
            self.assertIsNotNone(tossup)
            self.assertFalse(any(rnd._is_custom_key(key) for key in seen))

    def play_round(self, session):
        self.assertEqual(rnd.start_round(lambda _: None, "", session), StartResult.STARTED)
        answer = rnd.current_round["answer_sanitized"]  # the test data's answer is the question's id
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")
        rnd.submit_rating(1, "good")  # clears the /next rating gate
        return answer

    def test_rounds_in_one_chat_never_repeat_a_custom_question_until_all_are_played(self):
        settings.custom_all = True
        settings.selected_categories = set()
        session = {}
        played = [self.play_round(session) for _ in range(4)]
        self.assertEqual(sorted(played), ["doge", "laksa", "merlion", "sakura"])
        # Another chat's session is its own: it can still get the question this chat just had.
        self.assertIn(self.play_round({}), played)
        # A fifth round in the first chat starts the custom questions over instead of failing.
        self.assertIn(self.play_round(session), played)
        custom_ids = [key for key in session["seen_tossups"] if rnd._is_custom_key(key) and key[0] == "custom_id"]
        self.assertEqual(len(custom_ids), 1)

    def test_custom_off_never_draws_a_custom_question(self):
        settings.custom_all = False
        self.assertEqual({t.answer_sanitized for t in self.draw(60)}, {"mitosis", "pi", "nile"})

    def test_several_specific_custom_categories_are_all_drawn_from(self):
        # Regression: selecting "Custom: Memes" and "Custom: Singapore" together must draw
        # from both categories, not just one.
        settings.selected_custom_categories = {"Singapore", "Memes"}
        settings.selected_categories = set()
        tossups = self.draw(60)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"merlion", "laksa", "doge"})
        self.assertTrue(all(t.custom for t in tossups))

    def test_a_single_specific_custom_category_excludes_the_others(self):
        settings.selected_custom_categories = {"Memes"}
        settings.selected_categories = set()
        self.assertEqual({t.answer_sanitized for t in self.draw()}, {"doge"})

    def test_a_specific_custom_category_mixed_with_specific_non_custom_categories(self):
        # Regression: "Custom: Memes" plus non-custom "Biology" must draw from both, not just
        # the custom one.
        settings.selected_custom_categories = {"Memes"}
        settings.selected_categories = {"Biology"}
        tossups = self.draw(60)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"mitosis", "doge"})
        self.assertTrue(any(t.custom for t in tossups))
        self.assertTrue(any(not t.custom for t in tossups))

    def test_a_specific_custom_category_mixed_with_several_non_custom_categories(self):
        # The exact combination reported as buggy: "Custom: Memes" plus non-custom
        # "Math" and "Geography" must draw from all three, not just Memes.
        settings.selected_custom_categories = {"Memes"}
        settings.selected_categories = {"Math", "Geography"}
        tossups = self.draw(60)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"doge", "pi", "nile"})
        self.assertTrue(any(t.custom for t in tossups))
        self.assertTrue(any(not t.custom for t in tossups))

    def test_three_specific_custom_categories_are_all_drawn_from(self):
        # Selecting more than two specific custom categories together must still draw from
        # all of them, not just the first two (test_several_..._are_all_drawn_from covers two).
        settings.selected_custom_categories = {"Singapore", "Memes", "Japan"}
        settings.selected_categories = set()
        tossups = self.draw(60)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"merlion", "laksa", "doge", "sakura"})
        self.assertTrue(all(t.custom for t in tossups))

    def test_several_specific_custom_categories_mixed_with_several_non_custom_categories(self):
        # Two specific custom categories plus two non-custom categories, all at once.
        settings.selected_custom_categories = {"Singapore", "Memes"}
        settings.selected_categories = {"Biology", "Math"}
        tossups = self.draw(90)
        self.assertEqual({t.answer_sanitized for t in tossups}, {"merlion", "laksa", "doge", "mitosis", "pi"})
        self.assertTrue(any(t.custom for t in tossups))
        self.assertTrue(any(not t.custom for t in tossups))

    def test_a_custom_round_opens_with_its_label_and_can_be_won(self):
        settings.selected_custom_categories = {"Singapore"}
        settings.selected_categories = set()
        messages = []
        self.assertEqual(rnd.start_round(messages.append, "", {}), StartResult.STARTED)
        answer = rnd.current_round["answer_sanitized"]
        rnd.submit_answer(1, "Ada", answer, lambda _: None)
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")

        self.assertEqual(messages[0], "📝 Custom question\nCategory: Singapore")
        self.assertTrue(messages[1].startswith("🎯\n"), messages[1])
        self.assertIn(f"Answer: {answer}", "\n".join(messages))

    def votes(self, tossup_id):
        conn = sqlite3.connect(self.stack.custom_db_path)
        try:
            return conn.execute("SELECT good_votes, bad_votes FROM tossups WHERE id = ?", (tossup_id,)).fetchone()
        finally:
            conn.close()

    def play_custom_round(self, winner=None):
        """Run one custom-only round to its end; returns (question id, everything announced)."""
        settings.custom_all = True
        settings.selected_categories = set()
        messages = []
        self.assertEqual(rnd.start_round(messages.append, "\n\nNext: /next", {}), StartResult.STARTED)
        answer = rnd.current_round["answer_sanitized"]  # the test data's answer is the question's id
        if winner:
            rnd.submit_answer(winner, "Ada", answer, lambda _: None)
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")
        return answer, messages

    def test_players_rate_a_custom_question_after_its_round_and_the_database_is_updated(self):
        answer, messages = self.play_custom_round(winner=1)
        end = next(m for m in messages if "[ROUND END]" in m)
        self.assertTrue(end.endswith("\n\nNext: /next\n\nPlease rate the question /good or /bad"), end)

        good, bad = self.votes(answer)
        rnd.submit_rating(1, "good")
        rnd.submit_rating(2, "good")
        rnd.submit_rating(3, "bad")
        self.assertEqual(self.votes(answer), (good + 2, bad + 1))

    def test_spam_is_ignored_and_a_players_latest_choice_stands(self):
        answer, _ = self.play_custom_round()
        good, bad = self.votes(answer)
        for _ in range(5):
            rnd.submit_rating(1, "good")
        rnd.submit_rating(2, "bad")
        rnd.submit_rating(2, "good")   # pressed the wrong one first
        rnd.submit_rating(2, "good")
        rnd.submit_rating(1, "bad")    # changed their mind
        self.assertEqual(self.votes(answer), (good + 1, bad + 1))

    def test_votes_after_the_next_round_has_started_go_nowhere(self):
        answer, _ = self.play_custom_round()
        rnd.submit_rating(1, "good")  # satisfies the /next rating gate so round 2 can start right away
        settings.custom_all = False
        self.assertEqual(rnd.start_round(lambda _: None, "", {}), StartResult.STARTED)
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")
        before = {t: self.votes(t) for t in ("merlion", "laksa")}
        rnd.submit_rating(1, "good")
        self.assertEqual({t: self.votes(t) for t in ("merlion", "laksa")}, before)

    def test_ordinary_rounds_do_not_ask_for_a_rating(self):
        settings.custom_all = False
        messages = []
        rnd.start_round(messages.append, "", {})
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")
        self.assertNotIn("/good", "\n".join(messages))

    def test_next_is_refused_until_the_question_is_rated(self):
        self.play_custom_round()
        self.assertEqual(rnd.start_round(lambda _: None, "", {}), StartResult.NEEDS_RATING)
        rnd.submit_rating(1, "good")
        self.assertEqual(rnd.start_round(lambda _: None, "", {}), StartResult.STARTED)


class StartFailureIntegrationTest(unittest.TestCase):
    """/next when the backend has nothing to serve or cannot be reached."""

    def setUp(self):
        self._saved_settings = dict(vars(settings))
        settings.selected_difficulties = {"HS Easy (2)", "HS Regular (3)"}
        self.bot = SimpleNamespace(username="TriviaOracleBot")
        self.sent = []
        self.bot.send_message = lambda chat_id, text: self.sent.append(text)
        self.update = SimpleNamespace(effective_chat=SimpleNamespace(id=-1))
        self.context = SimpleNamespace(bot=self.bot, chat_data={})

    def tearDown(self):
        vars(settings).clear()
        vars(settings).update(self._saved_settings)
        wait_until(lambda: not rnd.round_lock.locked())

    def _next(self, url):
        with mock.patch.object(rnd, "question_source", BackendQuestionSource(url)):
            round_handlers.start_round(self.update, self.context)

    def test_no_matching_tossups_tells_the_chat_and_frees_the_lock(self):
        stack = LocalStack([tossup("mitosis", difficulty=8)])  # college only; HS is selected
        self.addCleanup(stack.close)
        self._next(stack.url)

        self.assertEqual(self.sent, ["Failed to fetch a question. Try /next again."])
        self.assertFalse(rnd.round_lock.locked())
        self.assertNotIn("last_next", self.context.chat_data)

    def test_the_same_chat_recovers_once_the_difficulty_matches(self):
        stack = LocalStack([tossup("mitosis", difficulty=8)])
        self.addCleanup(stack.close)
        self._next(stack.url)
        self.assertEqual(len(self.sent), 1)

        settings.selected_difficulties = {COLLEGE_8}
        self._next(stack.url)
        self.assertTrue(wait_until(lambda: any("[ROUND END]" in m for m in self.sent), timeout=30))
        self.assertIn("The answer is actually: mitosis", "\n".join(self.sent))

    def test_unreachable_backend_tells_the_chat_and_frees_the_lock(self):
        self._next("http://127.0.0.1:1")
        self.assertEqual(self.sent, ["Failed to fetch a question. Try /next again."])
        self.assertFalse(rnd.round_lock.locked())


if __name__ == "__main__":
    unittest.main()
