# TriviaOracleBot 🎯

A Telegram group trivia bot built just for fun by **Terence Chew**. It asks quizbowl tossups from the
[qbreader](https://www.qbreader.org) database one clue at a time. Type your answer before the clues run out.

100% vibe coded. No regrets.

**Contents:** [Playing](#playing) · [Scoring](#scoring) · [Running it](#running-it) ·
[Questions and answer checking](#questions-and-answer-checking) · [Development](#development) · [Credits](#credits)

---

## Playing

| Command | What it does |
|---------|--------------|
| `/next` | Start a new round |
| `/scores` | Show the scoreboard |
| `/good`, `/bad` | Rate the custom question that was just played (see [Custom questions](#custom-questions)) |
| `/configure` | Change timing, categories, difficulty and scoring mode |

During a round, just type your answer in the chat. The first correct answer wins the points.

- Questions don't repeat in a chat until 30 minutes pass without a round starting. This is kept in memory, so a restart clears it.
- The scoreboard is saved to disk and survives restarts. Only the admin can reset it.

---

## Scoring

A correct answer is worth **+10** and wrong answers cost nothing, unless you change that in
`/configure` → **🏆 Scoring Mode**. Tick any combination and press **💾 Save**. Changes apply from the next round.

| Mode | Effect |
|------|--------|
| **Wrong answers -1pt** | Every wrong answer costs 1 point |
| **Hourglass bonus** | A correct answer scores 10 × the ⏳ still showing (⏳⏳⏳⏳⏳ = 50) |
| **Medals get penalty** | Whoever holds 🥇🥈🥉 at the start of the round loses 3 points per wrong answer |

Penalties stack, so a medal holder with both penalty modes on loses 4 per wrong answer.
If several people answer correctly at the same moment, all of them are credited.

---

## Running it

### 1. Create a bot

Talk to [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the token. Add the bot to your group.
For it to see plain-text answers, make it a group admin or turn off privacy mode with `/setprivacy`.

### 2. Add your settings

```bash
cp secrets.example.json secrets.json    # gitignored; fill it in
```

Each setting can also be an environment variable, which takes priority over `secrets.json`.

| Setting | Required | Description |
|---------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `ADMIN_USERNAME` | No | Your Telegram username without `@`. Unlocks **Admin Settings** in `/configure`. |
| `SCORES_FILE` | No | Where scores are stored. Default: `data/scores.md` |
| `BACKEND_URL` | No | Where the question backend listens. Default: `http://localhost:8080` (Compose sets it for you) |

### 3. Start it

Run only one bot per token. A second instance shuts itself down.

**Docker Compose (recommended)** starts two containers, the bot and the question backend:

```bash
docker compose up -d                 # start both
docker compose logs -f --tail 50 bot # watch the bot's console; each round's answer is logged as "Answer: ..."
docker compose down                  # stop
```

The container is named `trivia-oracle-bot-1`, so `docker logs -f --tail 50 trivia-oracle-bot-1` works from any folder.
If the bot exits with `TELEGRAM_TOKEN is not set`, check that `secrets.json` sits next to `docker-compose.yml`.

**Plain Python** needs Python 3.9–3.11 (python-telegram-bot 13 breaks on 3.12+):

```bash
pip install -r trivia_oracle_backend/requirements.txt -r trivia_oracle_bot/requirements.txt
python -m trivia_oracle_backend     # terminal 1: question backend on :8080
python -m trivia_oracle_bot         # terminal 2: the bot
```

---

## Questions and answer checking

The bot is only a Telegram frontend. It never contacts qbreader itself: every question and every answer
check goes to the **question backend**, a small HTTP service (`trivia_oracle_backend`).

| `QUESTION_BACKEND` | Questions | Answer checking |
|--------------------|-----------|-----------------|
| `local` (default) | SQLite copy in `data/questions.db` | Built-in checker, no network calls |
| `api` | qbreader.org, live | qbreader.org |

Set it with `QUESTION_BACKEND=api docker compose up -d`. The backend also reads `QUESTIONS_DB`, `HOST` and
`PORT` (see [AGENTS.md](AGENTS.md)).

### Custom questions

Hand-written questions (see [custom/CONTRIBUTING.md](trivia_oracle_backend/custom/CONTRIBUTING.md)) live in their own
database, `data/custom_questions.db`, and work in both modes. In `/configure` → **📚 Categories**, tick **Custom** to play them:

- Custom on its own (untick everything else, e.g. with **Deselect All**) plays only custom questions.
- Custom next to other categories mixes it in: each round has an equal chance of being custom or a regular question,
  because the custom set is small and would otherwise almost never come up.
- Custom questions ignore the category and difficulty filters. Every custom question is fair game.
- A custom round opens with a message of its own, `📝 Custom question` and then `Category: <category>` on the next line, sent just before the first clue.
- A custom round's end message asks players to rate the question with `/good` or `/bad`. Votes are added to the
  question's `good_votes` / `bad_votes` in `data/custom_questions.db`, and reloading a submission file keeps them.
  Each player has one vote per round: repeating the same command is ignored, and the other command replaces their
  earlier vote. Voting closes when the next round starts, and the bot does not reply to votes.
- If no custom questions are loaded yet, a custom-only `/next` says "Failed to fetch a question", and a mixed one just
  plays a regular question. The file is read on every request, so you can load questions while the bot is running.

### Filling the local database

You run the sync yourself, whenever you like. It copies qbreader into `data/questions.db`: about an hour and
300 MB for everything. It resumes if interrupted, and re-running only fetches sets you don't have yet.

```bash
docker compose run --rm --no-deps backend python -m trivia_oracle_backend.local.sync
python -m trivia_oracle_backend.local.sync --limit 5     # try a few sets first (also: --sets "2023 ACF Winter", --refresh)
```

The backend re-reads the file on every request, so you can sync while it's running. It only refuses to start
if the file doesn't exist yet.

### How the local checker judges answers

It reads the answerline the way qbreader's editors write it, e.g.
`<u>Constantine</u> the <u>Great</u> [or Constantine I; prompt on Constantine; do not accept "Constantine II"]`.

- **Underlined or bold words are required.** `Grant` and `Ulysses Grant` both beat `Ulysses S. <u>Grant</u>`,
  but `Grant Wood` does not.
- **Directives:** `accept` and `or` add answers, `prompt on` asks for more, and `do not accept` / `reject` always win.
- **Ignored:** case, accents, punctuation, a leading "the/a/an". Roman numerals equal digits.
- **Typos:** forgiven per word, none up to 5 letters (`Kant` isn't `Kent`), one in 6–14, more beyond that. The first
  letter must be right, so `refraction` doesn't pass for `reflection`.
- **Not understood:** free-text instructions like "accept equivalents". Such answerlines accept only what they spell out.

The local verdict is final. The bot's extra lenient-spelling pass only runs in `api` mode.

### Known limitations

- The local database only has the sets you synced. The bot defaults to HS Easy and HS Regular, so a college-only
  database answers `/next` with "Failed to fetch a question" until you sync HS sets or pick other difficulties in `/configure`.
- Choosing a normal subcategory together with an alternate one (say Biology and Poetry) matches nothing in local mode.
- The local checker is a little different from qbreader's: it forgives some one-letter typos in longer words that qbreader
  rejects, and it can't tell near neighbours like Iceland and Ireland apart.

---

## Development

Two independent services that talk over HTTP and never import each other. The JSON in
`trivia_oracle_backend/server.py` is the contract. [AGENTS.md](AGENTS.md) has the full architecture notes.

```
trivia_oracle_bot/       Frontend: the Telegram bot
  bot/                   Telegram UI: commands, /configure menus, keyboards
  game/                  Rules and state: rounds, scoring, settings, scoreboard (no Telegram code)
  questions.py           HTTP client for the backend
  config.py              Token, admin, categories, difficulties, scoring constants
trivia_oracle_backend/   Backend: questions and answer checking as an HTTP service
  server.py              /health, /random-tossup, /rate-tossup, /check-answer
  local/                 SQLite source, the sync script and the answer checker
  api/, vendor/qbreader/ The qbreader.org source and its vendored client
  custom/                Hand-written questions (see custom/CONTRIBUTING.md)
tests/                   bot, game, backend, contract, integration
docker-compose.yml       Runs both containers
data/                    Runtime files, gitignored: scores.md (bot), questions.db (backend)
```

Each package has its own `Dockerfile` and `requirements.txt`.

### Where to edit

| I want to... | Edit |
|--------------|------|
| Add or change a command or /configure menu | `trivia_oracle_bot/bot/` |
| Change round rules, timing or scoring | `trivia_oracle_bot/game/round.py`, `trivia_oracle_bot/config.py` |
| Change selectable categories or difficulties | `trivia_oracle_bot/config.py`, `game/settings.py` |
| Change how answers are judged locally | `trivia_oracle_backend/local/` (`answerline.py`, `matching.py`, `answer_judge.py`) |
| Change the wire format or add an endpoint | `trivia_oracle_backend/server.py` and `trivia_oracle_bot/questions.py` together |
| Change how questions are filtered or the database | `trivia_oracle_backend/local/` (`question_source.py`, `schema.sql`, `sync.py`) |
| Add a setting | the package's `config.py`, then the tables here and in AGENTS.md |

### Running tests

The tests fake Telegram and qbreader, so they need no token or network. Each image holds only its own code, so
mount `tests/` and run each side in its own image:

```bash
docker build -f trivia_oracle_bot/Dockerfile -t trivia-oracle-bot .
docker build -f trivia_oracle_backend/Dockerfile -t trivia-oracle-backend .

# bot + game
docker run --rm -v "$PWD/tests:/app/tests:ro" trivia-oracle-bot sh -c \
  "python -m unittest discover -s tests/bot -t . && python -m unittest discover -s tests/game -t ."

# backend (add -v "$PWD/data:/app/data:ro" to also check every answerline in your database)
docker run --rm -v "$PWD/tests:/app/tests:ro" trivia-oracle-backend \
  python -m unittest discover -s tests/backend -t .

# contract + integration (need both packages, so mount the bot's code too)
docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/trivia_oracle_bot:/app/trivia_oracle_bot:ro" \
  trivia-oracle-backend sh -c \
  "python -m unittest discover -s tests/contract -t . && python -m unittest discover -s tests/integration -t ."
```

---

## Credits

- Questions: [qbreader](https://www.qbreader.org). Please be gentle with their API.
- `trivia_oracle_backend/vendor/qbreader/` is vendored from [qbreader/python-module](https://github.com/qbreader/python-module)
  (MIT, © 2022 QBreader, see [LICENSE](trivia_oracle_backend/vendor/qbreader/LICENSE)), with one patch:
  `Musicals` is mapped to Other Fine Arts in `_api_utils.py`.
- Built on [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v13.

### Contributors

Thanks to everyone who sent a pull request:

- [@beaux3](https://github.com/beaux3): no repeat questions within a chat session ([#5](../../pull/5))
- [@xianlinc](https://github.com/xianlinc): lenient qbreader spellings and abbreviated game titles ([#4](../../pull/4)), replies to directed answer prompts ([#1](../../pull/1))

And to everyone who reviewed them:

- [@xianlinc](https://github.com/xianlinc) and [@nigelnnk](https://github.com/nigelnnk): reviewed [#5](../../pull/5)
