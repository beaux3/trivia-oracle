# Question backend service. Build from the repository root:
#   docker build -f trivia_oracle_backend/Dockerfile -t trivia-oracle-backend .
FROM python:3.11-slim

WORKDIR /app

COPY trivia_oracle_backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY trivia_oracle_backend/ ./trivia_oracle_backend/

# The question database lives at /app/data/questions.db — mount a volume here.
# Build it yourself with:
#   docker compose run --rm backend python -m trivia_oracle_backend.local.sync
VOLUME /app/data

ENV QUESTION_BACKEND=api
EXPOSE 8080
CMD ["python", "-m", "trivia_oracle_backend"]
