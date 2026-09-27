"""The backend service's HTTP surface, called with a plain HTTP client over a real socket."""
import os
import tempfile
import unittest
from unittest import mock

import aiohttp

from tests.integration.support import LocalStack, tossup

from trivia_oracle_backend import __main__ as backend_main


class BackendHttpTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = LocalStack([
            tossup("mitosis", "Science", "Biology", difficulty=8),
            tossup("orbits", "Science", "Other Science", alt="Astronomy", difficulty=9),
        ])

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    async def asyncSetUp(self):
        self.http = aiohttp.ClientSession(self.stack.url)

    async def asyncTearDown(self):
        await self.http.close()

    async def post(self, path, **kwargs):
        async with self.http.post(path, **kwargs) as response:
            try:
                body = await response.json()
            except aiohttp.ContentTypeError:
                body = await response.text()
            return response.status, body

    async def test_health_reports_which_backend_is_serving(self):
        async with self.http.get("/health") as response:
            self.assertEqual((response.status, await response.json()), (200, {"backend": "local"}))

    async def test_random_tossup_returns_exactly_the_documented_fields(self):
        status, body = await self.post("/random-tossup", json={"subcategories": ["Biology"], "difficulties": ["8"]})
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "question_sanitized": "First clue for mitosis. Second clue for mitosis.",
            "answer": "<b><u>mitosis</u></b>",
            "answer_sanitized": "mitosis",
        })

    async def test_empty_object_means_no_filters(self):
        status, body = await self.post("/random-tossup", json={})
        self.assertEqual(status, 200)
        self.assertIn(body["answer_sanitized"], {"mitosis", "orbits"})

    async def test_null_filters_mean_no_filters(self):
        status, _ = await self.post("/random-tossup", json={
            "subcategories": None, "alternate_subcategories": None, "difficulties": None,
        })
        self.assertEqual(status, 200)

    async def test_no_match_is_404_with_an_error_message(self):
        status, body = await self.post("/random-tossup", json={"difficulties": ["2"]})
        self.assertEqual(status, 404)
        self.assertIn("No tossups", body["error"])

    async def test_malformed_requests_are_400(self):
        cases = [
            {"data": "not json"},
            {"json": ["a", "list"]},
            {"json": {"difficulties": "8"}},
            {"json": {"subcategories": [1, 2]}},
            {"json": {"alternate_subcategories": ["Not A Real Subcategory"]}},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                status, _ = await self.post("/random-tossup", **kwargs)
                self.assertEqual(status, 400)

    async def test_check_answer_relays_the_judges_verdict(self):
        status, body = await self.post("/check-answer", json={"answerline": "<b><u>mitosis</u></b>", "given": "Mitosis"})
        self.assertEqual((status, body), (200, {"directive": "accept", "directed_prompt": None, "final": False}))

        status, body = await self.post("/check-answer", json={"answerline": "<u>mitosis</u>", "given": "more specific"})
        self.assertEqual((status, body), (200, {"directive": "prompt", "directed_prompt": "the full name", "final": False}))

        status, body = await self.post("/check-answer", json={"answerline": "<u>mitosis</u>", "given": "meiosis"})
        self.assertEqual((status, body), (200, {"directive": "reject", "directed_prompt": None, "final": False}))

    async def test_check_answer_rejects_non_string_fields(self):
        for payload in ({}, {"answerline": "a"}, {"answerline": 1, "given": "a"}, {"answerline": "a", "given": None}):
            with self.subTest(payload=payload):
                status, _ = await self.post("/check-answer", json=payload)
                self.assertEqual(status, 400)

    async def test_judge_failure_is_502(self):
        status, body = await self.post("/check-answer", json={"answerline": "a", "given": "boom"})
        self.assertEqual(status, 502)
        self.assertIn("qbreader down", body["error"])

    async def test_unknown_route_and_wrong_method_are_rejected(self):
        async with self.http.get("/random-tossup") as response:
            self.assertEqual(response.status, 405)
        async with self.http.get("/nope") as response:
            self.assertEqual(response.status, 404)


class BackendStartupTest(unittest.TestCase):
    """__main__.main() must refuse to start on bad configuration instead of serving errors."""

    def served_with(self, backend, db_path):
        """The (source, judge) that main() hands to the service for this QUESTION_BACKEND."""
        with mock.patch.object(backend_main, "QUESTION_BACKEND", backend), \
                mock.patch.object(backend_main, "QUESTIONS_DB", db_path), \
                mock.patch.object(backend_main, "build_app") as build_app, \
                mock.patch.object(backend_main.web, "run_app"):
            backend_main.main()
        source, judge, name = build_app.call_args.args
        self.assertEqual(name, backend)
        return source, judge

    def test_local_mode_judges_answers_itself_and_api_mode_asks_qbreader(self):
        from trivia_oracle_backend import LocalAnswerJudge, LocalQuestionSource, QbreaderAnswerJudge, QbreaderQuestionSource
        from trivia_oracle_backend.local.db import connect

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "questions.db")
            connect(db_path).close()
            source, judge = self.served_with("local", db_path)
            self.assertIsInstance(source, LocalQuestionSource)
            self.assertIsInstance(judge, LocalAnswerJudge)
            self.assertNotIsInstance(judge, QbreaderAnswerJudge)

            source, judge = self.served_with("api", db_path)
            self.assertIsInstance(source, QbreaderQuestionSource)
            self.assertIsInstance(judge, QbreaderAnswerJudge)

    def test_local_mode_without_a_database_says_how_to_build_one(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(backend_main, "QUESTION_BACKEND", "local"), \
                mock.patch.object(backend_main, "QUESTIONS_DB", os.path.join(tmp, "missing.db")):
            with self.assertRaisesRegex(SystemExit, "local.sync"):
                backend_main.main()

    def test_unknown_backend_name_is_rejected(self):
        with mock.patch.object(backend_main, "QUESTION_BACKEND", "postgres"):
            with self.assertRaisesRegex(SystemExit, '"api" or "local"'):
                backend_main.main()


if __name__ == "__main__":
    unittest.main()
