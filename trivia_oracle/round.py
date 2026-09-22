import asyncio
import logging
import re
import threading

from qbreader.asynchronous import Async

from .config import ALL_ALT_SUBCATEGORIES, CATEGORIES, DIFFICULTIES, POINTS_PER_CORRECT, POINTS_PER_WRONG
from .scores import format_scoreboard, save_scores, scores, scores_lock
from .settings import settings

# ── Round state ───────────────────────────────────────────────────────────────

current_round: dict = {
    "active": False,
    "answer_sanitized": None,
    "answerline": None,
    "winners": [],       # list of first-name strings for everyone who answered correctly
    "penalties": {},     # {first_name: total_points_deducted} for wrong answers this round
    "sentences": [],
    "event": threading.Event(),
}
round_lock = threading.Lock()  # held for the duration of a round; prevents overlapping rounds


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_api_filters() -> tuple:
    """
    Split settings.selected_categories into the two qbreader API parameters.

    Returns (subcategories, alt_subcategories) — either can be None (= no filter).
    When all categories are selected we return (None, None) to avoid sending a
    redundant filter and to stay within URL-length limits.
    """
    if settings.selected_categories == set(CATEGORIES):
        return None, None

    subcategories = [c for c in settings.selected_categories if c not in ALL_ALT_SUBCATEGORIES] or None
    alt_subcategories = [c for c in settings.selected_categories if c in ALL_ALT_SUBCATEGORIES] or None
    return subcategories, alt_subcategories


async def _fetch_tossup():
    subcategories, alt_subcategories = _build_api_filters()
    difficulties = (
        [DIFFICULTIES[d] for d in settings.selected_difficulties]
        if settings.selected_difficulties != set(DIFFICULTIES)
        else None
    )
    async with await Async.create() as qb:
        tossups = await qb.random_tossup(
            number=1,
            subcategories=subcategories,
            alternate_subcategories=alt_subcategories,
            difficulties=difficulties,
        )
    return tossups[0]


async def _check_answer(answerline: str, given: str):
    async with await Async.create() as qb:
        return await qb.check_answer(answerline, given)


# ── Round execution ───────────────────────────────────────────────────────────

def _run_round(bot, chat_id: int) -> None:
    sentences = current_round["sentences"]
    total = len(sentences)

    for i, sentence in enumerate(sentences):
        if current_round["event"].is_set():
            break
        bot.send_message(
            chat_id=chat_id,
            text=f"{'🎯' * (i + 1)}\n{sentence}\n{'⏳' * (total - i)}",
        )
        current_round["event"].wait(settings.sentence_interval)

    if not current_round["event"].is_set():
        current_round["event"].wait(settings.answer_wait)

    current_round["active"] = False
    _send_round_end(bot, chat_id)
    bot.send_message(chat_id=chat_id, text=format_scoreboard())
    round_lock.release()


def _send_round_end(bot, chat_id: int) -> None:
    next_prompt = f"\n\nNext question: /next@{bot.username}"
    winners = current_round["winners"]
    penalties = current_round["penalties"]

    if winners:
        if len(winners) == 1:
            congrats = f"Congrats {winners[0]} answered correctly!"
        else:
            names = ", ".join(winners[:-1]) + f" & {winners[-1]}"
            congrats = f"Congrats {names} all answered correctly!"
        result = f"✅✅✅ [ROUND END] ✅✅✅\n {congrats}\n\n Answer: {current_round['answer_sanitized']}"
    else:
        result = f"❌❌❌ [ROUND END] ❌❌❌\n Sad to say, nobody answered correctly.\n\n The answer is actually: {current_round['answer_sanitized']}"

    if penalties:
        penalty_lines = "\n".join(f"  -{pts} pts — {name}" for name, pts in sorted(penalties.items()))
        result += f"\n\n❌ Wrong answer deductions:\n{penalty_lines}"

    result += next_prompt
    bot.send_message(chat_id=chat_id, text=result)


# ── Public Telegram handler functions ─────────────────────────────────────────

def handle_round_answer(update, _context) -> None:
    if not current_round["active"]:
        return

    given = update.message.text.strip()
    user = update.effective_user

    with scores_lock:
        if user.id not in scores:
            scores[user.id] = {"name": user.first_name, "score": 0}
        else:
            scores[user.id]["name"] = user.first_name

    try:
        judgement = asyncio.run(_check_answer(current_round["answerline"], given))
    except Exception as e:
        logging.error("Answer check failed: %s", e)
        return

    if judgement.directive == "accept":
        with scores_lock:
            scores[user.id]["score"] += POINTS_PER_CORRECT
            save_scores()
            current_round["winners"].append(user.first_name)
        current_round["event"].set()

    elif judgement.directive == "reject":
        with scores_lock:
            scores[user.id]["score"] -= POINTS_PER_WRONG
            save_scores()
            name = user.first_name
            current_round["penalties"][name] = current_round["penalties"].get(name, 0) + POINTS_PER_WRONG


def start_round(update, context) -> None:
    if not round_lock.acquire(blocking=False):
        return

    try:
        tossup = asyncio.run(_fetch_tossup())
    except Exception as e:
        logging.error("Failed to fetch question: %s", e)
        context.bot.send_message(chat_id=update.effective_chat.id, text="Failed to fetch a question. Try /next again.")
        round_lock.release()
        return

    current_round.update({
        "active": True,
        "answer_sanitized": tossup.answer_sanitized,
        "answerline": tossup.answer,
        "winners": [],
        "penalties": {},
        "sentences": [s.strip() for s in re.split(r'(?<=[.!?])\s+', tossup.question_sanitized) if s.strip()],
    })
    current_round["event"].clear()
    logging.info("Answer: %s", tossup.answer_sanitized)

    threading.Thread(
        target=_run_round,
        args=(context.bot, update.effective_chat.id),
        daemon=True,
    ).start()
