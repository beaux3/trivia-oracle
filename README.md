# TriviaOracleBot 🎯

A Telegram group trivia bot built just for fun by **Terence Chew**. Questions are pulled live from the [qbreader](https://www.qbreader.org) quizbowl database and revealed sentence by sentence — buzz in by typing your answer before the clue runs out.

100% vibe coded. No regrets.

---

## Features

- Quizbowl tossups across dozens of categories (Literature, History, Science, Arts, Pop Culture, and more)
- Clues revealed one sentence at a time, answers judged by qbreader's answer checker
- Configurable categories, difficulty levels, timing, and scoring mode via `/configure`
- Combinable scoring modes (see [Scoring](#scoring))
- Persistent scoreboard across restarts
- Admin-only score reset

---

## Bot commands

| Command | Description |
|---------|-------------|
| `/next` | Start a new round |
| `/scores` | Show the current scoreboard |
| `/configure` | Configure timing, categories, difficulty, and scoring mode |

During a round, just type your answer in the chat.
Questions won't repeat in the same chat until 30 minutes pass without a successful `/next` starting a question.
This history is kept in memory and clears when the bot restarts.

---

## Scoring

By default every correct answer is worth **+10** and wrong answers cost nothing.
Under `/configure` → **🏆 Scoring Mode**, tick any combination of these modes, then press **💾 Save**:

| Mode | Effect |
|------|--------|
| **Wrong answers -1pt** | Every wrong answer costs 1 point |
| **Hourglass bonus** | A correct answer scores 10 × the ⏳ still showing (answer on ⏳⏳⏳⏳⏳ for 50) |
| **Medals get penalty** | Whoever holds 🥇🥈🥉 when the round starts loses 3 points per wrong answer |

Penalties stack: with both penalty modes on, a medal holder loses 4 points per wrong answer.
Changes take effect from the next round. Everyone who answers correctly gets credited,
even if several people answer at the same time.

---

## Running it yourself

### 1. Create a bot

Talk to [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`, and copy the token it gives you.
Add the bot to your group. For it to see plain-text answers, either make it a group admin or turn
off privacy mode with `/setprivacy` in BotFather.

### 2. Configure it

The bot reads these settings from environment variables, falling back to a local `secrets.json`:

| Setting | Required | Description |
|---------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `ADMIN_USERNAME` | No | Your Telegram username (without `@`). Unlocks **Admin Settings** in `/configure`. If unset, nobody is admin. |
| `SCORES_FILE` | No | Where to store scores. Default: `data/scores.md` |
| `BACKEND_URL` | No | Where the question backend service listens. Default: `http://localhost:8080` (Docker Compose sets it for you) |

The bot is only a frontend: questions and answer checking come from the question backend service
(`trivia_oracle_backend`), which has its own settings, see [Question backend](#question-backend).

For local runs, copy the example file and fill it in (`secrets.json` is gitignored):

```bash
cp secrets.example.json secrets.json
```

### 3a. Run with Docker Compose (recommended)

Two containers, two images: the **bot** (`trivia_oracle_bot/Dockerfile`) and the **question backend**
(`trivia_oracle_backend/Dockerfile`). `docker-compose.yml` builds and connects them. The bot reads
your `secrets.json` (mounted read-only; the backend never sees it) and keeps its scoreboard in `./data`.

```bash
docker compose up -d                          # backend serves questions from qbreader.org's API
QUESTION_BACKEND=local docker compose up -d   # backend serves them from ./data/questions.db
docker compose logs -f bot
```

If the bot exits with `TELEGRAM_TOKEN is not set`, check that `secrets.json` exists next to
`docker-compose.yml`. Only run one bot per token: a second instance will shut itself down.

### 3b. Run with Python

Requires Python 3.9–3.11 (python-telegram-bot 13.x breaks on 3.12+). The Docker images use 3.11.

```bash
pip install -r trivia_oracle_backend/requirements.txt -r trivia_oracle_bot/requirements.txt
python -m trivia_oracle_backend     # terminal 1: question backend on :8080
python -m trivia_oracle_bot         # terminal 2: the bot
```

### Question backend

`trivia_oracle_backend` is a small HTTP service (`/random-tossup`, `/check-answer`, `/health`; see
`trivia_oracle_backend/server.py`) in front of one of two sources, chosen by `QUESTION_BACKEND`:

| `QUESTION_BACKEND` | Questions from |
|--------------------|----------------|
| `api` (default) | qbreader.org, live |
| `local` | `QUESTIONS_DB` (default `data/questions.db`), a SQLite copy of qbreader |

Answers are checked by qbreader's answer checker in both modes, so the backend needs internet
access for now. `HOST` and `PORT` (default `0.0.0.0:8080`) set where it listens. Compose does not
publish the port, so only the bot can reach it.

### Offline questions

Sync is a job you run yourself, when you like. It copies qbreader into the database (about an hour and
~300 MB for all sets; it resumes if interrupted, and a re-run only fetches sets it doesn't have yet):

```bash
python -m trivia_oracle_backend.local.sync              # or with Docker:
docker compose run --rm --no-deps backend python -m trivia_oracle_backend.local.sync
```

Add `--limit 5` or `--sets "2023 ACF Winter"` to try it on a few sets first. Then start the backend
with `QUESTION_BACKEND=local`. The backend reads the file on every request, so a sync can run while
it is up; it only refuses to start if the file does not exist yet.

### Running tests

Each image holds only its own code, so run each side's tests in its own image, mounting `tests/`
(the images leave it out):

```bash
docker build -f trivia_oracle_bot/Dockerfile -t trivia-oracle-bot .
docker run --rm -v "$PWD/tests:/app/tests:ro" trivia-oracle-bot sh -c \
  "python -m unittest discover -s tests/bot -t . && python -m unittest discover -s tests/game -t ."
docker build -f trivia_oracle_backend/Dockerfile -t trivia-oracle-backend .
docker run --rm -v "$PWD/tests:/app/tests:ro" trivia-oracle-backend \
  python -m unittest discover -s tests/backend -t .
```

`tests/contract` checks the two sides agree, so it imports both. Run it from the repo root with both
requirements files installed: `python -m unittest discover -s tests/contract -t .`.
The tests fake Telegram and qbreader, so they need no token or network access.

---

## Project layout

```
trivia_oracle_bot/       Frontend: the Telegram bot (python -m trivia_oracle_bot)
  bot/                Telegram UI: handlers for rounds, /configure menus, keyboards
  game/               Rounds, scoring, settings, lenient spelling (no Telegram code)
  questions.py        HTTP client for the question backend
  Dockerfile, requirements.txt
trivia_oracle_backend/   Backend: question data as an HTTP service (python -m trivia_oracle_backend)
  server.py           /random-tossup, /check-answer, /health
  api/                qbreader.org source
  local/              SQLite source + the sync script that fills it
  vendor/qbreader/    Vendored copy of the qbreader Python API wrapper (MIT)
  Dockerfile, requirements.txt
docker-compose.yml    Runs both; QUESTION_BACKEND picks api or local
tests/                Unit tests: bot/, game/, backend/, contract/
data/                 Runtime files: scores.md, questions.db (gitignored, mounted into the containers)
assets/               Project images
secrets.example.json  Template for local secrets.json
AGENTS.md             Architecture notes for contributors and AI coding agents
```

---

## Credits

- Questions and answer judging: [qbreader](https://www.qbreader.org) — please be gentle with their API.
- `trivia_oracle_backend/vendor/qbreader/` is vendored from [qbreader/python-module](https://github.com/qbreader/python-module)
  (MIT License, © 2022 QBreader — see [LICENSE](trivia_oracle_backend/vendor/qbreader/LICENSE)), with one small patch: `Musicals` is mapped to Other Fine Arts in `_api_utils.py`.
- Built on [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v13.
