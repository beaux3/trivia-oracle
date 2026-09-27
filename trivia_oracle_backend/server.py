"""
HTTP service in front of a question backend. The Telegram bot is its client.

  GET  /health         -> {"backend": "api" | "local"}
  POST /random-tossup  {subcategories, alternate_subcategories, difficulties, custom}
                       -> {question_sanitized, answer, answer_sanitized}
                          plus {custom: true, category, id} when the question is a custom one
                          404 if nothing matches, 502 if the backend fails
  POST /rate-tossup    {id, rating: "good" | "bad", previous: "good" | "bad" | null}
                       -> {good_votes, bad_votes}, the question's new totals
                          Adds one player's vote to a custom question's votes in the database. `previous` is
                          the vote that same player gave it before, if any: it is withdrawn, so changing a vote
                          moves it. Deciding who may vote, and when, is the client's job; this only counts.
                          404 if there is no custom question with that id, 502 if the write fails
  POST /check-answer   {answerline, given} -> {directive, directed_prompt, final}
                       final is true when the verdict is exact (the local judge), so the
                       bot does not apply its own lenient spelling pass to a reject

Filter fields are lists of strings or null. `custom` says whether to draw from the
custom question database: "exclude" (the default) never does, "only" always does,
and "include" picks the custom or the main source with equal odds (the custom set is
tiny, so mixing by size would almost never show it) and falls back to the other one
when the first has nothing. Custom questions ignore every filter. This wire format is
the only contract with the bot; the two never import each other.
"""
import logging
import random
from typing import Optional

from aiohttp import web

from .base import AnswerJudge, QuestionFilters, QuestionSource
from .local.db import RATINGS
from .local.question_source import ALT_SUBCATEGORY_PARENTS

_FILTER_FIELDS = ("subcategories", "alternate_subcategories", "difficulties")
_CUSTOM_MODES = ("exclude", "include", "only")
NO_CUSTOM_QUESTIONS = (
    "No custom questions are loaded. Add some with `python -m trivia_oracle_backend.custom.add`."
)


def _string_list(body: dict, field: str):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise web.HTTPBadRequest(text=f"{field} must be a list of strings or null")
    return value


def _custom_mode(body: dict) -> str:
    mode = body.get("custom")
    if mode is None:
        return "exclude"
    if mode not in _CUSTOM_MODES:
        raise web.HTTPBadRequest(text=f"custom must be one of {', '.join(_CUSTOM_MODES)} or null")
    return mode


def _rating_field(body: dict, field: str, required: bool) -> Optional[str]:
    value = body.get(field)
    if value is None and not required:
        return None
    if value not in RATINGS:
        raise web.HTTPBadRequest(text=f"{field} must be one of {', '.join(RATINGS)}" + ("" if required else " or null"))
    return value


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="body must be JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    return body


def _tossup_json(tossup, is_custom: bool) -> dict:
    body = {
        "question_sanitized": tossup.question_sanitized,
        "answer": tossup.answer,
        "answer_sanitized": tossup.answer_sanitized,
    }
    if is_custom:
        body.update(custom=True, category=getattr(tossup, "category", None), id=getattr(tossup, "id", None))
    return body


def build_app(question_source: QuestionSource, answer_judge: AnswerJudge, backend_name: str,
              custom_source: Optional[QuestionSource] = None) -> web.Application:
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"backend": backend_name})

    async def random_tossup(request: web.Request) -> web.Response:
        body = await _json_body(request)
        filters = QuestionFilters(*(_string_list(body, f) for f in _FILTER_FIELDS))
        for alt in filters.alternate_subcategories or []:
            if alt not in ALT_SUBCATEGORY_PARENTS:
                raise web.HTTPBadRequest(text=f"unknown alternate subcategory: {alt}")
        custom_mode = _custom_mode(body)

        # (source, is_custom) in the order they are tried; the first one with a question wins.
        candidates = [(question_source, False)]
        if custom_mode == "only":
            candidates = [(custom_source, True)]
        elif custom_mode == "include":
            candidates.insert(0 if random.random() < 0.5 else 1, (custom_source, True))

        errors = []
        for source, is_custom in candidates:
            if source is None:
                errors.append(LookupError(NO_CUSTOM_QUESTIONS))
                continue
            try:
                tossup = await source.random_tossup(QuestionFilters() if is_custom else filters)
            except Exception as e:
                if is_custom and isinstance(e, (LookupError, FileNotFoundError)):
                    errors.append(LookupError(NO_CUSTOM_QUESTIONS))  # nothing loaded (yet)
                elif isinstance(e, LookupError):
                    errors.append(e)
                else:
                    logging.exception("random-tossup failed")
                    errors.append(e)
            else:
                return web.json_response(_tossup_json(tossup, is_custom))

        error = errors[-1]
        if all(isinstance(e, LookupError) for e in errors):
            return web.json_response({"error": str(error)}, status=404)
        return web.json_response({"error": str(error)}, status=502)

    async def rate_tossup(request: web.Request) -> web.Response:
        body = await _json_body(request)
        tossup_id = body.get("id")
        if not isinstance(tossup_id, str) or not tossup_id:
            raise web.HTTPBadRequest(text="id must be a non-empty string")
        rating = _rating_field(body, "rating", required=True)
        previous = _rating_field(body, "previous", required=False)
        if custom_source is None:
            return web.json_response({"error": NO_CUSTOM_QUESTIONS}, status=404)
        try:
            good, bad = await custom_source.rate_tossup(tossup_id, rating, previous)
        except FileNotFoundError:
            return web.json_response({"error": NO_CUSTOM_QUESTIONS}, status=404)
        except LookupError as e:
            return web.json_response({"error": str(e)}, status=404)
        except Exception as e:
            logging.exception("rate-tossup failed")
            return web.json_response({"error": str(e)}, status=502)
        return web.json_response({"good_votes": good, "bad_votes": bad})

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
            "final": bool(getattr(judgement, "final", False)),
        })

    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.post("/random-tossup", random_tossup),
        web.post("/rate-tossup", rate_tossup),
        web.post("/check-answer", check_answer),
    ])
    return app
