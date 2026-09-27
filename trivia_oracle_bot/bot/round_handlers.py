"""Telegram handlers for playing rounds: /next and free-text answers."""
from ..game import round as game_round
from ..game.round import StartResult

_START_FAILURE_TEXT = {
    StartResult.FETCH_FAILED: "Failed to fetch a question. Try /next again.",
    StartResult.NO_FRESH_QUESTION: "Could not find a new question. Try /next again.",
}


def start_round(update, context) -> None:
    """/next handler."""
    bot = context.bot
    chat_id = update.effective_chat.id

    def announce(text: str) -> None:
        bot.send_message(chat_id=chat_id, text=text)

    result = game_round.start_round(
        announce,
        end_hint=f"\n\nNext question: /next@{bot.username}",
        session=context.chat_data,
    )
    if result in _START_FAILURE_TEXT:
        announce(_START_FAILURE_TEXT[result])


def handle_round_answer(update, context) -> None:
    """Runs on a dispatcher worker thread (run_async) so simultaneous answers are checked in parallel."""
    user = update.effective_user

    def reply_prompt(prompt: str) -> None:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🤔 {user.first_name}, Prompt on: {prompt}",
            reply_to_message_id=update.message.message_id,
        )

    game_round.submit_answer(user.id, user.first_name, update.message.text, reply_prompt)
