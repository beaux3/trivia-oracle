import logging
import os

from aiohttp import web

from . import LocalAnswerJudge, LocalQuestionSource, QbreaderAnswerJudge, QbreaderQuestionSource
from .config import CUSTOM_QUESTIONS_DB, HOST, PORT, QUESTION_BACKEND, QUESTIONS_DB
from .server import build_app


def main() -> None:
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
    if QUESTION_BACKEND == "api":
        source, judge = QbreaderQuestionSource(), QbreaderAnswerJudge()
    elif QUESTION_BACKEND == "local":
        if not os.path.exists(QUESTIONS_DB):
            raise SystemExit(
                f"QUESTION_BACKEND is local but {QUESTIONS_DB} does not exist. "
                "Build it with `python -m trivia_oracle_backend.local.sync`."
            )
        source, judge = LocalQuestionSource(QUESTIONS_DB), LocalAnswerJudge()
    else:
        raise SystemExit(f'QUESTION_BACKEND must be "api" or "local", not "{QUESTION_BACKEND}".')
    # Local mode never touches the network: questions come from the database, answers from LocalAnswerJudge.
    # Custom questions come from their own database in either mode. It is opened per request, so it may be
    # created or refilled (custom.add) while the service runs, and a missing file only fails custom draws.
    custom_source = LocalQuestionSource(CUSTOM_QUESTIONS_DB)
    web.run_app(build_app(source, judge, QUESTION_BACKEND, custom_source=custom_source), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
