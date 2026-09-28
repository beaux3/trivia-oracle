import asyncio
import enum
import logging
import threading
import time
from typing import Callable, Optional

from ..config import (
    ALL_ALT_SUBCATEGORIES, CATEGORIES, DIFFICULTIES,
    POINTS_PER_CORRECT, POINTS_PER_MEDAL_WRONG, POINTS_PER_WRONG, RATINGS,
)
from ..questions import QuestionFilters, answer_judge, question_source
from .scores import format_scoreboard, medalist_ids, save_scores, scores, scores_lock
from .sentences import split_sentences
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
    "header": "",        # sent as its own message before the first clue (marks custom questions)
    "hourglasses": 0,    # ⏳ count on the latest clue message (hourglass scoring)
    "scoring_modes": frozenset(),  # snapshot of settings.scoring_modes at round start
    "medalists": set(),  # user IDs holding 🥇🥈🥉 at round start (medal_penalty scoring)
    "pending_checks": 0, # answers sent while active whose backend check hasn't returned yet
    # (question id, {user_id: "good" | "bad"}) once a custom question can be rated, else None. Rounds
    # replace it whole, so a vote still being sent for the last question can't land in the next one's.
    "rating": None,
    # Clues still unrevealed when the first correct answer was accepted; None until then. Sent to the
    # backend at the end of a custom round (the question's avg_num_clues_left_when_answered).
    "clues_left_when_answered": None,
    "ended_at": None,    # time.monotonic() when the round last finished; gates /next while it needs a rating
    "event": threading.Event(),
}
round_lock = threading.Lock()  # held for the duration of a round; prevents overlapping rounds
# Held while a player's vote is sent to the backend, so one player's votes arrive in the order they were made.
ratings_lock = threading.Lock()
RATING_PROMPT = "\n\nPlease rate the question /good or /bad"
# Signalled whenever pending_checks drops, so the round can close once every
# answer sent before the buzzer has been judged. Shares scores_lock.
checks_settled = threading.Condition(scores_lock)
PENDING_CHECK_TIMEOUT = 15.0  # seconds; don't hold the round open forever if the backend hangs
SIMULTANEOUS_ANSWER_GRACE = 0.5  # let queued replies register after a fast first verdict
RATING_GRACE_PERIOD = 10.0  # seconds /next is blocked after an unrated custom round, before it opens up anyway
SESSION_TIMEOUT = 30 * 60  # seconds since the last successful /next
QUESTION_FETCH_ATTEMPTS = 5
QUESTION_FETCH_TIMEOUT = 15.0  # total seconds across all duplicate draws


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_filters(exclude_custom_ids=None) -> QuestionFilters:
    """
    Turn the /configure selections into question filters.

    settings.selected_categories is split across the two backend filter fields
    (subcategories / alternate_subcategories). A dimension with everything
    selected becomes None (= no filter), which also keeps requests small.
    """
    subcategories = alt_subcategories = difficulties = custom_subcategories = None
    custom = "exclude"
    if settings.custom_all or settings.selected_custom_categories:
        # Custom on its own (nothing else ticked) plays only custom questions; otherwise they are mixed in.
        custom = "include" if settings.selected_categories else "only"
        if not settings.custom_all:
            custom_subcategories = sorted(settings.selected_custom_categories)
    if settings.selected_categories != set(CATEGORIES):
        subcategories = [c for c in settings.selected_categories if c not in ALL_ALT_SUBCATEGORIES] or None
        alt_subcategories = [c for c in settings.selected_categories if c in ALL_ALT_SUBCATEGORIES] or None
    if settings.selected_difficulties != set(DIFFICULTIES):
        difficulties = [DIFFICULTIES[d] for d in settings.selected_difficulties]
    return QuestionFilters(subcategories, alt_subcategories, difficulties, custom, custom_subcategories,
                           exclude_custom_ids)


def _round_header(tossup) -> str:
    """The message sent just before the first clue that says a hand-written question is coming, and its category."""
    if not getattr(tossup, "custom", False):
        return ""
    category = getattr(tossup, "category", None)
    return f"📝 Custom question\nCategory: {category}" if category else "📝 Custom question"


async def _fetch_tossup(exclude_custom_ids=None):
    return await question_source.random_tossup(_build_filters(exclude_custom_ids))


# Session keys: an ordinary question is its text; a custom one is a ("custom_...", value) tuple.
def _session_keys(tossup):
    if not getattr(tossup, "custom", False):
        yield tossup.question_sanitized
        return
    yield ("custom_question", tossup.question_sanitized)
    if getattr(tossup, "id", None):
        yield ("custom_id", tossup.id)
    primary_answer = tossup.answer_sanitized.partition("[")[0]
    yield ("custom_answer", "".join(c for c in primary_answer.casefold() if c.isalnum()))


def _is_custom_key(key) -> bool:
    return isinstance(key, tuple) and key[0].startswith("custom_")


async def _fetch_fresh_tossup(seen: set):
    """
    Draw a question this session has not had; returns (tossup, the session's seen keys).

    Custom repeats are avoided by the backend, which is sent the ids already played; the answer
    check here catches a reworded question with an answer already asked. The backend repeats a
    custom question only once every one it could draw has been played: that starts the custom
    questions over, so the returned keys drop the custom ones.

    Ordinary questions have no such server-side exclusion, so a small category selection can run
    out of fresh draws before QUESTION_FETCH_ATTEMPTS is reached. When that happens, getting a
    question out matters more than avoiding a repeat: the last draw is accepted and the ordinary
    keys are dropped from `seen` (a new cycle), same as the custom ones above.
    """
    rejected = []  # custom ids drawn and turned down during this call
    tossup = None
    for _ in range(QUESTION_FETCH_ATTEMPTS):
        played = [key[1] for key in seen if _is_custom_key(key) and key[0] == "custom_id"]
        tossup = await _fetch_tossup(played + rejected)
        if getattr(tossup, "custom", False) and ("custom_id", getattr(tossup, "id", None)) in seen:
            seen = {key for key in seen if not _is_custom_key(key)}
        if not any(key in seen for key in _session_keys(tossup)):
            return tossup, seen
        if getattr(tossup, "custom", False) and getattr(tossup, "id", None):
            rejected.append(tossup.id)
    return tossup, {key for key in seen if _is_custom_key(key)}


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
    header = current_round["header"]
    total = len(sentences)

    if header:
        announce(header)
    for i, sentence in enumerate(sentences):
        if current_round["event"].is_set():
            break
        current_round["hourglasses"] = total - i
        announce(f"{'🎯' * (i + 1)}\n{sentence}\n{'⏳' * (total - i)}")
        current_round["event"].wait(settings.sentence_interval)

    if not current_round["event"].is_set():
        current_round["event"].wait(settings.answer_wait)

    if current_round["winners"]:
        time.sleep(SIMULTANEOUS_ANSWER_GRACE)

    with checks_settled:
        current_round["active"] = False
        # Answers sent at the same moment as the first correct one are still
        # being checked; score them before announcing the result.
        if not checks_settled.wait_for(lambda: current_round["pending_checks"] == 0, PENDING_CHECK_TIMEOUT):
            logging.warning("Closing round with %d answer check(s) still pending", current_round["pending_checks"])
    current_round["ended_at"] = time.monotonic()
    announce(_round_end_text() + end_hint + (RATING_PROMPT if current_round["rating"] else ""))
    announce(format_scoreboard())
    _record_play()


def _record_play() -> None:
    """Tell the backend a custom question was played, and how many clues were left when it was answered."""
    rating = current_round["rating"]
    if rating is None:
        return
    try:
        asyncio.run(question_source.record_play(rating[0], current_round["clues_left_when_answered"]))
    except Exception as e:
        logging.error("Recording the play failed: %s", e)


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
    NEEDS_RATING = "needs_rating"            # the last custom question is still unrated within its grace period


def _rating_still_required() -> bool:
    """
    True while the round that just finished was a ratable custom question, nobody has voted on it
    yet, and RATING_GRACE_PERIOD hasn't passed since it ended. Never true while a round is active:
    that case is round_lock's job (StartResult.BUSY), not this one's.
    """
    if current_round["active"]:
        return False
    rating = current_round["rating"]
    if rating is None:
        return False
    _, votes = rating
    if votes:
        return False
    ended_at = current_round["ended_at"]
    return ended_at is not None and time.monotonic() - ended_at < RATING_GRACE_PERIOD


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
        and not getattr(judgement, "final", False)
        and is_lenient_spelling_match(current_round["answerline"], given)
    ):
        with scores_lock:
            if user_id in current_round["winner_ids"]:
                return
            points = _points_for_correct()
            if not current_round["winners"]:
                # hourglasses counts the clue on screen, so the ones still to come are one fewer.
                current_round["clues_left_when_answered"] = current_round["hourglasses"] - 1
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


def submit_rating(user_id: int, rating: str) -> None:
    """
    Record a player's /good or /bad on the custom question that was just played.

    Votes are open from the round's end until the next round starts, and only for custom questions.
    Each player has one vote per round: repeating it is ignored, and the other one replaces it (the
    backend moves the vote). A vote the backend fails to record does not count, so it can be retried.
    Blocks while the vote is sent, so callers run it on a worker thread.
    """
    if rating not in RATINGS:
        return
    with ratings_lock:
        target = current_round["rating"]
        if current_round["active"] or target is None:
            return
        question_id, votes = target
        previous = votes.get(user_id)
        if previous == rating:
            return
        try:
            asyncio.run(question_source.rate_tossup(question_id, rating, previous))
        except Exception as e:
            logging.error("Rating failed: %s", e)
            return
        votes[user_id] = rating


def start_round(announce: Callable[[str], None], end_hint: str, session: dict) -> StartResult:
    """
    Fetch a question and run the round on a background thread.

    `session` is per-chat storage that persists between calls; it remembers
    which tossups the chat has seen. `end_hint` is appended to the round-end
    message (e.g. how to start the next round).
    """
    if _rating_still_required():
        return StartResult.NEEDS_RATING

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
            tossup, seen = asyncio.run(asyncio.wait_for(
                _fetch_fresh_tossup(seen), timeout=QUESTION_FETCH_TIMEOUT,
            ))
        except Exception as e:
            logging.error("Failed to fetch question: %s", e)
            return StartResult.FETCH_FAILED

        sentences = split_sentences(tossup.question_sanitized)
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
            "header": _round_header(tossup),
            "hourglasses": len(sentences),
            "scoring_modes": frozenset(settings.scoring_modes),
            "medalists": medalists,
            "pending_checks": 0,
            "clues_left_when_answered": None,
            "rating": (tossup.id, {}) if getattr(tossup, "custom", False) and getattr(tossup, "id", None) else None,
        })
        current_round["event"].clear()
        logging.info("Answer: %s", tossup.answer_sanitized)

        threading.Thread(target=_run_round, args=(announce, end_hint), daemon=True).start()
        handed_off = True
        seen.update(_session_keys(tossup))
        session["seen_tossups"] = seen
        session["last_next"] = now
        return StartResult.STARTED
    finally:
        if not handed_off:
            with scores_lock:
                current_round["active"] = False
            round_lock.release()
