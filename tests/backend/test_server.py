"""The HTTP service: request validation, status codes and the JSON it returns."""
from types import SimpleNamespace

from aiohttp.test_utils import AioHTTPTestCase

from trivia_oracle_backend import QuestionFilters
from trivia_oracle_backend.server import build_app


class FakeSource:
    def __init__(self):
        self.seen = []
        self.error = None

    async def random_tossup(self, filters: QuestionFilters):
        self.seen.append(filters)
        if self.error:
            raise self.error
        return SimpleNamespace(question_sanitized="Q?", answer="<b>A</b>", answer_sanitized="A", extra="dropped")


class FakeJudge:
    async def check(self, answerline, given):
        if given == "boom":
            raise RuntimeError("qbreader down")
        return SimpleNamespace(directive="accept" if given == "a" else "reject", directed_prompt=None)


class ServerTest(AioHTTPTestCase):
    async def get_application(self):
        self.source = FakeSource()
        return build_app(self.source, FakeJudge(), "local")

    async def test_health_names_the_backend(self):
        response = await self.client.get("/health")
        self.assertEqual(await response.json(), {"backend": "local"})

    async def test_random_tossup_passes_filters_and_returns_only_the_wire_fields(self):
        response = await self.client.post("/random-tossup", json={
            "subcategories": ["Biology"], "alternate_subcategories": ["Poetry"], "difficulties": ["3", "4"],
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"question_sanitized": "Q?", "answer": "<b>A</b>", "answer_sanitized": "A"})
        self.assertEqual(self.source.seen, [QuestionFilters(["Biology"], ["Poetry"], ["3", "4"])])

    async def test_missing_filters_mean_no_filter(self):
        response = await self.client.post("/random-tossup", json={})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.source.seen, [QuestionFilters(None, None, None)])

    async def test_bad_requests_are_400(self):
        for payload in ({"difficulties": "3"}, {"subcategories": [3]}, {"alternate_subcategories": ["Nope"]}, []):
            response = await self.client.post("/random-tossup", json=payload)
            self.assertEqual(response.status, 400, payload)
        response = await self.client.post("/random-tossup", data="not json")
        self.assertEqual(response.status, 400)
        response = await self.client.post("/check-answer", json={"answerline": "x"})
        self.assertEqual(response.status, 400)

    async def test_no_matching_tossup_is_404_and_backend_failure_is_502(self):
        self.source.error = LookupError("nothing matches")
        response = await self.client.post("/random-tossup", json={})
        self.assertEqual((response.status, await response.json()), (404, {"error": "nothing matches"}))
        self.source.error = RuntimeError("qbreader down")
        response = await self.client.post("/random-tossup", json={})
        self.assertEqual(response.status, 502)

    async def test_check_answer(self):
        response = await self.client.post("/check-answer", json={"answerline": "<b>a</b>", "given": "a"})
        self.assertEqual(await response.json(), {"directive": "accept", "directed_prompt": None, "final": False})
        response = await self.client.post("/check-answer", json={"answerline": "<b>a</b>", "given": "boom"})
        self.assertEqual(response.status, 502)
