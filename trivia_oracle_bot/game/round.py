import asyncio
import enum
import logging
import re
import threading
import time
from typing import Callable, Optional

from ..config import (
    ALL_ALT_SUBCATEGORIES, CATEGORIES, DIFFICULTIES,
    POINTS_PER_CORRECT, POINTS_PER_MEDAL_WRONG, POINTS_PER_WRONG,
)
from ..questions import QuestionFilters, answer_judge, question_source
from .scores import format_scoreboard, medalist_ids, save_scores, scores, scores_lock
from .settings import settings
from .spelling import is_lenient_spelling_match

# ── Round state ───────────────────────────────────────────────────────────────

current_round: dict = {
    "active": False,
    "answer_sanitized": None,
    "answerline": None,
    "winners": [],       # [(first_name, points_awarded)] for everyone who answered correctly
    "winner_ids": set(), # user IDs already scored this round (one correct answer each)
    "penalties": {},     # {first_name: total_points_deducted} for wrong answers this round
    "sentences": [],
    "hourglasses": 0,    # ⏳ count on the latest clue message (hourglass scoring)
    "scoring_modes": frozenset(),  # snapshot of settings.scoring_modes at round start
    "medalists": set(),  # user IDs holding 🥇🥈🥉 at round start (medal_penalty scoring)
    "pending_checks": 0, # answers sent while active whose qbreader check hasn't returned yet
    "event": threading.Event(),
}
round_lock = threading.Lock()  # held for the duration of a round; prevents overlapping rounds
# Signalled whenever pending_checks drops, so the round can close once every
# answer sent before the buzzer has been judged. Shares scores_lock.
checks_settled = threading.Condition(scores_lock)
PENDING_CHECK_TIMEOUT = 15.0  # seconds; don't hold the round open forever if qbreader hangs
SESSION_TIMEOUT = 30 * 60  # seconds since the last successful /next
QUESTION_FETCH_ATTEMPTS = 5
QUESTION_FETCH_TIMEOUT = 15.0  # total seconds across all duplicate draws


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_filters() -> QuestionFilters:
    """
    Turn the /configure selections into question filters.

    settings.selected_categories is split across the two qbreader fields
    (subcategories / alternate_subcategories). A dimension with everything
    selected becomes None (= no filter), which also keeps qbreader API URLs short.
    """
    subcategories = alt_subcategories = difficulties = None
    if settings.selected_categories != set(CATEGORIES):
        subcategories = [c for c in settings.selected_categories if c not in ALL_ALT_SUBCATEGORIES] or None
        alt_subcategories = [c for c in settings.selected_categories if c in ALL_ALT_SUBCATEGORIES] or None
    if settings.selected_difficulties != set(DIFFICULTIES):
        difficulties = [DIFFICULTIES[d] for d in settings.selected_difficulties]
    return QuestionFilters(subcategories, alt_subcategories, difficulties)


async def _fetch_tossup():
    return await question_source.random_tossup(_build_filters())


async def _fetch_fresh_tossup(seen: set):
    for _ in range(QUESTION_FETCH_ATTEMPTS):
        tossup = await _fetch_tossup()
        if tossup.question_sanitized not in seen:
            return tossup
    return None


def _points_for_correct() -> int:
    if "hourglass" in current_round["scoring_modes"]:
        return POINTS_PER_CORRECT * current_round["hourglasses"]
    return POINTS_PER_CORRECT


def _penalty_for_wrong(user_id: int) -> int:
    modes = current_round["scoring_modes"]
    penalty = 0
    if "wrong_penalty" in modes:
        penalty += POINTS_PER_WRONG
    if "medal_penalty" in modes and user_id in current_round["medalists"]:
        penalty += POINTS_PER_MEDAL_WRONG
    return penalty


async def _check_answer(answerline: str, given: str):
    return await answer_judge.check(answerline, given)


# ── Round execution ───────────────────────────────────────────────────────────
# `announce(text)` posts a message to the chat the round is running in.

def _run_round(announce: Callable[[str], None], end_hint: str) -> None:
    try:
        _run_round_body(announce, end_hint)
    finally:
        with scores_lock:
            current_round["active"] = False
        round_lock.release()


def _run_round_body(announce: Callable[[str], None], end_hint: str) -> None:
    sentences = current_round["sentences"]
    total = len(sentences)

    for i, sentence in enumerate(sentences):
        if current_round["event"].is_set():
            break
        current_round["hourglasses"] = total - i
        announce(f"{'🎯' * (i + 1)}\n{sentence}\n{'⏳' * (total - i)}")
        current_round["event"].wait(settings.sentence_interval)

    if not current_round["event"].is_set():
        current_round["event"].wait(settings.answer_wait)

    with checks_settled:
        current_round["active"] = False
        # Answers sent at the same moment as the first correct one are still
        # being checked; score them before announcing the result.
        if not checks_settled.wait_for(lambda: current_round["pending_checks"] == 0, PENDING_CHECK_TIMEOUT):
            logging.warning("Closing round with %d answer check(s) still pending", current_round["pending_checks"])
    announce(_round_end_text() + end_hint)
    announce(format_scoreboard())


def _round_end_text() -> str:
    winners = current_round["winners"]
    penalties = current_round["penalties"]

    if winners:
        if "hourglass" in current_round["scoring_modes"]:
            labels = [f"{name} (+{pts} pts)" for name, pts in winners]
        else:
            labels = [name for name, _ in winners]
        if len(labels) == 1:
            congrats = f"Congrats {labels[0]} answered correctly!"
        else:
            names = ", ".join(labels[:-1]) + f" & {labels[-1]}"
            congrats = f"Congrats {names} all answered correctly!"
        result = f"✅✅✅ [ROUND END] ✅✅✅\n {congrats}\n\n Answer: {current_round['answer_sanitized']}"
    else:
        result = f"❌❌❌ [ROUND END] ❌❌❌\n Sad to say, nobody answered correctly.\n\n The answer is actually: {current_round['answer_sanitized']}"

    if penalties:
        penalty_lines = "\n".join(f"  -{pts} pts — {name}" for name, pts in sorted(penalties.items()))
        result += f"\n\n❌ Wrong answer deductions:\n{penalty_lines}"
    return result


# ── Public API (called by bot/round_handlers.py) ──────────────────────────────

class StartResult(enum.Enum):
    STARTED = "started"
    BUSY = "busy"                            # a round is already running; ignore silently
    FETCH_FAILED = "fetch_failed"            # the question source errored or timed out
    NO_FRESH_QUESTION = "no_fresh_question"  # every draw was already seen this session


def submit_answer(user_id: int, name: str, given: str, on_prompt: Callable[[str], None]) -> None:
    """
    Judge one player's answer to the running round, if any.

    Blocks while the answer is checked, so callers run it on a worker thread;
    simultaneous answers are judged in parallel. `on_prompt(text)` is called
    when the judge wants the player to be more specific.
    """
    with scores_lock:
        if not current_round["active"] or user_id in current_round["winner_ids"]:
            return
        current_round["pending_checks"] += 1
        if user_id not in scores:
            scores[user_id] = {"name": name, "score": 0}
        else:
            scores[user_id]["name"] = name

    try:
        prompt = _judge_answer(user_id, name, given.strip())
        if prompt:
            on_prompt(prompt)
    finally:
        with checks_settled:
            current_round["pending_checks"] -= 1
            checks_settled.notify_all()


def _judge_answer(user_id: int, name: str, given: str) -> Optional[str]:
    try:
        judgement = asyncio.run(_check_answer(current_round["answerline"], given))
    except Exception as e:
        logging.error("Answer check failed: %s", e)
        return

    if judgement.directive == "accept" or (
        judgement.directive == "reject"
        and is_lenient_spelling_match(current_round["answerline"], given)
    ):
        with scores_lock:
            if user_id in current_round["winner_ids"]:
                return
            points = _points_for_correct()
            scores[user_id]["score"] += points
            save_scores()
            current_round["winner_ids"].add(user_id)
            current_round["winners"].append((name, points))
        current_round["event"].set()

    elif judgement.directive == "prompt":
        return judgement.directed_prompt or "be more specific"

    elif judgement.directive == "reject":
        penalty = _penalty_for_wrong(user_id)
        if not penalty:
            return
        with scores_lock:
            scores[user_id]["score"] -= penalty
            save_scores()
            current_round["penalties"][name] = current_round["penalties"].get(name, 0) + penalty


def start_round(announce: Callable[[str], None], end_hint: str, session: dict) -> StartResult:
    """
    Fetch a question and run the round on a background thread.

    `session` is per-chat storage that persists between calls; it remembers
    which tossups the chat has seen. `end_hint` is appended to the round-end
    message (e.g. how to start the next round).
    """
    now = time.monotonic()
    last_next = session.get("last_next")

    if not round_lock.acquire(blocking=False):
        return StartResult.BUSY

    handed_off = False
    try:
        seen = (
            set() if last_next is None or now - last_next >= SESSION_TIMEOUT
            else session.get("seen_tossups", set())
        )

        try:
            tossup = asyncio.run(asyncio.wait_for(
                _fetch_fresh_tossup(seen), timeout=QUESTION_FETCH_TIMEOUT,
            ))
        except Exception as e:
            logging.error("Failed to fetch question: %s", e)
            return StartResult.FETCH_FAILED

        if tossup is None:
            return StartResult.NO_FRESH_QUESTION

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', tossup.question_sanitized) if s.strip()]
        with scores_lock:
            medalists = medalist_ids()
        current_round.update({
            "active": True,
            "answer_sanitized": tossup.answer_sanitized,
            "answerline": tossup.answer,
            "winners": [],
            "winner_ids": set(),
            "penalties": {},
            "sentences": sentences,
            "hourglasses": len(sentences),
            "scoring_modes": frozenset(settings.scoring_modes),
            "medalists": medalists,
            "pending_checks": 0,
        })
        current_round["event"].clear()
        logging.info("Answer: %s", tossup.answer_sanitized)

        threading.Thread(target=_run_round, args=(announce, end_hint), daemon=True).start()
        handed_off = True
        seen.add(tossup.question_sanitized)
        session["seen_tossups"] = seen
        session["last_next"] = now
        return StartResult.STARTED
    finally:
        if not handed_off:
            with scores_lock:
                current_round["active"] = False
            round_lock.release()
