# TriviaOracleBot — Architecture Reference

> Read this file before making any changes. It explains what the bot does, how
> the code is organised, and exactly where to touch things when adding features.

---

## What the bot does

TriviaOracleBot is a Telegram group trivia bot. It fetches tossup questions from
the [qbreader API](https://www.qbreader.org/api-docs) and reveals them sentence
by sentence. Any group member can type a free-text answer at any time. The first
correct answer (or multiple simultaneous correct answers) wins points. Scores
are persisted to a Markdown file and printed to the group after every round.

**Bot commands**
| Command | What it does |
|---------|-------------|
| `/next` | Start a new round (ignored if one is already active) |
| `/scores` | Print the current scoreboard |
| `/configure` | Open the interactive settings menu |

---

## File structure

```
trivia_oracle/          The bot package. Run with `python -m trivia_oracle`
                        from the repo root. Modules use relative imports.
qbreader/               Vendored qbreader API wrapper (MIT, see qbreader/LICENSE).
                        Must stay at the repo root: it imports itself as `qbreader.*`.
assets/                 Project images; excluded from the Docker build.
Dockerfile              python:3.9-slim; installs requirements.txt, copies
                        qbreader/ and trivia_oracle/, runs `python -m trivia_oracle`.
requirements.txt        Runtime dependencies (python-telegram-bot pinned to 13.7).
secrets.example.json    Template for the gitignored secrets.json.
data/                   Runtime scores (gitignored; Docker volume at /app/data).
```

Inside `trivia_oracle/`:

```
__main__.py    Entry point. Registers all handlers with the Telegram dispatcher
               and starts polling. Nothing else lives here.

config.py      Runtime configuration and immutable constants:
               • TOKEN, ADMIN_USERNAME, SCORES_FILE — read from env vars,
                 falling back to secrets.json (see "Configuration & secrets")
               • POINTS_PER_CORRECT, POINTS_PER_WRONG, POINTS_PER_MEDAL_WRONG
               • SCORING_MODES (key → checkbox label), SCORING_MODE_DESCRIPTIONS,
                 DEFAULT_SCORING_LABEL (shown when no mode is on)
               • CATEGORIES list (every selectable category/subcategory label)
               • ALL_ALT_SUBCATEGORIES, ALL_SCIENCE, ALL_ARTS helper sets
               • DIFFICULTIES dict (display label → qbreader numeric string)
               • ConversationHandler state IDs (SELECT_OPTION … SELECT_SCORING)

settings.py    Single `settings` object holding mutable runtime state that
               /configure can change:
               • sentence_interval (float, seconds between sentences)
               • answer_wait (float, seconds to wait after last sentence)
               • selected_categories (set of strings from CATEGORIES)
               • selected_difficulties (set of display-label strings)
               • scoring_modes (set of SCORING_MODES keys; empty = default scoring)

scores.py      In-memory score store (dict + threading.Lock) and helpers:
               • load_scores()     — populate from SCORES_FILE on startup
               • save_scores()     — write current scores to SCORES_FILE
               • format_scoreboard() — return a human-readable scoreboard string
               • medalist_ids()    — user IDs shown with 🥇🥈🥉 (top 3 on the board)

round.py       All game logic. Owns `current_round` state dict and `round_lock`.
               • start_round()         — /next handler; fetches question, spawns thread
               • handle_round_answer() — MessageHandler; judges free-text answers
               • _fetch_tossup()       — async; calls qbreader random_tossup
               • _check_answer()       — async; calls qbreader check_answer
               • _build_api_filters()  — splits selected_categories into the two
                                         correct qbreader parameters
               • _run_round()          — thread; drives sentence reveals + end message
               • _points_for_correct() — points for a correct answer in this round's mode
               • _penalty_for_wrong()  — deduction for a wrong answer in this round's mode

keyboards.py   Pure functions that build and return InlineKeyboardMarkup objects.
               Re-called on every render so the checkmarks always reflect current
               state. Never mutates anything.
               • build_category_keyboard()
               • build_difficulty_keyboard()
               • build_scoring_keyboard()   — ✅/☐ checkbox row per scoring mode + 💾 Save
               • build_admin_keyboard()

handlers.py    All Telegram handler functions for /configure and /scores.
               Organised by ConversationHandler state with section comments.
               • show_scores()
               • configure()                  — entry point → SELECT_OPTION
               • configure_select_option()    — SELECT_OPTION callbacks
               • configure_select_time_field()— SELECT_TIME_FIELD callbacks
               • configure_input_value()      — INPUT_VALUE text message
               • configure_toggle_category()  — SELECT_CATEGORIES callbacks
               • configure_toggle_difficulty()— SELECT_DIFFICULTIES callbacks
               • configure_select_scoring()   — SELECT_SCORING callbacks
               • configure_admin()            — SELECT_ADMIN callbacks
               • error_handler()
```

---

## Import dependency graph

All imports below are relative (`from .config import ...`).

```
config.py
    ↑
settings.py          (imports CATEGORIES, DIFFICULTIES from config)
scores.py            (imports SCORES_FILE from config)
    ↑
round.py             (imports config, scores, settings)
keyboards.py         (imports config, settings)
    ↑
handlers.py          (imports config, keyboards, scores, settings)
    ↑
__main__.py          (imports config, handlers, round, scores)
```

No circular imports. `config.py` depends on nothing local.

---

## Key design decisions

### settings object instead of module globals
`settings.py` exposes a single `_Settings` instance. All handler and round
functions import this one object and mutate its attributes directly. This avoids
the Python `global` keyword and the `from module import X` rebinding pitfall
(where reassigning a local name doesn't update the original module variable).

### selected_categories set operations
When toggling individual items use `.add()` / `.discard()`.
When toggling a group use `|=` (union-update) and `-=` (difference-update).
When resetting to "all" use `= set(CATEGORIES)` — this is an attribute
assignment on the settings object and is safe; it does NOT need `global`.

### Two qbreader filter parameters
The qbreader API has both `subcategories=` and `alternate_subcategories=`.
`round._build_api_filters()` splits `settings.selected_categories` across
both. The `ALL_ALT_SUBCATEGORIES` set in `config.py` is the authoritative
list of which display names map to the `alternate_subcategories=` parameter.
If all categories are selected the function returns `(None, None)` so no
filter string is sent, which also avoids URL-length issues.

### Concurrent correct answers
`current_round["winners"]` is a list of `(first_name, points)` tuples. Multiple
answers can be appended within `scores_lock` before `_run_round` reads the list.
The first correct answer calls `event.set()` to trigger round-end, but any answer
received before `current_round["active"]` is flipped to False also gets scored
and added. `current_round["winner_ids"]` stops the same player scoring twice.

Two things make "received before" hold for answers sent at the same moment:
- `handle_round_answer` is registered with `run_async=True`. PTB v13 otherwise
  handles updates one at a time, so a second answer would wait out the first
  one's qbreader check and arrive after the round closed.
- Each answer registers in `current_round["pending_checks"]` while its check is
  in flight. `_run_round` flips `active` off, then waits on `checks_settled`
  (a Condition on `scores_lock`) until pending checks reach 0, capped at
  `PENDING_CHECK_TIMEOUT`, before sending the round-end message.

`tests/test_concurrent_answers.py` covers this (`python -m unittest discover tests`).

### Scoring modes
Scoring modes are independent toggles that can be combined. `settings.scoring_modes`
is a set of enabled keys; an empty set is default scoring (+`POINTS_PER_CORRECT`
per correct answer, no penalties). `start_round` snapshots it into
`current_round["scoring_modes"]` (a frozenset), so toggling mid-round only affects
the next round. All scoring decisions go through `_points_for_correct()` and
`_penalty_for_wrong()` in `round.py`.

| Mode key | Effect when on |
|----------|----------------|
| `wrong_penalty` | Every wrong answer: −`POINTS_PER_WRONG` |
| `hourglass` | Correct answer: +`POINTS_PER_CORRECT` × `current_round["hourglasses"]` instead of the flat +`POINTS_PER_CORRECT` |
| `medal_penalty` | Wrong answer by a player in `current_round["medalists"]`: −`POINTS_PER_MEDAL_WRONG` |

- Penalties stack: with `wrong_penalty` and `medal_penalty` both on, a medal
  holder loses `POINTS_PER_WRONG + POINTS_PER_MEDAL_WRONG` (4) per wrong answer.
- `hourglasses` is set by `_run_round` to the ⏳ count of the clue it just sent
  (`total - i`), so it matches what players see. It stays at 1 during the
  answer wait after the last clue.
- `medalists` is `scores.medalist_ids()` captured at round start — the same three
  players shown with medals on the scoreboard, frozen for the round.
- "prompt" judgements (qbreader asks for more specificity) are neither scored
  nor penalised in any mode.

To add a mode: add a key to `SCORING_MODES` and `SCORING_MODE_DESCRIPTIONS` in
`config.py`, then handle it in `_points_for_correct()` / `_penalty_for_wrong()`
with an `in current_round["scoring_modes"]` check. The keyboard, menu text, and
settings summary pick it up automatically.

### round_lock
A `threading.Lock` held for the entire duration of a round (acquired in
`start_round`, released at the end of `_run_round`). `acquire(blocking=False)`
in `start_round` silently drops a `/next` command if a round is already running.

---

## ConversationHandler state machine

```
/configure
    │
    └─► SELECT_OPTION
            ├─ "time"       ──► SELECT_TIME_FIELD ──► INPUT_VALUE ──► END
            ├─ "category"   ──► SELECT_CATEGORIES (looping) ──► END
            ├─ "difficulty" ──► SELECT_DIFFICULTIES (looping) ──► END
            ├─ "scoring"    ──► SELECT_SCORING (looping) ──► END
            ├─ "view_settings" ─────────────────────────────────► END
            └─ "admin" (gated to ADMIN_USERNAME; disabled if unset)
                    └─► SELECT_ADMIN (looping) ──► END
```

---

## How to extend the bot

### Add a new bot command
1. Write a handler function in `handlers.py` (or `round.py` if it touches game state).
2. Register it in `__main__.py` with `dp.add_handler(CommandHandler("name", fn))`.

### Add a new /configure setting (scalar value)
1. Add the attribute to `_Settings` in `settings.py`.
2. Add a button in `configure()` keyboard in `handlers.py` with a new `callback_data`.
3. Handle that `callback_data` in `configure_select_option` — either create a new
   state or reuse `INPUT_VALUE` flow (copy the time setting pattern).
4. Update `"view_settings"` block in `configure_select_option` to display the new value.

### Add a new admin-only action
1. Add a button to `build_admin_keyboard()` in `keyboards.py`.
2. Add an `elif query.data == "your_action":` branch in `configure_admin()` in `handlers.py`.
   - For destructive actions, follow the existing "Are you sure?" confirmation pattern.

### Add a new category group bulk-toggle button (like Science / Arts)
1. Add a set constant (e.g. `ALL_HISTORY = {...}`) in `config.py`.
2. Add a suffix emoji for those entries in `build_category_keyboard()` in `keyboards.py`.
3. Add the toggle row above the existing bulk-toggle rows in `build_category_keyboard()`.
4. Add an `elif query.data == "cat_toggle_X":` branch in `configure_toggle_category()`.

### Add new qbreader categories/subcategories
- **Subcategory values** (qbreader `Subcategory` enum): add to `CATEGORIES` only.
- **AlternateSubcategory values** (qbreader `AlternateSubcategory` enum): add to
  both `CATEGORIES` and `ALL_ALT_SUBCATEGORIES` in `config.py`.
- Check the qbreader enums with:
  ```python
  from qbreader.types import Subcategory, AlternateSubcategory
  list(Subcategory)
  list(AlternateSubcategory)
  ```

---

## qbreader API notes

- Library: local `qbreader/` folder (vendored, not pip-installed).
  Copied from qbreader/python-module v1.0.1 with one patch: `AlternateSubcategory.MUSICALS`
  added to the Other Fine Arts mapping in `_api_utils.py`. Keep `qbreader/LICENSE` with it.
- Entry point: `qbreader.asynchronous.Async` (async context manager).
- Key methods used:
  - `qb.random_tossup(number, subcategories, alternate_subcategories, difficulties)`
  - `qb.check_answer(answerline, given_answer)` → returns `AnswerJudgement` with `.directive` ("accept" / "reject" / "prompt")
- All calls are wrapped in `asyncio.run()` because the Telegram handler threads
  are synchronous (python-telegram-bot v13).

---

## Configuration & secrets

`config.py` resolves each setting with `_setting(name)`: environment variable
first, then `secrets.json` in the repo root (gitignored), then a default.

| Name | Required | Default | Notes |
|------|----------|---------|-------|
| `TELEGRAM_TOKEN` | yes | — | Bot exits at import time with a clear message if missing. |
| `ADMIN_USERNAME` | no | `None` | Telegram username without `@`. `None` locks Admin Settings for everyone. |
| `SCORES_FILE` | no | `<repo>/data/scores.md` | Parent directory is created on first save. |

`secrets.example.json` shows the format. To add a new setting, read it in
`config.py` with `_setting("YOUR_KEY")`, expose it as a module-level constant,
and document it here, in the README table, and in `secrets.example.json`.

**Never commit real secrets.** This repo is public. `secrets.json`, `.env`, and
`data/` (player names + Telegram IDs) are gitignored and dockerignored. Secrets
are passed to Docker at runtime with `-e`, never copied into the image.

---

## Docker

```bash
docker build -t trivia-oracle .
docker run --rm \
  -e TELEGRAM_TOKEN=... -e ADMIN_USERNAME=... \
  -v "$(pwd)/data:/app/data" \
  trivia-oracle
```

The image contains only `qbreader/` and `trivia_oracle/`. Scores go to
`/app/data/scores.md`; mount a volume on `/app/data` to keep them. Mount
`/app/data`, not `/app` — mounting over `/app` hides the code.

Publishing (maintainer only):
```bash
docker build --platform linux/amd64 -t chewterence/trivia-oracle:latest .
docker login   # use an access token
docker push chewterence/trivia-oracle:latest
```

---

## Running locally

```bash
pip install -r requirements.txt
cp secrets.example.json secrets.json   # then fill it in
python -m trivia_oracle
```

Only one process may poll a given token. A second instance gets a Telegram
`Conflict` error and `error_handler` exits it.
