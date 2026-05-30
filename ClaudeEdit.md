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
main.py        Entry point. Registers all handlers with the Telegram dispatcher
               and starts polling. Nothing else lives here.

config.py      All immutable constants:
               • TOKEN, SCORES_FILE, POINTS_PER_CORRECT, ADMIN_USERNAME
               • CATEGORIES list (every selectable category/subcategory label)
               • ALL_ALT_SUBCATEGORIES, ALL_SCIENCE, ALL_ARTS helper sets
               • DIFFICULTIES dict (display label → qbreader numeric string)
               • ConversationHandler state IDs (SELECT_OPTION … SELECT_ADMIN)

settings.py    Single `settings` object holding mutable runtime state that
               /configure can change:
               • sentence_interval (float, seconds between sentences)
               • answer_wait (float, seconds to wait after last sentence)
               • selected_categories (set of strings from CATEGORIES)
               • selected_difficulties (set of display-label strings)

scores.py      In-memory score store (dict + threading.Lock) and helpers:
               • load_scores()     — populate from SCORES_FILE on startup
               • save_scores()     — write current scores to SCORES_FILE
               • format_scoreboard() — return a human-readable scoreboard string

round.py       All game logic. Owns `current_round` state dict and `round_lock`.
               • start_round()         — /next handler; fetches question, spawns thread
               • handle_round_answer() — MessageHandler; judges free-text answers
               • _fetch_tossup()       — async; calls qbreader random_tossup
               • _check_answer()       — async; calls qbreader check_answer
               • _build_api_filters()  — splits selected_categories into the two
                                         correct qbreader parameters
               • _run_round()          — thread; drives sentence reveals + end message

keyboards.py   Pure functions that build and return InlineKeyboardMarkup objects.
               Re-called on every render so the checkmarks always reflect current
               state. Never mutates anything.
               • build_category_keyboard()
               • build_difficulty_keyboard()
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
               • configure_admin()            — SELECT_ADMIN callbacks
               • error_handler()
```

---

## Import dependency graph

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
main.py              (imports config, handlers, round, scores)
```

No circular imports. `config.py` and `settings.py` depend on nothing local.

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
`current_round["winners"]` is a list. Multiple answers can be appended within
`scores_lock` before `_run_round` reads the list. The first correct answer
calls `event.set()` to trigger round-end, but any answer received before
`current_round["active"]` is flipped to False also gets scored and added.

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
            ├─ "view_settings" ─────────────────────────────────► END
            └─ "admin" (gated to ADMIN_USERNAME)
                    └─► SELECT_ADMIN (looping) ──► END
```

---

## How to extend the bot

### Add a new bot command
1. Write a handler function in `handlers.py` (or `round.py` if it touches game state).
2. Register it in `main.py` with `dp.add_handler(CommandHandler("name", fn))`.

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
- Entry point: `qbreader.asynchronous.Async` (async context manager).
- Key methods used:
  - `qb.random_tossup(number, subcategories, alternate_subcategories, difficulties)`
  - `qb.check_answer(answerline, given_answer)` → returns `AnswerJudgement` with `.directive` ("accept" / "reject" / "prompt")
- All calls are wrapped in `asyncio.run()` because the Telegram handler threads
  are synchronous (python-telegram-bot v13).

---

## Docker

Build and run:
```
docker build -t chewterence/trivia-oracle:latest .
docker run --rm chewterence/trivia-oracle:latest
```

Push:
```
docker login   # use access token
docker push chewterence/trivia-oracle:latest
```

The Dockerfile copies `qbreader/` and all six `.py` source files into `/app`.
Scores are persisted to `/app/scores.md` inside the container — mount a volume
if you need scores to survive container restarts.
