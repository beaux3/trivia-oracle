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

For local runs, copy the example file and fill it in (`secrets.json` is gitignored):

```bash
cp secrets.example.json secrets.json
```

### 3a. Run with Docker (recommended)

```bash
docker build -t trivia-oracle .
docker run --rm \
  -e TELEGRAM_TOKEN=your-bot-token \
  -e ADMIN_USERNAME=your_username \
  -v "$(pwd)/data:/app/data" \
  trivia-oracle
```

The `-v` mount keeps the scoreboard across container restarts. Secrets are passed at runtime
and are never baked into the image.

### 3b. Run with Python

Requires Python 3.9+ (python-telegram-bot 13.x doesn't support 3.13+).

```bash
pip install -r requirements.txt
python -m trivia_oracle
```

Only run one instance per bot token — a second instance will shut itself down.

### Running tests

```bash
python -m unittest discover tests
```

The tests fake Telegram and qbreader, so they need no token or network access.

---

## Project layout

```
trivia_oracle/        The bot (run with `python -m trivia_oracle`)
qbreader/             Vendored copy of the qbreader Python API wrapper (MIT)
tests/                Unit tests (python -m unittest discover tests)
assets/               Project images
Dockerfile            Container build
requirements.txt      Python dependencies
secrets.example.json  Template for local secrets.json
AGENTS.md             Architecture notes for contributors and AI coding agents
```

---

## Credits

- Questions and answer judging: [qbreader](https://www.qbreader.org) — please be gentle with their API.
- `qbreader/` is vendored from [qbreader/python-module](https://github.com/qbreader/python-module)
  (MIT License, © 2022 QBreader — see [qbreader/LICENSE](qbreader/LICENSE)), with one small patch: `Musicals` is mapped to Other Fine Arts in `_api_utils.py`.
- Built on [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v13.
