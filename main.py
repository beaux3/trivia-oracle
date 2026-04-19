import asyncio
import logging
import re
import sys
import threading
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackQueryHandler
from qbreader.asynchronous import Async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TOKEN = "8690521877:***REMOVED***"

SENTENCE_INTERVAL = 2   # seconds between each sentence
ANSWER_WAIT = 10        # seconds to wait for answers after the last sentence

SELECT_OPTION, SELECT_TIME_FIELD, INPUT_VALUE = range(3)

current_round = {
    "active": False,
    "answer_sanitized": None,
    "answerline": None,
    "winner": None,
    "event": threading.Event(),
}
round_lock = threading.Lock()


async def fetch_round_question():
    async with await Async.create() as qb:
        tossups = await qb.random_tossup(number=1)
        return tossups[0]


async def check_round_answer_async(answerline, given_answer):
    async with await Async.create() as qb:
        return await qb.check_answer(answerline, given_answer)


def handle_round_answer(update, _context):
    if not current_round["active"]:
        return

    given = update.message.text.strip()
    username = update.effective_user.first_name
    try:
        judgement = asyncio.run(check_round_answer_async(current_round["answerline"], given))
    except Exception as e:
        logging.error("Answer check API call failed: %s", e)
        return

    if judgement.directive == "accept":
        current_round["winner"] = username
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

    if current_round["winner"]:
        bot.send_message(
            chat_id=chat_id,
            text=f"✅✅✅ [ROUND END] ✅✅✅\n Congrats {current_round['winner']} answered correctly!\n\n Answer: {current_round['answer_sanitized']}"
        )
    else:
        bot.send_message(
            chat_id=chat_id,
            text=f"❌❌❌ [ROUND END] ❌❌❌\n Sad to say, nobody answered correctly.\n\n The answer is actually: {current_round['answer_sanitized']}"
        )

    round_lock.release()


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
    current_round["winner"] = None
    current_round["event"].clear()
    current_round["sentences"] = [s.strip() for s in re.split(r'(?<=[.!?])\s+', tossup.question_sanitized) if s.strip()]

    logging.info("Answer: %s", tossup.answer_sanitized)

    thread = threading.Thread(target=run_round, args=(context.bot, update.effective_chat.id), daemon=True)
    thread.start()


def configure(update, context):
    keyboard = [
        [InlineKeyboardButton("⏱ Time", callback_data="time")],
        [InlineKeyboardButton("📚 Category", callback_data="category")],
    ]
    update.message.reply_text("What would you like to configure?", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_OPTION


def configure_select_option(update, context):
    query = update.callback_query
    query.answer()

    if query.data == "time":
        keyboard = [
            [InlineKeyboardButton(f"Sentence Interval (current: {SENTENCE_INTERVAL}s)", callback_data="sentence_interval")],
            [InlineKeyboardButton(f"Answer Wait (current: {ANSWER_WAIT}s)", callback_data="answer_wait")],
        ]
        query.edit_message_text("Which time setting?", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECT_TIME_FIELD
    else:
        query.edit_message_text("Category configuration coming soon!")
        return ConversationHandler.END


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


def error_handler(update, context):
    if isinstance(context.error, Conflict):
        logging.error("Another bot instance is already running. Shutting down.")
        sys.exit(1)
    logging.error("Update %s caused error: %s", update, context.error)


def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("next", start_round))
    dispatcher.add_handler(ConversationHandler(
        entry_points=[CommandHandler("configure", configure)],
        states={
            SELECT_OPTION: [CallbackQueryHandler(configure_select_option)],
            SELECT_TIME_FIELD: [CallbackQueryHandler(configure_select_time_field)],
            INPUT_VALUE: [MessageHandler(Filters.text & ~Filters.command, configure_input_value)],
        },
        fallbacks=[],
    ))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_round_answer))
    dispatcher.add_error_handler(error_handler)

    updater.start_polling(allowed_updates=["message", "callback_query"])
    logging.info("TriviaOracleBot is running...")
    updater.idle()


if __name__ == "__main__":
    main()
