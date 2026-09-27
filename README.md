# TriviaOracleBot 🎯

A Telegram group trivia bot built just for fun by **Terence Chew**. Questions come from the [qbreader](https://www.qbreader.org) quizbowl database, live or from an offline copy, and are revealed sentence by sentence — buzz in by typing your answer before the clue runs out.

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

`tests/contract` and `tests/integration` need both packages. `tests/integration` runs the real backend
service over a temporary SQLite database and plays whole rounds against it through the bot's HTTP
client; only qbreader's answer checker is scripted. Run them in the backend image with the bot's code
mounted, or from the repo root with both requirements files installed:

```bash
docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/trivia_oracle_bot:/app/trivia_oracle_bot:ro" \
  trivia-oracle-backend sh -c \
  "python -m unittest discover -s tests/contract -t . && python -m unittest discover -s tests/integration -t ."
```

The tests fake Telegram and qbreader, so they need no token or network access.

---

## Project layout

The repo is two independent services that talk over HTTP, plus their tests.

```
trivia_oracle_bot/       FRONTEND: the Telegram bot (python -m trivia_oracle_bot)
  bot/                   Telegram UI: /next, /scores, /configure menus and keyboards
  game/                  Rules and state: rounds, scoring, settings, scoreboard, lenient spelling
                         (no Telegram code)
  questions.py           HTTP client for the backend (BACKEND_URL)
  config.py              Token, admin, categories, difficulties, scoring constants
  Dockerfile, requirements.txt
trivia_oracle_backend/   BACKEND: question data as an HTTP service (python -m trivia_oracle_backend)
  server.py              /health, /random-tossup, /check-answer (the wire format)
  __main__.py            Picks the source from QUESTION_BACKEND and starts the service
  api/                   Source 1: qbreader.org, live
  local/                 Source 2: SQLite copy (questions.db) + the sync script that fills it
  vendor/qbreader/       Vendored qbreader API wrapper (MIT)
  Dockerfile, requirements.txt
docker-compose.yml       Runs both containers; QUESTION_BACKEND picks api or local
tests/                   bot/ game/ (bot image), backend/ (backend image),
                         contract/ integration/ (need both packages)
data/                    Runtime files, gitignored: scores.md (bot), questions.db (backend)
assets/                  Project images
secrets.example.json     Template for the gitignored secrets.json
AGENTS.md                Architecture notes and a "where to edit" guide for contributors and AI agents
```

The two packages share no code and never import each other. The JSON in
`trivia_oracle_backend/server.py` is the contract between them.

### What lives where

| I want to... | Edit |
|--------------|------|
| Add or change a bot command or /configure menu | `trivia_oracle_bot/bot/` (`handlers.py`, `keyboards.py`, `app.py`) |
| Change round rules, timing or scoring | `trivia_oracle_bot/game/round.py`, `trivia_oracle_bot/config.py` |
| Change which categories or difficulties can be picked | `trivia_oracle_bot/config.py` (and the default selection in `game/settings.py`) |
| Change the scoreboard or how scores are saved | `trivia_oracle_bot/game/scores.py` |
| Change how answers are matched | `trivia_oracle_bot/game/spelling.py` (bot side), or `trivia_oracle_backend/api/` (the judge) |
| Change how the bot talks to the backend | `trivia_oracle_bot/questions.py` and `trivia_oracle_backend/server.py` together |
| Add an endpoint or change a response | `trivia_oracle_backend/server.py` |
| Change how local questions are chosen (filters) | `trivia_oracle_backend/local/question_source.py` |
| Change the local database or the sync | `trivia_oracle_backend/local/` (`schema.sql`, `db.py`, `sync.py`) |
| Change how the qbreader API is called | `trivia_oracle_backend/api/qbreader_api.py` |
| Add a setting or environment variable | `trivia_oracle_bot/config.py` or `trivia_oracle_backend/config.py`, then the tables above and in AGENTS.md |
| Change the container setup | each package's `Dockerfile`, or `docker-compose.yml` |

Which test suite covers what: `tests/bot` and `tests/game` for the bot, `tests/backend` for the
service and the local source, `tests/contract` for the one list both sides must agree on, and
`tests/integration` for the whole path (bot client, backend, SQLite, rounds).

### Known limitations

- Answer checking always calls qbreader.org, even with `QUESTION_BACKEND=local`.
- The local database only has the sets you synced. The bot's default difficulties are HS Easy and
  HS Regular, so a database with only college sets answers `/next` with "Failed to fetch a question"
  until you sync HS sets or pick matching difficulties in `/configure`.
- Picking a normal subcategory together with an alternate one (say Biology and Poetry) matches
  nothing in local mode, because the filters are ANDed. `tests/integration` records this as an
  expected failure.

---

## Credits

- Questions and answer judging: [qbreader](https://www.qbreader.org) — please be gentle with their API.
- `trivia_oracle_backend/vendor/qbreader/` is vendored from [qbreader/python-module](https://github.com/qbreader/python-module)
  (MIT License, © 2022 QBreader — see [LICENSE](trivia_oracle_backend/vendor/qbreader/LICENSE)), with one small patch: `Musicals` is mapped to Other Fine Arts in `_api_utils.py`.
- Built on [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v13.
