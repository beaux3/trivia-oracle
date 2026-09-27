"""
HTTP service in front of a question backend. The Telegram bot is its client.

  GET  /health         -> {"backend": "api" | "local"}
  POST /random-tossup  {subcategories, alternate_subcategories, difficulties}
                       -> {question_sanitized, answer, answer_sanitized}
                          404 if nothing matches, 502 if the backend fails
  POST /check-answer   {answerline, given} -> {directive, directed_prompt}

Filter fields are lists of strings or null. This wire format is the only
contract with the bot; the two never import each other.
"""
import logging

from aiohttp import web

from .base import AnswerJudge, QuestionFilters, QuestionSource
from .local.question_source import ALT_SUBCATEGORY_PARENTS

_FILTER_FIELDS = ("subcategories", "alternate_subcategories", "difficulties")


def _string_list(body: dict, field: str):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise web.HTTPBadRequest(text=f"{field} must be a list of strings or null")
    return value


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="body must be JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    return body


def build_app(question_source: QuestionSource, answer_judge: AnswerJudge, backend_name: str) -> web.Application:
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"backend": backend_name})

    async def random_tossup(request: web.Request) -> web.Response:
        body = await _json_body(request)
        filters = QuestionFilters(*(_string_list(body, f) for f in _FILTER_FIELDS))
        for alt in filters.alternate_subcategories or []:
            if alt not in ALT_SUBCATEGORY_PARENTS:
                raise web.HTTPBadRequest(text=f"unknown alternate subcategory: {alt}")
        try:
            tossup = await question_source.random_tossup(filters)
        except LookupError as e:
            return web.json_response({"error": str(e)}, status=404)
        except Exception as e:
            logging.exception("random-tossup failed")
            return web.json_response({"error": str(e)}, status=502)
        return web.json_response({
            "question_sanitized": tossup.question_sanitized,
            "answer": tossup.answer,
            "answer_sanitized": tossup.answer_sanitized,
        })

    async def check_answer(request: web.Request) -> web.Response:
        body = await _json_body(request)
        answerline, given = body.get("answerline"), body.get("given")
        if not isinstance(answerline, str) or not isinstance(given, str):
            raise web.HTTPBadRequest(text="answerline and given must be strings")
        try:
            judgement = await answer_judge.check(answerline, given)
        except Exception as e:
            logging.exception("check-answer failed")
            return web.json_response({"error": str(e)}, status=502)
        return web.json_response({
            "directive": str(judgement.directive),
            "directed_prompt": judgement.directed_prompt,
        })

    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.post("/random-tossup", random_tossup),
        web.post("/check-answer", check_answer),
    ])
    return app
