FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY vendor/ ./vendor/
COPY trivia_oracle/ ./trivia_oracle/

# Scores are written to /app/data/scores.md — mount a volume here to keep them.
VOLUME /app/data

# Secrets are passed at runtime, never baked into the image:
#   docker run -e TELEGRAM_TOKEN=... -e ADMIN_USERNAME=... trivia-oracle
CMD ["python", "-m", "trivia_oracle"]
