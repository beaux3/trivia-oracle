# TriviaOracleBot 🎯

A Telegram group trivia bot built just for fun by **Terence Chew**. Questions come from the
[qbreader](https://www.qbreader.org) quizbowl database, live or from an offline copy. They are revealed
one sentence at a time, so buzz in by typing your answer before the clues run out.

100% vibe coded. No regrets.

**Contents:** [Playing](#playing) · [Scoring](#scoring) · [Running it yourself](#running-it-yourself) ·
[Question sources](#question-sources) · [Development](#development) · [Credits](#credits)

---

## Playing

**Features**

- Quizbowl tossups across dozens of categories (Literature, History, Science, Arts, Pop Culture, and more)
- Clues revealed one sentence at a time; answers judged by a built-in local checker, no network calls
- Configurable categories, difficulty, timing and scoring via `/configure`
- Combinable [scoring modes](#scoring)
- A scoreboard that survives restarts
- Admin-only score reset

**Commands**

| Command | Description |
|---------|-------------|
| `/next` | Start a new round |
| `/scores` | Show the current scoreboard |
| `/configure` | Configure timing, categories, difficulty, and scoring mode |

During a round, just type your answer in the chat.

Questions won't repeat in the same chat until 30 minutes pass without a successful `/next` starting a
question. This history is kept in memory, so it clears when the bot restarts.

---

## Scoring

By default every correct answer is worth **+10** and wrong answers cost nothing.
To change that, open `/configure` → **🏆 Scoring Mode**, tick any combination of modes, then press **💾 Save**:

| Mode | Effect |
|------|--------|
| **Wrong answers -1pt** | Every wrong answer costs 1 point |
| **Hourglass bonus** | A correct answer scores 10 × the ⏳ still showing (answer on ⏳⏳⏳⏳⏳ for 50) |
| **Medals get penalty** | Whoever holds 🥇🥈🥉 when the round starts loses 3 points per wrong answer |

- Penalties stack: with both penalty modes on, a medal holder loses 4 points per wrong answer.
- Changes take effect from the next round.
- Everyone who answers correctly gets credited, even if several people answer at the same time.

---

## Running it yourself

### 1. Create a bot

Talk to [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`, and copy the token it gives you.
Add the bot to your group. For it to see plain-text answers, either make it a group admin or turn off
privacy mode with `/setprivacy` in BotFather.

### 2. Configure it

The bot reads these settings from environment variables, falling back to a local `secrets.json`:

| Setting | Required | Description |
|---------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `ADMIN_USERNAME` | No | Your Telegram username (without `@`). Unlocks **Admin Settings** in `/configure`. If unset, nobody is admin. |
| `SCORES_FILE` | No | Where to store scores. Default: `data/scores.md` |
| `BACKEND_URL` | No | Where the question backend listens. Default: `http://localhost:8080` (Docker Compose sets it for you) |

For a local run, copy the example file and fill it in (`secrets.json` is gitignored):

```bash
cp secrets.example.json secrets.json
```

The bot is only a frontend. Questions and answer checking come from the question backend service, which
has its own settings (see [Question sources](#question-sources)).

### 3. Start it

Pick one of the two options. Either way, run only one bot per token: a second instance shuts itself down.

**Docker Compose (recommended)**

Two containers, two images: the **bot** (`trivia_oracle_bot/Dockerfile`) and the **question backend**
(`trivia_oracle_backend/Dockerfile`). `docker-compose.yml` builds and connects them. The bot reads your
`secrets.json` (mounted read-only, and the backend never sees it) and keeps its scoreboard in `./data`.

```bash
docker compose up -d                        # backend serves questions from ./data/questions.db
QUESTION_BACKEND=api docker compose up -d   # backend serves them live from qbreader.org instead
docker compose logs -f bot
```

To watch the bot's console output (each round's correct answer is logged as `Answer: ...`), follow the logs.
Ctrl+C stops watching, not the bot:

```bash
docker compose logs -f --tail 50 bot                                   # from this folder
docker logs -f --tail 50 trivia-oracle-bot-1                           # from anywhere, by container name
docker compose logs -f --no-log-prefix bot | grep --line-buffered "Answer:"   # only the answers
```

If the bot exits with `TELEGRAM_TOKEN is not set`, check that `secrets.json` exists next to
`docker-compose.yml`.

**Plain Python**

Requires Python 3.9–3.11 (python-telegram-bot 13.x breaks on 3.12+). The Docker images use 3.11.

```bash
pip install -r trivia_oracle_backend/requirements.txt -r trivia_oracle_bot/requirements.txt
python -m trivia_oracle_backend     # terminal 1: question backend on :8080
python -m trivia_oracle_bot         # terminal 2: the bot
```

---

## Question sources

`trivia_oracle_backend` is a small HTTP service (`/random-tossup`, `/check-answer`, `/health`; see
`trivia_oracle_backend/server.py`) that sits in front of one of two sources, chosen by `QUESTION_BACKEND`:

| `QUESTION_BACKEND` | Questions from | Answers judged by |
|--------------------|----------------|-------------------|
| `local` (default) | `QUESTIONS_DB` (default `data/questions.db`), a SQLite copy of qbreader | the built-in [local checker](#the-local-answer-checker), in-process |
| `api` | qbreader.org, live | qbreader.org's answer checker |

- In `local` mode the backend makes no network calls at all, and there is no fallback to qbreader.
- `HOST` and `PORT` (default `0.0.0.0:8080`) set where it listens. Compose does not publish the port, so
  only the bot can reach it.

### The local answer checker

It reads the answerline the way qbreader's editors write it, for example
`<b><u>Constantine</u></b> the <b><u>Great</u></b> [or <b><u>Constantine I</u></b>; prompt on <u>Constantine</u>; do not accept “Constantine II”]`:

- Underlined or bold text is what a player must say. The whole answer, or only the required words, is
  accepted (`Grant` and `Ulysses Grant` both beat `Ulysses S. <u>Grant</u>`). A word that is not part of the
  answer (`Grant Wood`, `President Grant`) makes it wrong.
- `accept X`, `or X`, and round brackets that open with a directive add answers. `prompt on X` asks for
  more, in the answerline's own words when it says `by asking "..."`. `do not accept`, `do not accept or
  prompt on` and `reject` always win and match word for word, so `reject “The Invisible Man”` does not catch
  `Invisible Man`.
- Case, accents, punctuation and a leading "the/a/an" do not matter. Roman numerals equal digits
  (`Henry VIII` = `Henry 8`), while `C`, `C++` and `C#` stay different answers.
- Typos are forgiven word by word: none up to 5 letters (`Kant` is not `Kent`), one in 6-14, two in 15-20,
  three beyond, and the first letter must be right (so `refraction` is not `reflection`). Numbers must match exactly. `accept word forms` also
  allows other forms of a word (`Italy` for `Italian`), and `accept either underlined portion` works.
- Free-text instructions such as `accept equivalents` or `accept any Coalition War` cannot be judged, so
  an answerline that relies on them accepts only what it spells out.
- The local verdict is final: the backend marks it `"final": true` in the `/check-answer` reply, and the
  bot's own lenient-spelling pass (`trivia_oracle_bot/game/spelling.py`) does not overturn it. That pass
  only runs in `api` mode, after a qbreader reject.

### Offline questions

Syncing is a job you run yourself, whenever you like. It copies qbreader into the database: about an
hour and ~300 MB for all sets. It resumes if interrupted, and a re-run only fetches sets you don't have yet.

```bash
python -m trivia_oracle_backend.local.sync              # or with Docker:
docker compose run --rm --no-deps backend python -m trivia_oracle_backend.local.sync
```

- Add `--limit 5` or `--sets "2023 ACF Winter"` to try it on a few sets first (`--refresh` re-downloads sets you already have).
- Then start the backend with `QUESTION_BACKEND=local`.
- The backend reads the file on every request, so a sync can run while it is up. It only refuses to start if the file doesn't exist yet.

### Known limitations

- `api` mode judges answers with qbreader.org. `local` mode judges them itself; see
  [the local checker](#the-local-answer-checker) for what it cannot understand.
- The local database only has the sets you synced. The bot's default difficulties are HS Easy and
  HS Regular, so a database with only college sets answers `/next` with "Failed to fetch a question"
  until you sync HS sets or pick matching difficulties in `/configure`.
- Picking a normal subcategory together with an alternate one (say Biology and Poetry) matches nothing in
  local mode, because the filters are ANDed. `tests/integration` records this as an expected failure.

---

## Development

The repo is two independent services that talk over HTTP, plus their tests. They share no code and never
import each other: the JSON in `trivia_oracle_backend/server.py` is the contract between them.

For architecture notes and a longer "where to edit" guide, see [AGENTS.md](AGENTS.md).

### Project layout

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
  local/                 Source 2: SQLite copy (questions.db) + the sync script that fills it,
                         and the answer checker (answer_judge.py, answerline.py, matching.py)
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

### What lives where

| I want to... | Edit |
|--------------|------|
| Add or change a bot command or /configure menu | `trivia_oracle_bot/bot/` (`handlers.py`, `keyboards.py`, `app.py`) |
| Change round rules, timing or scoring | `trivia_oracle_bot/game/round.py`, `trivia_oracle_bot/config.py` |
| Change which categories or difficulties can be picked | `trivia_oracle_bot/config.py` (and the default selection in `game/settings.py`) |
| Change the scoreboard or how scores are saved | `trivia_oracle_bot/game/scores.py` |
| Change how answers are judged in local mode | `trivia_oracle_backend/local/` (`answerline.py` reads answerlines, `matching.py` compares words, `answer_judge.py` decides) |
| Change the bot's extra leniency on rejected answers | `trivia_oracle_bot/game/spelling.py` |
| Change how the bot talks to the backend | `trivia_oracle_bot/questions.py` and `trivia_oracle_backend/server.py` together |
| Add an endpoint or change a response | `trivia_oracle_backend/server.py` |
| Change how local questions are chosen (filters) | `trivia_oracle_backend/local/question_source.py` |
| Change the local database or the sync | `trivia_oracle_backend/local/` (`schema.sql`, `db.py`, `sync.py`) |
| Change how the qbreader API is called | `trivia_oracle_backend/api/qbreader_api.py` |
| Add a setting or environment variable | `trivia_oracle_bot/config.py` or `trivia_oracle_backend/config.py`, then the tables above and in AGENTS.md |
| Change the container setup | each package's `Dockerfile`, or `docker-compose.yml` |

### Running tests

The tests fake Telegram and qbreader, so they need no token or network access.

| Suite | Covers | Needs |
|-------|--------|-------|
| `tests/bot`, `tests/game` | The bot | bot image |
| `tests/backend` | The service, the local source and the local answer checker | backend image |
| `tests/contract` | The one list both sides must agree on | both packages |
| `tests/integration` | The whole path: bot client, backend, SQLite, whole rounds (qbreader's checker is scripted, except in `test_local_answer_checking.py`) | both packages |

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

`tests/backend/test_answer_corpus.py` runs the local checker against every answerline in a real database
and is skipped without one; add `-v "$PWD/data:/app/data:ro"` to the backend command to include it.

`tests/contract` and `tests/integration` need both packages. Run them in the backend image with the bot's
code mounted, or from the repo root with both requirements files installed:

```bash
docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/trivia_oracle_bot:/app/trivia_oracle_bot:ro" \
  trivia-oracle-backend sh -c \
  "python -m unittest discover -s tests/contract -t . && python -m unittest discover -s tests/integration -t ."
```

---

## Credits

- Questions and answer judging: [qbreader](https://www.qbreader.org). Please be gentle with their API.
- `trivia_oracle_backend/vendor/qbreader/` is vendored from [qbreader/python-module](https://github.com/qbreader/python-module)
  (MIT License, © 2022 QBreader, see [LICENSE](trivia_oracle_backend/vendor/qbreader/LICENSE)), with one
  small patch: `Musicals` is mapped to Other Fine Arts in `_api_utils.py`.
- Built on [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v13.

### Contributors

Thanks to everyone who sent a pull request:

- [@beaux3](https://github.com/beaux3): no repeat questions within a chat session ([#5](../../pull/5))
- [@xianlinc](https://github.com/xianlinc): lenient qbreader spellings and abbreviated game titles ([#4](../../pull/4)), replies to directed answer prompts ([#1](../../pull/1))

And to everyone who reviewed them:

- [@xianlinc](https://github.com/xianlinc) and [@nigelnnk](https://github.com/nigelnnk): reviewed [#5](../../pull/5)
