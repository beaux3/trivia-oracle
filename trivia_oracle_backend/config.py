import os

# Repository root (parent of this package). In Docker this is /app.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where tossups come from: "local" (the default; QUESTIONS_DB, filled by
# `python -m trivia_oracle_backend.local.sync`) or "api" (qbreader.org, live).
QUESTION_BACKEND = (os.environ.get("QUESTION_BACKEND") or "local").lower()
QUESTIONS_DB = os.environ.get("QUESTIONS_DB") or os.path.join(ROOT_DIR, "data", "questions.db")
# Separate database for hand-written questions, same schema (filled by `python -m trivia_oracle_backend.custom.add`).
CUSTOM_QUESTIONS_DB = os.environ.get("CUSTOM_QUESTIONS_DB") or os.path.join(ROOT_DIR, "data", "custom_questions.db")

HOST = os.environ.get("HOST") or "0.0.0.0"
PORT = int(os.environ.get("PORT") or 8080)
