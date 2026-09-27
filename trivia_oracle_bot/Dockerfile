# Telegram bot. Build from the repository root:
#   docker build -f trivia_oracle_bot/Dockerfile -t trivia-oracle-bot .
# python-telegram-bot 13.7 needs Python 3.11 or older.
FROM python:3.11-slim

WORKDIR /app

COPY trivia_oracle_bot/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY trivia_oracle_bot/ ./trivia_oracle_bot/

# Scores are written to /app/data/scores.md — mount a volume here to keep them.
VOLUME /app/data

# Secrets are passed at runtime, never baked into the image (env vars, or a
# mounted /app/secrets.json). BACKEND_URL points at the question backend.
CMD ["python", "-m", "trivia_oracle_bot"]
