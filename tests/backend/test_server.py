"""The HTTP service: request validation, status codes and the JSON it returns."""
from types import SimpleNamespace
from unittest import mock

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


class FakeCustomSource:
    def __init__(self):
        self.seen = []
        self.rated = []
        self.error = None
        self.rate_error = None

    async def rate_tossup(self, tossup_id, rating, previous):
        self.rated.append((tossup_id, rating, previous))
        if self.rate_error:
            raise self.rate_error
        return (4, 2)

    async def random_tossup(self, filters: QuestionFilters):
        self.seen.append(filters)
        if self.error:
            raise self.error
        return SimpleNamespace(question_sanitized="Custom Q?", answer="<b>C</b>", answer_sanitized="C",
                               category="Singapore", id="custom-1")


class FakeJudge:
    async def check(self, answerline, given):
        if given == "boom":
            raise RuntimeError("qbreader down")
        return SimpleNamespace(directive="accept" if given == "a" else "reject", directed_prompt=None)


class ServerWithoutCustomSourceTest(AioHTTPTestCase):
    async def get_application(self):
        return build_app(FakeSource(), FakeJudge(), "local")

    async def test_rating_without_a_custom_source_is_404(self):
        response = await self.client.post("/rate-tossup", json={"id": "c", "rating": "good"})
        self.assertEqual(response.status, 404)


class ServerTest(AioHTTPTestCase):
    async def get_application(self):
        self.source = FakeSource()
        self.custom = FakeCustomSource()
        return build_app(self.source, FakeJudge(), "local", custom_source=self.custom)

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

    async def test_custom_only_draws_from_the_custom_source_and_names_its_category(self):
        response = await self.client.post("/random-tossup", json={
            "subcategories": ["Biology"], "difficulties": ["3"], "custom": "only",
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {
            "question_sanitized": "Custom Q?", "answer": "<b>C</b>", "answer_sanitized": "C",
            "custom": True, "category": "Singapore", "id": "custom-1",
        })
        # Custom questions ignore the category and difficulty filters, and the main source is never asked.
        self.assertEqual(self.custom.seen, [QuestionFilters(None, None, None)])
        self.assertEqual(self.source.seen, [])

    async def test_custom_exclude_or_missing_never_touches_the_custom_source(self):
        for payload in ({}, {"custom": None}, {"custom": "exclude"}):
            response = await self.client.post("/random-tossup", json=payload)
            self.assertEqual(response.status, 200)
            self.assertNotIn("custom", await response.json())
        self.assertEqual(self.custom.seen, [])

    async def test_custom_include_picks_either_source_at_random(self):
        with mock.patch("trivia_oracle_backend.server.random.random", return_value=0.1):
            body = await (await self.client.post("/random-tossup", json={"custom": "include"})).json()
        self.assertEqual((body["custom"], body["category"]), (True, "Singapore"))
        with mock.patch("trivia_oracle_backend.server.random.random", return_value=0.9):
            body = await (await self.client.post("/random-tossup", json={
                "subcategories": ["Biology"], "custom": "include",
            })).json()
        self.assertNotIn("custom", body)
        self.assertEqual(self.source.seen, [QuestionFilters(["Biology"], None, None)])

    async def test_custom_include_falls_back_to_the_other_source(self):
        self.custom.error = LookupError("no custom questions")
        with mock.patch("trivia_oracle_backend.server.random.random", return_value=0.1):
            response = await self.client.post("/random-tossup", json={"custom": "include"})
        self.assertEqual((response.status, (await response.json())["answer_sanitized"]), (200, "A"))

        self.custom.error = None
        self.source.error = LookupError("nothing matches")
        with mock.patch("trivia_oracle_backend.server.random.random", return_value=0.9):
            response = await self.client.post("/random-tossup", json={"custom": "include"})
        self.assertEqual((response.status, (await response.json())["answer_sanitized"]), (200, "C"))

    async def test_custom_only_with_nothing_loaded_is_404(self):
        for error in (LookupError("empty"), FileNotFoundError("no file")):
            self.custom.error = error
            response = await self.client.post("/random-tossup", json={"custom": "only"})
            self.assertEqual(response.status, 404)
            self.assertIn("custom", (await response.json())["error"].lower())

    async def test_custom_include_with_both_sources_empty_is_404(self):
        self.custom.error = LookupError("empty")
        self.source.error = LookupError("nothing matches")
        response = await self.client.post("/random-tossup", json={"custom": "include"})
        self.assertEqual(response.status, 404)

    async def test_custom_source_failure_is_502_when_it_is_the_only_option(self):
        self.custom.error = RuntimeError("disk error")
        response = await self.client.post("/random-tossup", json={"custom": "only"})
        self.assertEqual(response.status, 502)

    async def test_unknown_custom_mode_is_400(self):
        for value in ("all", 1, True):
            response = await self.client.post("/random-tossup", json={"custom": value})
            self.assertEqual(response.status, 400, value)

    async def test_ordinary_questions_do_not_expose_an_id(self):
        body = await (await self.client.post("/random-tossup", json={})).json()
        self.assertNotIn("id", body)

    async def test_rate_tossup_writes_the_vote_through_the_custom_source(self):
        response = await self.client.post("/rate-tossup", json={"id": "custom-1", "rating": "good", "previous": None})
        self.assertEqual((response.status, await response.json()), (200, {"good_votes": 4, "bad_votes": 2}))
        response = await self.client.post("/rate-tossup", json={"id": "custom-1", "rating": "bad", "previous": "good"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.custom.rated, [("custom-1", "good", None), ("custom-1", "bad", "good")])

    async def test_previous_is_optional(self):
        response = await self.client.post("/rate-tossup", json={"id": "custom-1", "rating": "good"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.custom.rated, [("custom-1", "good", None)])

    async def test_rate_tossup_bad_requests_are_400_and_write_nothing(self):
        for payload in (
            {}, [], {"rating": "good"}, {"id": "c"}, {"id": 1, "rating": "good"}, {"id": "", "rating": "good"},
            {"id": "c", "rating": "great"}, {"id": "c", "rating": None}, {"id": "c", "rating": "good", "previous": "great"},
            {"id": "c", "rating": "good", "previous": 1},
        ):
            response = await self.client.post("/rate-tossup", json=payload)
            self.assertEqual(response.status, 400, payload)
        response = await self.client.post("/rate-tossup", data="not json")
        self.assertEqual(response.status, 400)
        self.assertEqual(self.custom.rated, [])

    async def test_rating_an_unknown_question_or_an_empty_database_is_404(self):
        for error in (LookupError("no such question"), FileNotFoundError("no file")):
            self.custom.rate_error = error
            response = await self.client.post("/rate-tossup", json={"id": "c", "rating": "good"})
            self.assertEqual(response.status, 404)

    async def test_rating_failure_is_502(self):
        self.custom.rate_error = RuntimeError("disk error")
        response = await self.client.post("/rate-tossup", json={"id": "c", "rating": "good"})
        self.assertEqual(response.status, 502)

    async def test_rate_tossup_is_post_only(self):
        response = await self.client.get("/rate-tossup")
        self.assertEqual(response.status, 405)

    async def test_check_answer(self):
        response = await self.client.post("/check-answer", json={"answerline": "<b>a</b>", "given": "a"})
        self.assertEqual(await response.json(), {"directive": "accept", "directed_prompt": None, "final": False})
        response = await self.client.post("/check-answer", json={"answerline": "<b>a</b>", "given": "boom"})
        self.assertEqual(response.status, 502)
