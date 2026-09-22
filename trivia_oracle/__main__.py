import logging

from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ConversationHandler,
    Filters, MessageHandler, Updater,
)

from .config import (
    TOKEN,
    SELECT_OPTION, SELECT_TIME_FIELD, INPUT_VALUE,
    SELECT_CATEGORIES, SELECT_DIFFICULTIES, SELECT_ADMIN,
)
from .handlers import (
    configure,
    configure_admin,
    configure_input_value,
    configure_select_option,
    configure_select_time_field,
    configure_toggle_category,
    configure_toggle_difficulty,
    error_handler,
    show_scores,
)
from .round import handle_round_answer, start_round
from .scores import load_scores

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("next", start_round))
    dp.add_handler(CommandHandler("scores", show_scores))
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("configure", configure)],
        states={
            SELECT_OPTION:       [CallbackQueryHandler(configure_select_option)],
            SELECT_TIME_FIELD:   [CallbackQueryHandler(configure_select_time_field)],
            INPUT_VALUE:         [MessageHandler(Filters.text & ~Filters.command, configure_input_value)],
            SELECT_CATEGORIES:   [CallbackQueryHandler(configure_toggle_category)],
            SELECT_DIFFICULTIES: [CallbackQueryHandler(configure_toggle_difficulty)],
            SELECT_ADMIN:        [CallbackQueryHandler(configure_admin)],
        },
        fallbacks=[],
    ))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_round_answer))
    dp.add_error_handler(error_handler)

    load_scores()
    updater.start_polling(allowed_updates=["message", "callback_query"])
    logging.info("TriviaOracleBot is running...")
    updater.idle()


if __name__ == "__main__":
    main()
