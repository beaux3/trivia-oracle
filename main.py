import asyncio
import logging
import re
import sys
import time
from telegram.error import Conflict
from telegram.ext import Updater, CommandHandler
from qbreader.asynchronous import Async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TOKEN = "8690521877:***REMOVED***"

SENTENCE_INTERVAL = 2  # seconds between each sentence


async def fetch_tossup():
    async with await Async.create() as qb:
        tossups = await qb.random_tossup(number=1)
        return tossups[0]


def next_question(update, context):
    try:
        tossup = asyncio.run(fetch_tossup())
    except Exception as e:
        update.message.reply_text(f"Failed to fetch question: {e}")
        return

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', tossup.question_sanitized) if s.strip()]
    for sentence in sentences:
        context.bot.send_message(chat_id=update.effective_chat.id, text=sentence)
        time.sleep(SENTENCE_INTERVAL)


def error_handler(update, context):
    if isinstance(context.error, Conflict):
        logging.error("Another bot instance is already running. Shutting down.")
        sys.exit(1)
    logging.error("Update %s caused error: %s", update, context.error)


def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("next", next_question))
    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    logging.info("TriviaOracleBot is running...")
    updater.idle()


if __name__ == "__main__":
    main()
