"""
Local mode with the real answer checker: no scripted judge, no qbreader.

The backend service runs LocalAnswerJudge over a real SQLite database, and the bot's own
HTTP client and game code play rounds against it.
"""
import os
import tempfile
import unittest
from unittest import mock

import aiohttp

from tests.integration.support import LocalStack, tossup, wait_until

from trivia_oracle_backend import LocalAnswerJudge
from trivia_oracle_backend.api import qbreader_api
from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.game import scores as score_store
from trivia_oracle_bot.game.settings import settings
from trivia_oracle_bot.questions import BackendAnswerJudge, BackendQuestionSource

COLLEGE_8 = "College ⭐⭐⭐ (8)"

GRANT = (
    'Ulysses S. <b><u>Grant</u></b> [or Ulysses Simpson <b><u>Grant</u></b>; '
    'prompt on <u>General</u> by asking "which general?"; prompt on <u>Union</u>; do not accept or prompt on “Wood”]'
)


class NoQbreader:
    """Fails the test if anything reaches for qbreader.org."""

    def __enter__(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the local backend called qbreader")

        self._patches = [
            mock.patch.object(qbreader_api.Async, "create", refuse),
            mock.patch.object(qbreader_api.QbreaderAnswerJudge, "check", refuse),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class LocalJudgeOverHttpTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack([tossup("grant", answerline=GRANT)], judge=LocalAnswerJudge())

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    async def asyncSetUp(self):
        self.http = aiohttp.ClientSession(self.stack.url)
        self.no_qbreader = NoQbreader().__enter__()

    async def asyncTearDown(self):
        self.no_qbreader.__exit__()
        await self.http.close()

    async def check(self, given, answerline=GRANT):
        async with self.http.post("/check-answer", json={"answerline": answerline, "given": given}) as response:
            return response.status, await response.json()

    async def test_the_stored_answerline_is_served_with_its_html(self):
        async with self.http.post("/random-tossup", json={}) as response:
            body = await response.json()
        self.assertEqual(body["answer"], GRANT)
        self.assertNotIn("<", body["answer_sanitized"])

    async def test_local_verdicts_are_marked_final(self):
        for given in ("Grant", "wood"):
            _, body = await self.check(given)
            self.assertIs(body["final"], True)

    async def test_verdicts_over_the_wire(self):
        cases = {
            "Grant": ("accept", None),
            "ulysses grant": ("accept", None),
            "Ulyses Grant": ("accept", None),
            "General": ("prompt", "which general?"),
            "Union": ("prompt", None),
            "Wood": ("reject", None),
            "Sherman": ("reject", None),
            "": ("reject", None),
        }
        for given, (directive, prompt) in cases.items():
            with self.subTest(given=given):
                self.assertEqual(await self.check(given), (200, {"directive": directive, "directed_prompt": prompt, "final": True}))

    async def test_odd_but_valid_requests_get_verdicts_not_errors(self):
        for answerline, given in [("", ""), ("[", "]"), ("<b>", "x" * 5000), ("é" * 10000, "é"), ("Grant", "\U0001F600" * 50)]:
            with self.subTest(answerline=answerline[:10], given=given[:10]):
                status, body = await self.check(given, answerline)
                self.assertEqual(status, 200)
                self.assertIn(body["directive"], ("accept", "reject", "prompt"))

    async def test_bad_requests_are_still_400(self):
        for payload in ({}, {"answerline": "a"}, {"answerline": 1, "given": "a"}):
            with self.subTest(payload=payload):
                async with self.http.post("/check-answer", json=payload) as response:
                    self.assertEqual(response.status, 400)


class LocalJudgeRoundTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack([tossup("grant", answerline=GRANT, difficulty=8)], judge=LocalAnswerJudge())

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self._saved_settings = dict(vars(settings))
        settings.selected_difficulties = {COLLEGE_8}
        settings.sentence_interval = 0.3
        settings.answer_wait = 0.5
        self._tmp = tempfile.TemporaryDirectory()
        for p in (
            mock.patch.object(rnd, "question_source", BackendQuestionSource(self.stack.url)),
            mock.patch.object(rnd, "answer_judge", BackendAnswerJudge(self.stack.url)),
            mock.patch.object(score_store, "SCORES_FILE", os.path.join(self._tmp.name, "scores.md")),
        ):
            p.start()
            self.addCleanup(p.stop)
        score_store.scores.clear()
        self.no_qbreader = NoQbreader().__enter__()
        self.messages = []

    def tearDown(self):
        self.no_qbreader.__exit__()
        wait_until(lambda: not rnd.round_lock.locked())
        vars(settings).clear()
        vars(settings).update(self._saved_settings)
        score_store.scores.clear()
        self._tmp.cleanup()

    def play(self, *answers):
        """Start a round and submit (user id, name, text) answers; returns the prompts each one produced."""
        rnd.start_round(self.messages.append, "", {})
        prompts = []
        for user_id, name, text in answers:
            got = []
            rnd.submit_answer(user_id, name, text, got.append)
            prompts.append(got)
        self.assertTrue(wait_until(lambda: not rnd.round_lock.locked()), "round did not end")
        return prompts

    def test_underlined_answer_wins_and_names_the_answer_as_printed(self):
        self.play((1, "Ada", "grant"))
        self.assertEqual(score_store.scores[1], {"name": "Ada", "score": 10})
        self.assertIn("Answer: Ulysses S. Grant [or Ulysses Simpson Grant;", "\n".join(self.messages))

    def test_a_directed_prompt_reaches_the_player_and_they_can_still_win(self):
        prompts = self.play((1, "Ada", "general"), (1, "Ada", "Ulysses Grant"))
        self.assertEqual(prompts, [["which general?"], []])
        self.assertEqual(score_store.scores[1]["score"], 10)

    def test_a_plain_prompt_uses_the_default_wording(self):
        prompts = self.play((1, "Ada", "union"))
        self.assertEqual(prompts, [["be more specific"]])
        self.assertEqual(score_store.scores[1]["score"], 0)

    def test_wrong_and_rejected_answers_do_not_score(self):
        self.play((1, "Ada", "wood"), (2, "Bo", "sherman"))
        self.assertEqual(score_store.scores[1]["score"], 0)
        self.assertEqual(score_store.scores[2]["score"], 0)
        self.assertIn("nobody answered correctly", "\n".join(self.messages))

    def test_wrong_penalty_applies_to_local_rejections(self):
        settings.scoring_modes = {"wrong_penalty"}
        self.play((1, "Ada", "wood"))
        self.assertEqual(score_store.scores[1]["score"], -1)

    def test_hourglass_bonus_works_with_the_local_judge(self):
        settings.scoring_modes = {"hourglass"}
        self.play((1, "Ada", "Grant"))
        self.assertEqual(score_store.scores[1]["score"], 20)


class LocalRejectIsFinalTest(LocalJudgeRoundTest):
    """The bot's own lenient spelling must not overturn the local judge ("conversation" is not "Conservation of Energy")."""

    @classmethod
    def setUpClass(cls):
        answerline = "<b><u>Conservation of Energy</u></b> [prompt on partial answer]"
        cls.stack = LocalStack([tossup("energy", answerline=answerline, difficulty=8)], judge=LocalAnswerJudge())

    test_underlined_answer_wins_and_names_the_answer_as_printed = None
    test_a_directed_prompt_reaches_the_player_and_they_can_still_win = None
    test_a_plain_prompt_uses_the_default_wording = None
    test_wrong_and_rejected_answers_do_not_score = None
    test_wrong_penalty_applies_to_local_rejections = None
    test_hourglass_bonus_works_with_the_local_judge = None

    def test_a_near_miss_the_judge_rejected_does_not_score(self):
        self.play((1, "Ada", "conversation"))
        self.assertEqual(score_store.scores[1]["score"], 0)
        self.assertIn("nobody answered correctly", "\n".join(self.messages))

    def test_the_real_answer_still_scores(self):
        self.play((1, "Ada", "conservation of energy"))
        self.assertEqual(score_store.scores[1]["score"], 10)


if __name__ == "__main__":
    unittest.main()
