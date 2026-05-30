import asyncio
import logging
import os
import re
import sys
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackQueryHandler
from qbreader.asynchronous import Async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TOKEN = "8690521877:***REMOVED***"

SENTENCE_INTERVAL = 5   # seconds between each sentence
ANSWER_WAIT = 10        # seconds to wait for answers after the last sentence

SELECT_OPTION, SELECT_TIME_FIELD, INPUT_VALUE, SELECT_CATEGORIES, SELECT_DIFFICULTIES, SELECT_ADMIN = range(6)

CATEGORIES = [
    # Literature
    "American Literature", "British Literature", "Classical Literature",
    "European Literature", "World Literature", "Other Literature",
    "Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature",
    # History
    "American History", "Ancient History", "European History",
    "World History", "Other History",
    # Science
    "Biology", "Chemistry", "Physics", "Other Science",
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
    # Fine Arts
    "Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts",
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
    # Religion
    "Religion", "Beliefs", "Practices",
    # Standalone
    "Mythology", "Philosophy", "Current Events", "Geography", "Other Academic",
    # Social Science
    "Social Science", "Anthropology", "Economics", "Linguistics", "Psychology", "Sociology", "Other Social Science",
    # Pop Culture
    "Movies", "Music", "Sports", "Television", "Video Games", "Other Pop Culture",
]

# qbreader AlternateSubcategory values — passed via alternate_subcategories= parameter
ALL_ALT_SUBCATEGORIES = {
    "Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature",
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
    "Beliefs", "Practices",
    "Anthropology", "Economics", "Linguistics", "Psychology", "Sociology", "Other Social Science",
}

ALL_SCIENCE = {
    "Biology", "Chemistry", "Physics", "Other Science",
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
}

ALL_ARTS = {
    "Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts",
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
}

selected_categories = set(CATEGORIES)  # all enabled by default

DIFFICULTIES = {
    "Unrated (0)":       "0",
    "Middle School (1)": "1",
    "HS Easy (2)":       "2",
    "HS Regular (3)":    "3",
    "HS Hard (4)":       "4",
    "HS Nationals (5)":  "5",
    "College ⭐ (6)":    "6",
    "College ⭐⭐ (7)":  "7",
    "College ⭐⭐⭐ (8)": "8",
    "College ⭐⭐⭐⭐ (9)": "9",
    "Open (10)":          "10",
}

selected_difficulties = {"HS Easy (2)", "HS Regular (3)"}  # default difficulty

SCORES_FILE = "/app/scores.md"
POINTS_PER_CORRECT = 10

scores = {}       # {user_id: {"name": str, "score": int}}
scores_lock = threading.Lock()


def load_scores():
    if not os.path.exists(SCORES_FILE):
        return
    with open(SCORES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or line.startswith("| Rank") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) == 4:
                try:
                    _, name, score, user_id = parts
                    scores[int(user_id)] = {"name": name, "score": int(score)}
                except ValueError:
                    continue


def save_scores():
    lines = [
        "# TriviaOracleBot Scoreboard\n",
        "| Rank | Name | Score | Telegram ID |\n",
        "|------|------|-------|-------------|\n",
    ]
    for rank, (uid, player) in enumerate(
        sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True), start=1
    ):
        lines.append(f"| {rank} | {player['name']} | {player['score']} | {uid} |\n")
    with open(SCORES_FILE, "w") as f:
        f.writelines(lines)


def format_scoreboard():
    if not scores:
        return "📊 Scoreboard\n\nNo scores yet!"
    lines = ["📊 Scoreboard\n"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, (_, player) in enumerate(
        sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True), start=1
    ):
        medal = medals.get(rank, f"{rank}.")
        lines.append(f"{medal} {player['name']} — {player['score']} pts")
    return "\n".join(lines)


current_round = {
    "active": False,
    "answer_sanitized": None,
    "answerline": None,
    "winners": [],
    "event": threading.Event(),
}
round_lock = threading.Lock()


async def fetch_round_question():
    difficulties = [DIFFICULTIES[d] for d in selected_difficulties] if selected_difficulties != set(DIFFICULTIES) else None

    if selected_categories == set(CATEGORIES):
        subcategories = None
        alt_subcategories = None
    else:
        subcategories = [c for c in selected_categories if c not in ALL_ALT_SUBCATEGORIES] or None
        alt_subcategories = [c for c in selected_categories if c in ALL_ALT_SUBCATEGORIES] or None

    async with await Async.create() as qb:
        tossups = await qb.random_tossup(
            number=1,
            subcategories=subcategories,
            alternate_subcategories=alt_subcategories,
            difficulties=difficulties,
        )
        return tossups[0]


async def check_round_answer_async(answerline, given_answer):
    async with await Async.create() as qb:
        return await qb.check_answer(answerline, given_answer)


def handle_round_answer(update, _context):
    if not current_round["active"]:
        return

    given = update.message.text.strip()
    user = update.effective_user
    username = user.first_name
    user_id = user.id

    with scores_lock:
        if user_id not in scores:
            scores[user_id] = {"name": username, "score": 0}
        else:
            scores[user_id]["name"] = username  # keep name up to date

    try:
        judgement = asyncio.run(check_round_answer_async(current_round["answerline"], given))
    except Exception as e:
        logging.error("Answer check API call failed: %s", e)
        return

    if judgement.directive == "accept":
        with scores_lock:
            scores[user_id]["score"] += POINTS_PER_CORRECT
            save_scores()
            current_round["winners"].append(username)
        current_round["event"].set()


def run_round(bot, chat_id):
    sentences = current_round["sentences"]

    total = len(sentences)
    for i, sentence in enumerate(sentences):
        if current_round["event"].is_set():
            break
        prefix = "🎯" * (i + 1)
        hourglasses = "⏳" * (total - i)
        text = f"{prefix}\n{sentence}\n{hourglasses}"
        bot.send_message(chat_id=chat_id, text=text)
        current_round["event"].wait(SENTENCE_INTERVAL)

    if not current_round["event"].is_set():
        current_round["event"].wait(ANSWER_WAIT)

    current_round["active"] = False

    next_prompt = "\n\nNext question: /next@TriviaOracleBot"
    winners = current_round["winners"]
    if winners:
        if len(winners) == 1:
            names = winners[0]
            congrats = f"Congrats {names} answered correctly!"
        else:
            names = ", ".join(winners[:-1]) + f" & {winners[-1]}"
            congrats = f"Congrats {names} all answered correctly!"
        bot.send_message(
            chat_id=chat_id,
            text=f"✅✅✅ [ROUND END] ✅✅✅\n {congrats}\n\n Answer: {current_round['answer_sanitized']}{next_prompt}"
        )
    else:
        bot.send_message(
            chat_id=chat_id,
            text=f"❌❌❌ [ROUND END] ❌❌❌\n Sad to say, nobody answered correctly.\n\n The answer is actually: {current_round['answer_sanitized']}{next_prompt}"
        )

    bot.send_message(chat_id=chat_id, text=format_scoreboard())
    round_lock.release()


def show_scores(update, _context):
    update.message.reply_text(format_scoreboard())


def start_round(update, context):
    if not round_lock.acquire(blocking=False):
        return

    try:
        tossup = asyncio.run(fetch_round_question())
    except Exception as e:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Failed to fetch question: {e}")
        round_lock.release()
        return

    current_round["active"] = True
    current_round["answer_sanitized"] = tossup.answer_sanitized
    current_round["answerline"] = tossup.answer
    current_round["winners"] = []
    current_round["event"].clear()
    current_round["sentences"] = [s.strip() for s in re.split(r'(?<=[.!?])\s+', tossup.question_sanitized) if s.strip()]

    logging.info("Answer: %s", tossup.answer_sanitized)

    thread = threading.Thread(target=run_round, args=(context.bot, update.effective_chat.id), daemon=True)
    thread.start()


def _build_difficulty_keyboard():
    rows = []
    diff_names = list(DIFFICULTIES.keys())
    for i in range(0, len(diff_names), 2):
        row = []
        for name in diff_names[i:i + 2]:
            mark = "✅" if name in selected_difficulties else "☐"
            row.append(InlineKeyboardButton(f"{mark} {name}", callback_data=f"diff:{name}"))
        rows.append(row)
    all_on = selected_difficulties == set(DIFFICULTIES)
    rows.append([InlineKeyboardButton("☐ Deselect All" if all_on else "✅ Select All", callback_data="diff_toggle_all")])
    rows.append([InlineKeyboardButton("💾 Save", callback_data="diff_save")])
    return InlineKeyboardMarkup(rows)


def _build_category_keyboard():
    rows = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i + 2]:
            mark = "✅" if cat in selected_categories else "☐"
            suffix = " 🔬" if cat in ALL_SCIENCE else " 🎭" if cat in ALL_ARTS else ""
            row.append(InlineKeyboardButton(f"{mark} {cat}{suffix}", callback_data=f"cat:{cat}"))
        rows.append(row)
    arts_on = ALL_ARTS.issubset(selected_categories)
    rows.append([InlineKeyboardButton("🎭 ☐ Deselect All Arts 🎭" if arts_on else "🎭 ✅ Select All Arts 🎭", callback_data="cat_toggle_arts")])
    science_on = ALL_SCIENCE.issubset(selected_categories)
    rows.append([InlineKeyboardButton("🔬 ☐ Deselect All Science 🔬" if science_on else "🔬 ✅ Select All Science 🔬", callback_data="cat_toggle_science")])
    all_on = selected_categories == set(CATEGORIES)
    rows.append([InlineKeyboardButton("☐ Deselect All" if all_on else "✅ Select All", callback_data="cat_toggle_all")])
    rows.append([InlineKeyboardButton("💾 Save", callback_data="cat_save")])
    return InlineKeyboardMarkup(rows)


def _build_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Reset All Scores", callback_data="admin_reset")],
    ])


def configure_admin(update, _context):
    query = update.callback_query
    if update.effective_user.username != ADMIN_USERNAME:
        query.answer("⛔ Access denied.", show_alert=True)
        return ConversationHandler.END

    query.answer()

    if query.data == "admin_reset":
        query.edit_message_text(
            "⚠️ Are you sure you want to reset ALL scores? This cannot be undone.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, reset", callback_data="admin_reset_confirm"),
                    InlineKeyboardButton("❌ No, cancel", callback_data="admin_reset_cancel"),
                ]
            ]),
        )
    elif query.data == "admin_reset_confirm":
        with scores_lock:
            scores.clear()
            save_scores()
        query.edit_message_text("✅ All scores have been reset.")
        return ConversationHandler.END
    elif query.data == "admin_reset_cancel":
        query.edit_message_text("🔒 Admin Settings", reply_markup=_build_admin_keyboard())

    return SELECT_ADMIN


def configure(update, context):
    keyboard = [
        [InlineKeyboardButton("⏱ Time", callback_data="time")],
        [InlineKeyboardButton("📚 Categories", callback_data="category")],
        [InlineKeyboardButton("🎯 Difficulty", callback_data="difficulty")],
        [InlineKeyboardButton("👁 View Current Settings", callback_data="view_settings")],
        [InlineKeyboardButton("🔒 Admin Settings", callback_data="admin")],
    ]
    update.message.reply_text("What would you like to configure?", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_OPTION


ADMIN_USERNAME = "terenegade"


def configure_select_option(update, context):
    query = update.callback_query

    if query.data == "admin":
        if update.effective_user.username != ADMIN_USERNAME:
            query.answer("⛔ Access denied.", show_alert=True)
            return SELECT_OPTION
        query.answer()
        query.edit_message_text("🔒 Admin Settings", reply_markup=_build_admin_keyboard())
        return SELECT_ADMIN

    query.answer()

    if query.data == "view_settings":
        cats = "All" if selected_categories == set(CATEGORIES) else ", ".join(sorted(selected_categories))
        diffs = "All" if selected_difficulties == set(DIFFICULTIES) else ", ".join(selected_difficulties)
        text = (
            f"⚙️ Current Settings\n\n"
            f"⏱ Sentence Interval: {SENTENCE_INTERVAL}s\n"
            f"⏱ Answer Wait: {ANSWER_WAIT}s\n\n"
            f"📚 Categories:\n{cats}\n\n"
            f"🎯 Difficulties:\n{diffs}"
        )
        query.edit_message_text(text)
        return ConversationHandler.END

    if query.data == "time":
        keyboard = [
            [InlineKeyboardButton(f"Sentence Interval (current: {SENTENCE_INTERVAL}s)", callback_data="sentence_interval")],
            [InlineKeyboardButton(f"Answer Wait (current: {ANSWER_WAIT}s)", callback_data="answer_wait")],
        ]
        query.edit_message_text("Which time setting?", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECT_TIME_FIELD
    elif query.data == "category":
        active_label = "All categories" if selected_categories == set(CATEGORIES) else f"{len(selected_categories)} selected"
        query.edit_message_text(f"Toggle categories on/off ({active_label}):", reply_markup=_build_category_keyboard())
        return SELECT_CATEGORIES
    else:
        active_label = "All difficulties" if selected_difficulties == set(DIFFICULTIES) else f"{len(selected_difficulties)} selected"
        query.edit_message_text(f"Toggle difficulties on/off ({active_label}):", reply_markup=_build_difficulty_keyboard())
        return SELECT_DIFFICULTIES


def configure_select_time_field(update, context):
    query = update.callback_query
    query.answer()
    context.user_data["field"] = query.data

    if query.data == "sentence_interval":
        query.edit_message_text(f"Enter new Sentence Interval in seconds (current: {SENTENCE_INTERVAL}s):")
    else:
        query.edit_message_text(f"Enter new Answer Wait in seconds (current: {ANSWER_WAIT}s):")

    return INPUT_VALUE


def configure_input_value(update, context):
    global SENTENCE_INTERVAL, ANSWER_WAIT

    try:
        value = float(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("Please enter a valid positive number.")
        return INPUT_VALUE

    field = context.user_data.get("field")
    if field == "sentence_interval":
        SENTENCE_INTERVAL = value
        update.message.reply_text(f"✅ Sentence Interval set to {value}s")
    elif field == "answer_wait":
        ANSWER_WAIT = value
        update.message.reply_text(f"✅ Answer Wait set to {value}s")

    return ConversationHandler.END


def configure_toggle_category(update, context):
    global selected_categories
    query = update.callback_query
    query.answer()

    if query.data == "cat_save":
        if not selected_categories:
            query.answer("⚠️ Select at least one category!", show_alert=True)
            return SELECT_CATEGORIES
        active_label = "All categories" if selected_categories == set(CATEGORIES) else ", ".join(sorted(selected_categories))
        query.edit_message_text(f"✅ Categories saved:\n{active_label}")
        return ConversationHandler.END

    if query.data == "cat_toggle_arts":
        if ALL_ARTS.issubset(selected_categories):
            selected_categories -= ALL_ARTS
        else:
            selected_categories |= ALL_ARTS
    elif query.data == "cat_toggle_science":
        if ALL_SCIENCE.issubset(selected_categories):
            selected_categories -= ALL_SCIENCE
        else:
            selected_categories |= ALL_SCIENCE
    elif query.data == "cat_toggle_all":
        if selected_categories == set(CATEGORIES):
            selected_categories.clear()
        else:
            selected_categories = set(CATEGORIES)
    else:
        cat = query.data[len("cat:"):]
        if cat in selected_categories:
            selected_categories.discard(cat)
        else:
            selected_categories.add(cat)

    active_label = "All categories" if selected_categories == set(CATEGORIES) else f"{len(selected_categories)} selected"
    query.edit_message_reply_markup(reply_markup=_build_category_keyboard())
    return SELECT_CATEGORIES


def configure_toggle_difficulty(update, _context):
    global selected_difficulties
    query = update.callback_query
    query.answer()

    if query.data == "diff_save":
        if not selected_difficulties:
            query.answer("⚠️ Select at least one difficulty!", show_alert=True)
            return SELECT_DIFFICULTIES
        active_label = "All difficulties" if selected_difficulties == set(DIFFICULTIES) else ", ".join(selected_difficulties)
        query.edit_message_text(f"✅ Difficulties saved:\n{active_label}")
        return ConversationHandler.END

    if query.data == "diff_toggle_all":
        if selected_difficulties == set(DIFFICULTIES):
            selected_difficulties.clear()
        else:
            selected_difficulties = set(DIFFICULTIES)
    else:
        name = query.data[len("diff:"):]
        if name in selected_difficulties:
            selected_difficulties.discard(name)
        else:
            selected_difficulties.add(name)

    query.edit_message_reply_markup(reply_markup=_build_difficulty_keyboard())
    return SELECT_DIFFICULTIES


def error_handler(update, context):
    if isinstance(context.error, Conflict):
        logging.error("Another bot instance is already running. Shutting down.")
        sys.exit(1)
    logging.error("Update %s caused error: %s", update, context.error)


def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("next", start_round))
    dispatcher.add_handler(CommandHandler("scores", show_scores))
    dispatcher.add_handler(ConversationHandler(
        entry_points=[CommandHandler("configure", configure)],
        states={
            SELECT_OPTION: [CallbackQueryHandler(configure_select_option)],
            SELECT_TIME_FIELD: [CallbackQueryHandler(configure_select_time_field)],
            INPUT_VALUE: [MessageHandler(Filters.text & ~Filters.command, configure_input_value)],
            SELECT_CATEGORIES: [CallbackQueryHandler(configure_toggle_category)],
            SELECT_DIFFICULTIES: [CallbackQueryHandler(configure_toggle_difficulty)],
            SELECT_ADMIN: [CallbackQueryHandler(configure_admin)],
        },
        fallbacks=[],
    ))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_round_answer))
    dispatcher.add_error_handler(error_handler)

    load_scores()
    updater.start_polling(allowed_updates=["message", "callback_query"])
    logging.info("TriviaOracleBot is running...")
    updater.idle()


if __name__ == "__main__":
    main()
