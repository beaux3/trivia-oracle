import os

# Repository root (parent of this package). In Docker this is /app.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where tossups come from: "api" (qbreader.org, the default) or "local"
# (QUESTIONS_DB, filled by `python -m trivia_oracle_backend.local.sync`).
QUESTION_BACKEND = (os.environ.get("QUESTION_BACKEND") or "api").lower()
QUESTIONS_DB = os.environ.get("QUESTIONS_DB") or os.path.join(ROOT_DIR, "data", "questions.db")

HOST = os.environ.get("HOST") or "0.0.0.0"
PORT = int(os.environ.get("PORT") or 8080)
