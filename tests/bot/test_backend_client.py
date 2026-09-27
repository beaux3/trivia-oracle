"""The bot's HTTP client against a stand-in backend serving the documented wire format."""
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from trivia_oracle_bot.questions import (
    BackendAnswerJudge, BackendQuestionSource, Judgement, QuestionFilters, Tossup,
)


def _stand_in_backend(received):
    async def random_tossup(request):
        body = await request.json()
        received.append(body)
        if body["difficulties"] == ["10"]:
            return web.json_response({"error": "No tossups match"}, status=404)
        if body["difficulties"] == ["0"]:
            return web.json_response({"error": "qbreader down"}, status=502)
        return web.json_response({"question_sanitized": "Q?", "answer": "<b>A</b>", "answer_sanitized": "A"})

    async def check_answer(request):
        received.append(await request.json())
        return web.json_response({"directive": "prompt", "directed_prompt": "more specific"})

    app = web.Application()
    app.add_routes([web.post("/random-tossup", random_tossup), web.post("/check-answer", check_answer)])
    return app


class BackendClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.server = TestServer(_stand_in_backend(self.received))
        await self.server.start_server()
        self.url = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        await self.server.close()

    async def test_random_tossup_sends_filters_and_parses_the_tossup(self):
        tossup = await BackendQuestionSource(self.url).random_tossup(QuestionFilters(["Biology"], None, ["3"]))
        self.assertEqual(tossup, Tossup("Q?", "<b>A</b>", "A"))
        self.assertEqual(self.received, [{"subcategories": ["Biology"], "alternate_subcategories": None, "difficulties": ["3"]}])

    async def test_404_is_a_lookup_error_and_other_failures_are_runtime_errors(self):
        source = BackendQuestionSource(self.url)
        with self.assertRaisesRegex(LookupError, "No tossups match"):
            await source.random_tossup(QuestionFilters(difficulties=["10"]))
        with self.assertRaisesRegex(RuntimeError, "502"):
            await source.random_tossup(QuestionFilters(difficulties=["0"]))

    async def test_unreachable_backend_raises(self):
        with self.assertRaises(Exception):
            await BackendQuestionSource("http://127.0.0.1:1").random_tossup(QuestionFilters())

    async def test_check_answer(self):
        judgement = await BackendAnswerJudge(self.url).check("<b>A</b>", "a")
        self.assertEqual(judgement, Judgement("prompt", "more specific"))
        self.assertEqual(self.received, [{"answerline": "<b>A</b>", "given": "a"}])


if __name__ == "__main__":
    unittest.main()
