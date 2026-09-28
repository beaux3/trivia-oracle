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
        if body.get("custom") == "only":
            return web.json_response({"question_sanitized": "Custom Q?", "answer": "<b>C</b>", "answer_sanitized": "C",
                                      "custom": True, "category": "Singapore", "id": "merlion-id"})
        return web.json_response({"question_sanitized": "Q?", "answer": "<b>A</b>", "answer_sanitized": "A"})

    async def rate_tossup(request):
        body = await request.json()
        received.append(body)
        if body["id"] == "unknown":
            return web.json_response({"error": "No custom question with that id"}, status=404)
        if body["id"] == "broken":
            return web.json_response({"error": "disk error"}, status=502)
        return web.json_response({"good_votes": 4, "bad_votes": 2})

    async def record_play(request):
        body = await request.json()
        received.append(body)
        if body["id"] == "unknown":
            return web.json_response({"error": "No custom question with that id"}, status=404)
        return web.json_response({"times_played": 3, "times_answered": 2, "avg_num_clues_left_when_answered": 1.5})

    async def check_answer(request):
        received.append(await request.json())
        return web.json_response({"directive": "prompt", "directed_prompt": "more specific"})

    app = web.Application()
    app.add_routes([web.post("/random-tossup", random_tossup), web.post("/check-answer", check_answer),
                    web.post("/rate-tossup", rate_tossup), web.post("/record-play", record_play)])
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
        self.assertEqual(self.received, [{
            "subcategories": ["Biology"], "alternate_subcategories": None, "difficulties": ["3"], "custom": "exclude",
            "custom_subcategories": None, "exclude_custom_ids": None,
        }])

    async def test_custom_questions_come_back_marked_with_their_category(self):
        source = BackendQuestionSource(self.url)
        tossup = await source.random_tossup(QuestionFilters(custom="only"))
        self.assertEqual(tossup, Tossup("Custom Q?", "<b>C</b>", "C", custom=True, category="Singapore", id="merlion-id"))
        self.assertEqual(self.received[-1]["custom"], "only")
        # A qbreader question has neither field on the wire, and is not custom.
        plain = await source.random_tossup(QuestionFilters())
        self.assertEqual((plain.custom, plain.category, plain.id), (False, None, None))

    async def test_rate_tossup_sends_the_vote_and_the_one_it_replaces(self):
        source = BackendQuestionSource(self.url)
        self.assertEqual(await source.rate_tossup("merlion-id", "good", None), (4, 2))
        self.assertEqual(await source.rate_tossup("merlion-id", "bad", "good"), (4, 2))
        self.assertEqual(self.received, [
            {"id": "merlion-id", "rating": "good", "previous": None},
            {"id": "merlion-id", "rating": "bad", "previous": "good"},
        ])

    async def test_rate_tossup_errors_follow_the_same_rules_as_drawing(self):
        source = BackendQuestionSource(self.url)
        with self.assertRaisesRegex(LookupError, "No custom question"):
            await source.rate_tossup("unknown", "good", None)
        with self.assertRaisesRegex(RuntimeError, "502"):
            await source.rate_tossup("broken", "good", None)

    async def test_record_play_sends_the_clues_left_and_returns_the_stats(self):
        source = BackendQuestionSource(self.url)
        self.assertEqual(await source.record_play("merlion-id", 2), (3, 2, 1.5))
        await source.record_play("merlion-id", None)
        self.assertEqual(self.received, [{"id": "merlion-id", "clues_left": 2}, {"id": "merlion-id", "clues_left": None}])
        with self.assertRaisesRegex(LookupError, "No custom question"):
            await source.record_play("unknown", 1)

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
