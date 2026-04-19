import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python-module"))

from telegram.ext import Updater, CommandHandler
from qbreader.asynchronous import Async

TOKEN = "8690521877:***REMOVED***"


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

    text = (
        f"Category: {tossup.category} | {tossup.subcategory} | Difficulty: {tossup.difficulty}\n"
        f"Set: {tossup.set.name}\n\n"
        f"{tossup.question_sanitized}\n\n"
        f"ANSWER: {tossup.answer_sanitized}"
    )
    update.message.reply_text(text)


def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("next", next_question))

    updater.start_polling()
    print("TriviaOracleBot is running...")
    updater.idle()


if __name__ == "__main__":
    main()
