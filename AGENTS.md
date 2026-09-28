# TriviaOracleBot — Architecture Reference

> Read this file before making any changes. It explains what the bot does, how
> the code is organised, and exactly where to touch things when adding features.

---

## What the bot does

TriviaOracleBot is a Telegram group trivia bot. It fetches tossup questions from
the [qbreader API](https://www.qbreader.org/api-docs) (or a local SQLite copy of
it) through a separate question backend service (see "Question data backend"), and
reveals them sentence by sentence. Any group member can type a free-text answer at any time. The first
correct answer (or multiple simultaneous correct answers) wins points. Scores
are persisted to a Markdown file and printed to the group after every round.

**Bot commands**
| Command | What it does |
|---------|-------------|
| `/next` | Start a new round (ignored if one is already active; refused with a reply if the last custom question is still unrated) |
| `/scores` | Print the current scoreboard |
| `/good`, `/bad` | Rate the custom question just played (one vote per player per round; latest wins; open until the next round starts) |
| `/configure` | Open the interactive settings menu |

---

## File structure

```
trivia_oracle_bot/      Frontend: the Telegram bot. Run with `python -m trivia_oracle_bot` from
                        the repo root. Own Dockerfile and requirements.txt. Talks to the backend
                        over HTTP (questions.py) and must never import `trivia_oracle_backend`.
trivia_oracle_backend/  Backend: question data as an aiohttp service (server.py) over the qbreader
                        API source or the offline SQLite source + sync crawler. Own Dockerfile and
                        requirements.txt. Must never import `telegram` or `trivia_oracle_bot`.
  vendor/qbreader/      Vendored qbreader API wrapper (MIT, see its LICENSE). It imports
                        itself as `qbreader.*`; api/__init__.py puts vendor/ on sys.path
                        before importing it.
docker-compose.yml      Runs both containers; QUESTION_BACKEND picks api or local for the backend.
tests/                  tests/bot, tests/game (bot image), tests/backend (backend image),
                        tests/contract and tests/integration (need both packages; run from the
                        repo root, or in the backend image with trivia_oracle_bot mounted).
                        integration = real backend service + SQLite + bot client + game rounds,
                        with the qbreader answer judge scripted (tests/integration/support.py), except
                        test_local_answer_checking.py, which uses the real local judge.
assets/                 Project images; excluded from the Docker builds.
secrets.example.json    Template for the gitignored secrets.json.
data/                   Runtime files, never code (gitignored; mounted at /app/data in both
                        containers): scores.md (bot), questions.db (backend, built by the sync).
```

Two Dockerfiles, both built from the repo root (`docker build -f <pkg>/Dockerfile .`); each copies
only its own package. The bot and the backend share no code: the JSON wire format in
`trivia_oracle_backend/server.py` is the contract, and `tests/contract` guards the one shared list
(the alternate subcategories).

`trivia_oracle_bot/` has `bot/` (Telegram UI), `game/` (rules and state) and
`questions.py` (HTTP client for the backend). `trivia_oracle_backend/` holds the question
data. Module by module (paths are relative to `trivia_oracle_bot/` until the
`trivia_oracle_backend/` heading):

```
__main__.py        Entry point; just calls bot.app.main().

config.py          Runtime configuration and immutable constants:
                   • TOKEN, ADMIN_USERNAME, SCORES_FILE, BACKEND_URL — read from env vars,
                     falling back to secrets.json (see "Configuration & secrets")
                   • POINTS_PER_CORRECT, POINTS_PER_WRONG, POINTS_PER_MEDAL_WRONG
                   • SCORING_MODES (key → checkbox label), SCORING_MODE_DESCRIPTIONS,
                     DEFAULT_SCORING_LABEL (shown when no mode is on)
                   • CATEGORIES list (every selectable category/subcategory label)
                   • ALL_ALT_SUBCATEGORIES, ALL_SCIENCE, ALL_ARTS helper sets
                   • DIFFICULTIES dict (display label → qbreader numeric string)
                   • ConversationHandler state IDs (SELECT_OPTION … SELECT_SCORING)

bot/               Telegram UI.
  app.py           register_handlers() wires every handler into the dispatcher;
                   main() checks TOKEN (and the local database if selected), then
                   starts polling.
  round_handlers.py Telegram side of rounds; translates update/context into calls
                   to game/round.py and its results into chat messages:
                   • start_round()         — /next handler → round.start_round()
                   • handle_round_answer() — MessageHandler (run_async) → round.submit_answer()
                   • rate_good() / rate_bad() — /good, /bad CommandHandlers (run_async) → round.submit_rating()
  keyboards.py     Pure functions that build and return InlineKeyboardMarkup objects.
                   Re-called on every render so the checkmarks always reflect current
                   state. Never mutates anything.
                   • build_category_keyboard()
                   • build_difficulty_keyboard()
                   • build_scoring_keyboard()   — ✅/☐ checkbox row per scoring mode + 💾 Save
                   • build_admin_keyboard()
  handlers.py      All Telegram handler functions for /configure and /scores.
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

game/              Game rules and state.
  settings.py      Single `settings` object holding mutable runtime state that
                   /configure can change:
                   • sentence_interval (float, seconds between sentences)
                   • answer_wait (float, seconds to wait after last sentence)
                   • selected_categories (set of strings from CATEGORIES)
                   • custom_questions (bool; the "Custom" category, off by default. It is not in
                     CATEGORIES, so "all categories" still means all qbreader ones)
                   • selected_difficulties (set of display-label strings)
                   • scoring_modes (set of SCORING_MODES keys; empty = default scoring)
  scores.py        In-memory score store (dict + threading.Lock) and helpers:
                   • load_scores()     — populate from SCORES_FILE on startup
                   • save_scores()     — write current scores to SCORES_FILE
                   • format_scoreboard() — return a human-readable scoreboard string
                   • medalist_ids()    — user IDs shown with 🥇🥈🥉 (top 3 on the board)
  spelling.py      is_lenient_spelling_match(): local fallback that accepts near-miss
                   spellings the answer judge rejected, unless the judge marked its verdict `final` (local mode).
  sentences.py     split_sentences(): breaks a tossup into the clues revealed one at a time,
                   without splitting inside abbreviations like "St. Louis" or "U.S.". The backend keeps
                   an identical copy (trivia_oracle_backend/custom/sentences.py); change both.
  round.py         Round logic. Owns `current_round` state dict and `round_lock`.
                   Knows nothing about Telegram: chat output goes through an
                   `announce(text)` callback and prompts through `on_prompt(text)`.
                   • start_round(announce, end_hint, session) → StartResult
                                           — fetches a question, spawns the round thread.
                                             `session` is per-chat storage (Telegram chat_data)
                   • submit_answer(user_id, name, given, on_prompt)
                                           — judges one answer; blocks during the check
                   • submit_rating(user_id, rating)
                                           — a player's /good or /bad on the custom question just played;
                                             blocks while the vote is sent. State: current_round["rating"]
                                             = (question id, {user_id: rating}), set by start_round for
                                             custom tossups that have an id, else None
                   • _build_filters()      — settings → questions.QuestionFilters (incl. `custom`:
                                             "exclude" | "include" | "only")
                   • _round_header()       — "📝 Custom question\nCategory: X" for custom tossups,
                                             announced as its own message before the first clue
                   • _fetch_tossup()       — async; questions.question_source.random_tossup
                   • _check_answer()       — async; questions.answer_judge.check
                   • _run_round()          — thread; drives sentence reveals + end message
                   • _points_for_correct() — points for a correct answer in this round's mode
                   • _penalty_for_wrong()  — deduction for a wrong answer in this round's mode

questions.py      (in trivia_oracle_bot/) HTTP client for the backend (aiohttp). Defines
                   QuestionFilters, Tossup, Judgement, and exposes `question_source` and
                   `answer_judge`. A 404 becomes LookupError, other failures RuntimeError.

trivia_oracle_backend/  Question data behind two interfaces (see "Question data backend").
  __init__.py      Re-exports the interfaces and both sources; reads no config.
  __main__.py      Picks the source from QUESTION_BACKEND and runs the HTTP service.
  config.py        QUESTION_BACKEND, QUESTIONS_DB, CUSTOM_QUESTIONS_DB, HOST, PORT (env vars only).
  server.py        aiohttp app: GET /health, POST /random-tossup, POST /rate-tossup, POST /record-play,
                   POST /check-answer.
  base.py          QuestionFilters, and the Tossup / Judgement / QuestionSource /
                   AnswerJudge protocols.
  api/             qbreader.org backend: QbreaderQuestionSource, QbreaderAnswerJudge.
  local/           Offline backend over data/questions.db:
    schema.sql     `sets` and `tossups` tables, incl. good_votes / bad_votes / is_custom and the play stats
                   times_played / times_answered / avg_num_clues_left_when_answered. db.connect() (and
                   record_play) add columns missing from older files; replace_set() keeps votes and play stats.
    db.py          connect(), connect_readonly(), replace_set() (one set per transaction),
                   record_vote() and record_play() (the only writers at run time: a custom question's
                   good/bad votes and its play stats).
    question_source.py  LocalQuestionSource; build_where() turns QuestionFilters into SQL.
    sync.py        CLI that copies qbreader into the database
                   (`python -m trivia_oracle_backend.local.sync`).
    answer_judge.py  LocalAnswerJudge / judge(): rejected → accepted → prompt → reject, in that
                   order. Never touches the network.
    answerline.py  parse_answerline(): answerline HTML → Answerline (accepted phrases, prompts with an
                   optional "by asking" text, rejected phrases, word_forms flag). Cached.
    matching.py    fold_char, Phrase (words + which are underlined), words_match / strings_match
                   (typo rules), Roman numerals, edit distance.
  custom/          Hand-written questions, same schema as the local database (is_custom = 1):
    CONTRIBUTING.md  Instructions for an LLM (or person) writing questions. Keep it in step with add.py.
    submissions/   One .jsonl file per set (the source of truth, committable, unlike the .db), plus an
                   optional <set>.sources.md listing each clue's sources; add.py ignores the .md files.
    add.py         `python -m trivia_oracle_backend.custom.add [--check] [files]`: validates
                   submissions and loads each into data/custom_questions.db via local/db.replace_set(custom=True),
                   which sets is_custom = 1 (so a set can later be moved into questions.db). Besides the format it
                   enforces CONTRIBUTING.md's machine-checkable writing rules (sentence count and length, lead and
                   giveaway wording, quotes, answerline markup and a <= 30-character typeable answer), and runs every
                   question and answerline through local/answer_judge (accepted or prompted strings in the question,
                   alternates the judge does not honour). All of it is an error, --check or not; only repeated
                   answers are warnings. `--check` just skips the database.
    sentences.py   Copy of the bot's game/sentences.py, so add.py sees the clues the bot will reveal (the
                   backend may not import the bot). tests/contract/test_sentence_splitter.py keeps them identical.
```

---

## Where to edit

Start here when you know what you want to change. Keep the bot and the backend apart: they only
share the JSON wire format.

| Goal | Edit | Also touch |
|------|------|------------|
| New bot command | `trivia_oracle_bot/bot/handlers.py`, register in `bot/app.py` | `tests/bot` |
| New /configure setting | `game/settings.py`, `bot/handlers.py`, `bot/keyboards.py` | `tests/bot` or `tests/game` |
| New category or difficulty | `trivia_oracle_bot/config.py` (`CATEGORIES`, `DIFFICULTIES`) | `ALL_ALT_SUBCATEGORIES` if it is an alternate subcategory; `tests/contract` |
| Different default difficulties or categories | `game/settings.py` | check the local DB has questions at those levels |
| Round timing, reveal flow, winners | `trivia_oracle_bot/game/round.py` | `tests/bot`, `tests/integration/test_round_flow.py` |
| Scoring mode or point values | `trivia_oracle_bot/config.py`, `game/round.py` (`_points_for_correct`, `_penalty_for_wrong`) | `tests/integration/test_round_flow.py` |
| Scoreboard format or storage | `trivia_oracle_bot/game/scores.py` | |
| Lenient answer matching | `trivia_oracle_bot/game/spelling.py` | `tests/game` |
| How a tossup is split into clues | `trivia_oracle_bot/game/sentences.py` **and** its copy `trivia_oracle_backend/custom/sentences.py` | `tests/contract/test_sentence_splitter.py`; the "Sentence boundaries" section of `custom/CONTRIBUTING.md` |
| Rules for custom questions (validator) | `trivia_oracle_backend/custom/add.py` **and** `custom/CONTRIBUTING.md` | `tests/backend/test_custom_questions.py`; run `--check` on every submission file |
| Message shown when `/next` fails | `trivia_oracle_bot/bot/round_handlers.py` | `StartFailureIntegrationTest` |
| Wire format (request or response fields) | `trivia_oracle_backend/server.py` **and** `trivia_oracle_bot/questions.py` | `tests/backend/test_server.py`, `tests/bot/test_backend_client.py`, `tests/integration/test_backend_http.py` |
| New endpoint | `trivia_oracle_backend/server.py` | `tests/backend`, `tests/integration` |
| Rating custom questions (prompt text, who may vote, when, and the /next gate) | `trivia_oracle_bot/game/round.py` (`submit_rating`, `RATING_PROMPT`, `_rating_still_required`, `RATING_GRACE_PERIOD`); the counting is `local/db.py` (`record_vote`) | `tests/bot/test_ratings.py`, `tests/backend/test_votes.py`, `CustomQuestionsIntegrationTest`, `RateTossupHttpTest` |
| How local questions are filtered | `trivia_oracle_backend/local/question_source.py` (`build_where`) | `tests/backend/test_local_backend.py`, `FilterIntegrationTest` |
| Custom question play stats (times played, clues left when answered) | `trivia_oracle_bot/game/round.py` (`_record_play`, `clues_left_when_answered`); the counting is `local/db.py` (`record_play`) | `tests/bot/test_play_stats.py`, `tests/backend/test_votes.py` (`RecordPlayTest`) |
| Local DB schema | `trivia_oracle_backend/local/schema.sql`, `db.py` | `tests/backend`, `tests/integration/test_sync_pipeline.py` |
| What the sync downloads | `trivia_oracle_backend/local/sync.py` | `tests/integration/test_sync_pipeline.py` |
| Calling qbreader (API mode, answer judge) | `trivia_oracle_backend/api/qbreader_api.py` | `tests/backend` |
| How local mode judges answers (required words, typo limits, directives) | `trivia_oracle_backend/local/matching.py`, `answerline.py`, `answer_judge.py` | `tests/backend/test_local_answer_judge.py` (behaviour table), `test_answer_matching.py`, `test_answerline_parser.py`, `test_answer_corpus.py` (mount `data/`) |
| Choosing between api and local | `trivia_oracle_backend/__main__.py`, `config.py` | `BackendStartupTest` |
| New environment variable | that package's `config.py` | the Configuration tables below, README, `docker-compose.yml`, `secrets.example.json` if the bot reads it |
| Container setup | the package's `Dockerfile`, `docker-compose.yml` | `.dockerignore` |
| A new shared test fake | `tests/integration/support.py` | |

Never import across the two packages (`tests/*/test_dependency_rule.py` fails if you do), and
never put game rules in `bot/` or Telegram code in `game/`.

## Known limitations

- Local answer checking (`local/answer_judge.py`) works from the answerline's structure. Free-text
  instructions ("accept equivalents", "accept any Coalition War") are not understood, typo tolerance
  cannot tell near neighbours apart (Iceland/Ireland), and `A / B` alternatives in the main answer are
  one long phrase. Local verdicts are `final`, so the bot's `game/spelling.py` never overturns them;
  in `api` mode that pass still runs after a qbreader reject. `api` mode still judges with qbreader.org.
- The local DB only holds the synced sets, but the bot defaults to HS Easy and HS Regular
  (`game/settings.py`). With a college-only DB, `/next` answers "Failed to fetch a question".
- Local mode ANDs the subcategory and alternate-subcategory fields, so a mixed selection such as
  Biology plus Poetry matches nothing. `test_subcategory_and_alternate_subcategory_selections_are_a_union`
  is an `expectedFailure`; remove the decorator when it is fixed.

---

## Import dependency graph

Inside each package imports are relative (`from ..config import ...`). The two packages never
import each other (tests/bot and tests/backend `test_dependency_rule.py` enforce it).

```
config.py
    ↑
questions.py        (imports config; aiohttp)
game/settings.py     (imports CATEGORIES, DIFFICULTIES from config)
game/scores.py       (imports SCORES_FILE from config)
    ↑
game/round.py        (imports config, questions, scores, sentences, settings, spelling)
bot/keyboards.py     (imports config, game.settings)
    ↑
bot/handlers.py      (imports config, keyboards, game.scores, game.settings)
bot/round_handlers.py (imports game.round)
    ↑
bot/app.py           (imports config, handlers, round_handlers, game.scores)
```

No circular imports. `config.py` depends on nothing local. `trivia_oracle_backend` must never
import `trivia_oracle_bot` or `telegram`, `trivia_oracle_bot` must never import
`trivia_oracle_backend`, and `game/` must never import `bot/` or `telegram`.

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
`game/round._build_filters()` splits `settings.selected_categories` across
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

Three things make "received before" hold for answers sent at the same moment:
- `bot/round_handlers.handle_round_answer` is registered with `run_async=True`. PTB v13 otherwise
  handles updates one at a time, so a second answer would wait out the first
  one's answer check and arrive after the round closed.
- After the first correct answer, the round stays open briefly so queued replies
  can register even when the local answer judge returns immediately.
- Each answer registers in `current_round["pending_checks"]` while its check is
  in flight. `_run_round` flips `active` off, then waits on `checks_settled`
  (a Condition on `scores_lock`) until pending checks reach 0, capped at
  `PENDING_CHECK_TIMEOUT`, before sending the round-end message.

`tests/bot/test_concurrent_answers.py` covers this (run it as shown under "Docker").

### Scoring modes
Scoring modes are independent toggles that can be combined. `settings.scoring_modes`
is a set of enabled keys; an empty set is default scoring (+`POINTS_PER_CORRECT`
per correct answer, no penalties). `start_round` snapshots it into
`current_round["scoring_modes"]` (a frozenset), so toggling mid-round only affects
the next round. All scoring decisions go through `_points_for_correct()` and
`_penalty_for_wrong()` in `game/round.py`.

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
1. Write a handler function in `bot/handlers.py`. If it touches round state, put the
   logic in a plain function in `game/round.py` and keep only the Telegram glue in
   `bot/round_handlers.py`.
2. Register it in `register_handlers()` in `bot/app.py` with `dp.add_handler(CommandHandler("name", fn))`.

### Add a new /configure setting (scalar value)
1. Add the attribute to `_Settings` in `game/settings.py`.
2. Add a button in `configure()` keyboard in `bot/handlers.py` with a new `callback_data`.
3. Handle that `callback_data` in `configure_select_option` — either create a new
   state or reuse `INPUT_VALUE` flow (copy the time setting pattern).
4. Update `"view_settings"` block in `configure_select_option` to display the new value.

### Add a new admin-only action
1. Add a button to `build_admin_keyboard()` in `bot/keyboards.py`.
2. Add an `elif query.data == "your_action":` branch in `configure_admin()` in `bot/handlers.py`.
   - For destructive actions, follow the existing "Are you sure?" confirmation pattern.

### Add a new category group bulk-toggle button (like Science / Arts)
1. Add a set constant (e.g. `ALL_HISTORY = {...}`) in `config.py`.
2. Add a suffix emoji for those entries in `build_category_keyboard()` in `bot/keyboards.py`.
3. Add the toggle row above the existing bulk-toggle rows in `build_category_keyboard()`.
4. Add an `elif query.data == "cat_toggle_X":` branch in `configure_toggle_category()`.

### Add new qbreader categories/subcategories
- **Subcategory values** (qbreader `Subcategory` enum): add to `CATEGORIES` only.
- **AlternateSubcategory values** (qbreader `AlternateSubcategory` enum): add to
  both `CATEGORIES` and `ALL_ALT_SUBCATEGORIES` in `config.py`.
- Check the qbreader enums with (trivia_oracle_backend/vendor/ must be on the path):
  ```python
  import trivia_oracle_backend.api  # puts trivia_oracle_backend/vendor/ on sys.path
  from qbreader.types import Subcategory, AlternateSubcategory
  list(Subcategory)
  list(AlternateSubcategory)
  ```

---

## Question data backend

`game/round.py` gets questions and judgements only through `trivia_oracle_bot.questions`, an HTTP
client for the backend service (`BACKEND_URL`):

- `questions.question_source.random_tossup(filters)` → a Tossup (`question_sanitized`,
  `answer` with HTML, `answer_sanitized`, and for custom questions `custom=True`, `category` and `id`)
- `questions.question_source.rate_tossup(id, rating, previous)` → the question's new `(good, bad)` totals
- `questions.answer_judge.check(answerline, given)` → a Judgement (`directive`,
  `directed_prompt`)

Both are async. On the backend side they are Protocols in `trivia_oracle_backend/base.py`, and
`server.py` exposes them as `POST /random-tossup` (filters as lists of strings or null → the three
tossup fields, plus `custom`, `category` and `id` for a custom question; 404 when nothing matches, 502 when the
source fails, 400 for a bad request),
`POST /rate-tossup` and
`POST /check-answer`. Change the wire format in `server.py` and `questions.py` together.

`trivia_oracle_backend/__main__.py` picks the source from `QUESTION_BACKEND`:

| `QUESTION_BACKEND` | Questions from | Answers judged by |
|--------------------|----------------|-------------------|
| `local` (default) | `QUESTIONS_DB` (SQLite) | `local/answer_judge.LocalAnswerJudge`, in-process; no network, no fallback |
| `api` | qbreader.org `/random-tossup` | qbreader.org `/check-answer` |

### Custom questions in play
`__main__.py` always gives `build_app` a second `LocalQuestionSource` on `CUSTOM_QUESTIONS_DB`, in either
`QUESTION_BACKEND` mode. `POST /random-tossup` takes `custom`: `"exclude"` (default) never draws from it,
`"only"` always does, `"include"` tries the custom or the main source first with equal odds and falls back to
the other when it has nothing. Custom draws ignore all three filters. A missing or empty custom database is a 404
for `only` and is skipped for `include`. In the bot, `settings.custom_questions` + `selected_categories` become
`custom` in `_build_filters()`: on with categories selected = `include`, on with none = `only`.

### Custom question play stats
When a custom round with an id ends, `round._record_play` sends `POST /record-play {id, clues_left}` after the
scoreboard. `clues_left` is the number of clues not yet revealed when the first correct answer was accepted
(`hourglasses - 1`, so answering on the last clue, or after it, is 0), or null when nobody answered.
`local/db.record_play` adds 1 to `times_played`, and for an answered round also adds 1 to `times_answered` and
folds `clues_left` into `avg_num_clues_left_when_answered`, a running mean over answered rounds (NULL until the
first one). Only `is_custom = 1` rows count (404 otherwise). A failed report is logged and dropped; it never
affects the round.

### Drawing custom questions
The bot sends `exclude_custom_ids` on `/random-tossup`: the ids of custom questions the chat has played this session
(`("custom_id", id)` keys in `chat_data["seen_tossups"]`, which resets after `SESSION_TIMEOUT` without a /next and on
restart). The custom draw (`question_source._balanced_tossup`, `QuestionFilters.balanced`) skips those ids and takes
the selected custom categories in turn: it picks, at random among ties, a category with the fewest played ids that
still has an unplayed question, then the question with the lowest `times_played` in it (random among ties). Once
every matching custom question is excluded it ignores the list, so a played one comes back; `round._fetch_fresh_tossup`
sees an id it already has and drops the session's custom keys (a new cycle). It still retries a custom question whose
primary answer was already asked in a different wording, sending the turned-down id with the next draw. Ordinary
questions have no server-side exclusion, so they redraw (up to `QUESTION_FETCH_ATTEMPTS`) while the question text was
already seen — the whole point being to dodge a repeat when the selected categories still have a fresh one to give.
When a narrow category selection runs out of those (every draw within the attempt budget lands on something already
seen), `_fetch_fresh_tossup` stops chasing freshness and accepts the last draw instead: getting a question out matters
more than the uniform-randomness rule, so `/next` never refuses to start just because the pool is exhausted. That also
drops the ordinary keys from the session (a new cycle), the same way a played-out custom category does.
The custom-vs-ordinary choice in "include" mode is still the server's 50/50 coin.

### Rating custom questions
A custom round's end message ends with "Please rate the question /good or /bad" (`round.RATING_PROMPT`).
`POST /rate-tossup {id, rating: "good"|"bad", previous: "good"|"bad"|null}` adds one vote to that custom
question's `good_votes` / `bad_votes` (`local/db.record_vote`) and withdraws `previous`, so a changed vote
moves instead of doubling; counts never go below 0. Only `is_custom = 1` rows can be rated (404 otherwise, and
when there is no custom database; the file is never created). The backend just counts. Votes do not steer custom
draws (see "Drawing custom questions"). The one-vote-per-player
rule lives in the bot: `round.submit_rating` keeps `{user_id: rating}` for the round, ignores a repeat, sends a
change with `previous` set, and only records a vote once the backend accepted it. `ratings_lock` is held while a
vote is in flight, so one player's votes reach the backend in the order they were made. The rating state is
replaced when the next round starts, which is also when voting closes; a new round lets the player vote again,
even on the same question. `custom_questions.db` is therefore no longer read-only at run time: the backend's
`./data` mount must stay writable.

`round.start_round` refuses to start (`StartResult.NEEDS_RATING`) right after a custom round whose `rating` slot
is still `(id, {})` (nobody has voted) and less than `RATING_GRACE_PERIOD` (10s) has passed since `ended_at`
(`round._rating_still_required`). `round_handlers.start_round` replies to that player with `NEEDS_RATING_TEXT`
("Please rate the question first /good or /bad") instead of the usual `announce`. The gate never fires while a
round is active (round_lock's `StartResult.BUSY` already covers that) and is a no-op for ordinary rounds, whose
`rating` is always `None`.

The bot tests patch `round._fetch_tossup` / `round._check_answer`, so they are backend-independent;
`tests/bot/test_backend_client.py` covers the client against a stand-in server, and
`tests/backend/` covers the service and the local source on a temporary database.

### Local database and sync
`python -m trivia_oracle_backend.local.sync` crawls `/set-list`, then
`/num-packets` and `/packet?questionTypes=tossups` for each set, sequentially with
a 0.2 s gap (qbreader allows 20 requests/s). Each set is written in one
transaction and only then recorded in `sets`, so re-running the command resumes
where it stopped. Options: `--sets NAME…`, `--limit N`, `--refresh`, `--delay S`,
`--db PATH`. A set takes ~5 s; all ~700 sets take about an hour and ~300 MB.
Only tossups are stored, and the question HTML is dropped (the bot shows
`question_sanitized`).

### Filter semantics
`local/question_source.build_where()` reproduces qbreader's server query rather
than the obvious one. All filters are ANDed. An alternate subcategory adds its
parent category or subcategory (the vendored client's `category_correspondence`;
`tests/backend` checks the copy stays in sync), and an alternate-subcategory
filter also admits tossups with no alternate subcategory. Keep that behaviour so
switching backends doesn't change which questions a /configure selection draws.

## qbreader API notes

- Library: local `trivia_oracle_backend/vendor/qbreader/` folder (vendored, not pip-installed).
  Only `trivia_oracle_backend/api/` imports it (and tests/backend, to
  compare category mappings). The sync script calls the HTTP API directly with `requests`.
  Copied from qbreader/python-module v1.0.1 with one patch: `AlternateSubcategory.MUSICALS`
  added to the Other Fine Arts mapping in `_api_utils.py`. Keep `trivia_oracle_backend/vendor/qbreader/LICENSE` with it.
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
| `TELEGRAM_TOKEN` | yes | — | `bot.app.main()` exits with a clear message if missing. Not needed by the sync script. |
| `ADMIN_USERNAME` | no | `None` | Telegram username without `@`. `None` locks Admin Settings for everyone. |
| `SCORES_FILE` | no | `<repo>/data/scores.md` | Parent directory is created on first save. |
| `BACKEND_URL` | no | `http://localhost:8080` | Question backend the bot calls. Compose sets `http://backend:8080`. |

The backend has its own settings, read from environment variables only (`trivia_oracle_backend/config.py`):

| Name | Default | Notes |
|------|---------|-------|
| `QUESTION_BACKEND` | `local` | `local` or `api`. With `local`, the backend refuses to start if `QUESTIONS_DB` is missing. |
| `QUESTIONS_DB` | `<repo>/data/questions.db` | Written by the sync script, opened read-only per request by the service. |
| `CUSTOM_QUESTIONS_DB` | `<repo>/data/custom_questions.db` | Written by `custom/add.py` and, for players' votes and play stats, by `POST /rate-tossup` and `POST /record-play`; opened per request, so it may appear or change while the service runs. |
| `HOST`, `PORT` | `0.0.0.0`, `8080` | Where the service listens. Compose does not publish it. |

`secrets.example.json` shows the format. To add a new setting, read it in
`config.py` with `_setting("YOUR_KEY")`, expose it as a module-level constant,
and document it here, in the README table, and in `secrets.example.json`.

**Never commit real secrets.** This repo is public. `secrets.json`, `.env`, and
`data/` (player names + Telegram IDs) are gitignored and dockerignored. Secrets
reach the bot container at runtime (`-e`, or Compose mounting `./secrets.json` read-only), never copied
into an image. The backend container gets no secrets.

---

## Docker

```bash
docker compose up -d                        # backend on ./data/questions.db
QUESTION_BACKEND=api docker compose up -d   # backend on the qbreader API instead
docker compose run --rm --no-deps backend python -m trivia_oracle_backend.local.sync   # run by hand
```

Watch the console with `docker compose logs -f --tail 50 bot` (or `docker logs -f --tail 50 trivia-oracle-bot-1`).
The bot logs each round's correct answer as `Answer: ...` (`game/round.py`); it does not log players' guesses or verdicts.

Two images, `trivia-oracle-bot` and `trivia-oracle-backend`, built from the repo root with
`docker build -f trivia_oracle_bot/Dockerfile .` and `docker build -f trivia_oracle_backend/Dockerfile .`.
Each contains only its own package. The bot mounts `./secrets.json` read-only and `./data`
(scores); the backend mounts `./data` (questions.db) and has no published port, so only the bot can
reach it on the Compose network. Mount `/app/data`, not `/app`, since mounting over `/app` hides the code.

Run the whole suite (tests are not baked into the images; the script mounts them) with:
```bash
python3 scripts/run_tests.py
```
It builds both images, runs all five test directories each in the right image/mounts, and prints one
consolidated report — a pass/fail line per directory, full tracebacks only for failures, and a
ready-to-paste rerun command for just the failing test(s). Use this instead of separate `docker run`
calls: it's the same coverage in far less output to read. `python3 scripts/run_tests.py backend` runs
one group; `python3 scripts/run_tests.py tests.backend.test_votes.VotesTest.test_x` reruns one test by
the id printed in a failure; `--no-build` skips the image build; `--with-data backend` also checks every
answerline in `data/`. See `scripts/run_tests.py` for the raw `docker run`/`unittest discover` commands
it wraps per group, if you need to run one by hand.

The old single image `chewterence/trivia-oracle` on Docker Hub predates this split and is not
updated by it. Publishing the new images is a separate decision for the maintainer.

---

## Running locally

```bash
pip install -r trivia_oracle_backend/requirements.txt -r trivia_oracle_bot/requirements.txt
cp secrets.example.json secrets.json   # then fill it in
python -m trivia_oracle_backend        # terminal 1
python -m trivia_oracle_bot            # terminal 2
```

Only one process may poll a given token. A second instance gets a Telegram
`Conflict` error and `error_handler` exits it.
