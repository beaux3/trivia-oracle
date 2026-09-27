# Writing custom questions (instructions for AI models and people)

Your job: turn a request like *"Science, something fun about space"* into **tossup
questions** for the TriviaOracle Telegram bot, in the style of qbreader quizbowl. You do
it in three stages, and **every fact must be checked online before it goes into a question**.
The result is a JSONL file in this folder's `submissions/` directory. A script validates the
file and loads it into the custom question database. You never touch the database directly.

The bot reads a tossup aloud **one sentence at a time**. Players can buzz in with a
typed answer after any sentence, so early sentences must be hard and clues must get
easier as the question goes on. Whoever answers earliest and correctly scores most.

## Workflow

The requester gives you a **category** (for example History, or Science / Physics) and a
rough **vibe** (for example "weird inventions", "90s pop nostalgia", "hard, for a college
crowd"). If the category, the vibe, the difficulty (see the scale below) or the number of
questions is missing, ask once; otherwise assume difficulty 3–5 and 10 questions.

### Stage 1: propose answers (stop and wait for approval)

Before writing any question, brainstorm **about 1.5–2x as many candidate answers as you need**
and show them to the requester as a numbered list. For each, give:

- the answer, and its subcategory (and alternate subcategory if any);
- one line on why it fits the vibe;
- a rough difficulty guess.

Choose answers that fit the category and vibe, that have **several distinct, well-documented
clues** (a tossup needs 4–7), and that are varied (not five painters in a row). Skip answers
you could not find good sources for. Then **stop** and let the requester cut, swap or add
answers. Do not go on to stage 2 until they approve the list (or say "go ahead" / "you pick").

### Stage 2: research every approved answer online

For each approved answer, look the facts up on the web with whatever search or browsing tool
you have. Your memory is not a source.

- Find **at least two independent, reputable sources** for each clue you plan to use (for
  example an encyclopedia plus a primary or academic source; two sites that copy each other
  count as one). Prefer encyclopedias, museum, university, government and publisher pages over
  blogs, forums, quote sites and AI-generated pages.
- Check dates, spellings of names, numbers, and attributions ("first", "only", "largest") in the
  sources themselves. Superlatives are the most often wrong; if sources disagree or you cannot
  confirm one, do not use that clue.
- Note each clue's sources. If an answer ends up with fewer than 4 confirmed clues, replace the
  answer (tell the requester which one and why) instead of padding it with unverified claims.
- Confirm the **answerline** too: the standard name, common alternate names and spellings,
  and any commonly confused answer that should be rejected.
- Do **not** copy wording from the sources or from qbreader. Use them for facts only.

If you have **no way to browse the web**, say so at the start. You may still do stage 1, but you
must not write questions for the database: tell the requester that stage 2 needs a browsing
tool. (If they ask you to write them anyway, write the file, tell them plainly that the facts are
**unverified**, and do not load it into the database.)

### Stage 3: write, record sources, validate, load

1. Write the questions to `trivia_oracle_backend/custom/submissions/<set_name>.jsonl`.
   - The file name (without `.jsonl`) becomes the **set name** shown in the database, so make it
     descriptive: `space_fun_batch_01.jsonl`, `terence_general_knowledge.jsonl`.
     Use letters, digits, `_` and `-`.
   - Never overwrite or delete another contributor's file. Pick a new name or, to add more
     questions, append lines to your own file.
2. Write `trivia_oracle_backend/custom/submissions/<set_name>.sources.md` next to it. It is
   not loaded anywhere; it lets a human spot-check your work. Format, per question in file order:
   ```
   ## 1. angular momentum
   - "Conserved in the absence of external torques": https://...  ; https://...
   - "SI units kg m^2 / s": https://...  ; https://...
   ```
   Put the full URLs of at least two sources next to every clue. Never invent a URL and never
   list one you did not actually open.
3. Validate from the repo root:
   ```
   python -m trivia_oracle_backend.custom.add --check trivia_oracle_backend/custom/submissions/<set_name>.jsonl
   ```
   Fix every reported problem (each has a line number) and run it again until it says the
   questions are valid. A file with any invalid line is rejected as a whole. The validator only
   checks format, not facts, so do the self-check below yourself.
4. Load it (only if the requester asked, and only if every clue was verified in stage 2):
   ```
   python -m trivia_oracle_backend.custom.add trivia_oracle_backend/custom/submissions/<set_name>.jsonl
   ```
   This writes to `data/custom_questions.db`. Loading a file replaces that set, so it is safe
   to run repeatedly. The `.jsonl` files are the source of truth; the database can always be
   rebuilt by running the command with no file arguments.
5. Report back: how many questions, the answers (as a list), any answer you dropped and why,
   anything you were unsure about, and the paths of the two files. Ask the requester to skim the
   sources file.

If you cannot run commands, just write the files and say they have not been validated.

## File format

One JSON object per line, no trailing commas, no blank lines needed, no comments.
Exactly these fields:

| Field | Required | Meaning |
|---|---|---|
| `category` | yes | One of the categories below |
| `subcategory` | yes | Must belong to the category (table below) |
| `alternate_subcategory` | no | A finer topic, or `null`. Only for the combinations below |
| `difficulty` | yes | Integer 1–10, see the scale below |
| `question` | yes | Plain text, several sentences, no HTML |
| `answer` | yes | The answerline, with `<b><u>` marking what a player must say |

Do **not** add other fields (ids, set names, numbers, dates are filled in for you; unknown
fields are rejected). The database schema is the one in `../local/schema.sql`, the same as the
qbreader copy. Two things in it are never written in a submission file: `good_votes` /
`bad_votes` (start at 0, filled in from player feedback) and `is_custom` (always set to 1 for
questions loaded from here, so they can be told apart from qbreader questions later).

Example (each object is really one line):

```json
{"category": "Science", "subcategory": "Physics", "alternate_subcategory": null, "difficulty": 5, "question": "This quantity is conserved in the absence of external torques. Its SI units are kilogram meters squared per second. For a point particle, it equals the cross product of position and linear momentum. A figure skater spins faster after pulling in her arms because this quantity stays constant. Kepler's second law, the equal-areas law, is a consequence of its conservation. For 10 points, name this rotational analogue of linear momentum.", "answer": "<b><u>angular momentum</u></b> [prompt on <u>momentum</u>; do not accept or prompt on \"linear momentum\"]"}
{"category": "Literature", "subcategory": "American Literature", "alternate_subcategory": "Long Fiction", "difficulty": 4, "question": "A character in this novel keeps a green light in view across the bay and hosts lavish parties every Saturday night. The narrator, Nick Carraway, rents a small house next door to that character. A yellowed advertisement showing a pair of spectacles looms over the Valley of Ashes. Daisy Buchanan is the love interest at the center of the plot. For 10 points, name this F. Scott Fitzgerald novel about Jay Gatsby.", "answer": "<u>The Great Gatsby</u>"}
```

## Categories, subcategories and alternate subcategories

| category | allowed `subcategory` values |
|---|---|
| Literature | American Literature, British Literature, Classical Literature, European Literature, World Literature, Other Literature |
| History | American History, Ancient History, European History, World History, Other History |
| Science | Biology, Chemistry, Physics, Other Science |
| Fine Arts | Visual Fine Arts, Auditory Fine Arts, Other Fine Arts |
| Pop Culture | Movies, Music, Sports, Television, Video Games, Other Pop Culture |
| Religion, Mythology, Philosophy, Social Science, Current Events, Geography, Other Academic, Singapore | the same word as the category (e.g. category `Mythology`, subcategory `Mythology`) |

`alternate_subcategory` is optional; use `null` when none fits. Allowed only with these parents:

| alternate_subcategory | category / subcategory it requires |
|---|---|
| Drama, Long Fiction, Poetry, Short Fiction, Misc Literature | Literature / any literature subcategory |
| Math, Astronomy, Computer Science, Earth Science, Engineering, Misc Science | Science / Other Science |
| Architecture, Dance, Film, Jazz, Musicals, Opera, Photography, Misc Arts | Fine Arts / Other Fine Arts |
| Anthropology, Economics, Linguistics, Psychology, Sociology, Other Social Science | Social Science / Social Science |
| Beliefs, Practices | Religion / Religion |

`Singapore` is a custom-only category (qbreader has none): everything about Singapore (history,
food, slang, places, people) goes in it, with `subcategory` `"Singapore"` and `alternate_subcategory`
`null`, whatever the topic. If the requester names a category, use exactly that one.

Note that Math, Astronomy etc. have `subcategory` **"Other Science"**, and Film, Opera etc.
have **"Other Fine Arts"**. Choose the category by the *subject of the answer*, not the
question's angle (a question about a painter's life whose answer is the painter is Fine Arts).

## Difficulty scale

| Value | Level | Typical audience / feel |
|---|---|---|
| 1 | Middle school | Well-known basics |
| 2 | Easy high school | Common school knowledge |
| 3 | Regular high school | Solid general knowledge |
| 4 | Hard high school | Needs real subject study |
| 5 | High school nationals | Very strong high schoolers |
| 6 | Easy college | Intro college quizbowl |
| 7 | Regular college | Standard college quizbowl |
| 8 | Hard college | Deep, specialised clues |
| 9 | College nationals | Very obscure leads |
| 10 | Open | Hardest, near-expert |

Default to 3–5 for a general chat group unless told otherwise. Difficulty is how obscure the
answer and the *first* clues are; the last clue should always be easier. Do not use 0
(unrated); the validator rejects it.

## How to write a good tossup

**Structure (pyramidal).** 4–7 sentences, roughly 100–250 words.
- Sentence 1: the hardest clue, still uniquely identifying the answer to an expert.
- Middle sentences: progressively better-known clues.
- Last sentence ("giveaway"): a clue almost anyone who knows the answer gets, ending with
  **"For 10 points, name this ..."** (or "identify", "give this ...").
- One clue per sentence. The bot splits on sentence boundaries, so every sentence should stand
  alone. Avoid one enormous sentence with many clauses.

**No answer leaks.** The answer (or an obvious part of it) must not appear in the question
before the last sentence. Use "this man", "this novel", "this element", and so on. Refer to
the answer as `this <thing>`, never by name.

**Unique answer.** Every clue must be true of the answer and, taken together, the question must
point to exactly one answer. Clues that also fit a more famous alternative belong later, or need
an extra distinguishing detail.

**Only true, verified facts.** This is the most important rule. Every claim must have been
confirmed in stage 2 against at least two independent sources. If you are not sure of a date,
name, number or attribution, drop that clue or choose another answer. A wrong "fact" gets
memorised by players and cannot be detected by the validator. Do not invent people, works, or
events, and do not write a clue just because it "sounds right".

**Original text.** Write the clues yourself. Do not copy tossups from qbreader, packets, or
other question sets, and do not reproduce copyrighted passages. Facts are free to use; wording
is not.

**Plain text question.** No HTML, no markdown, no numbering, no "TOSSUP:" prefix. Use normal
quotes and dashes. Spell out enough of the context that the sentence works when read on its
own.

**Variety.** Within one file, vary categories, subcategories and answer types (people, works,
places, concepts), do not repeat an answer, and do not reuse the same clue twice.

## Writing the answerline

The answerline (`answer`) is what the bot uses to judge typed answers. It is HTML-ish text in
the qbreader style.

1. Wrap the **required** part in `<b><u>...</u></b>` (or just `<u>...</u>`). Players must
   say at least this, so keep it to the shortest form a knowledgeable person would give
   (`Josip Broz <b><u>Tito</u></b>` needs only "Tito"). With no underline at all the bot
   requires the whole answer, so always underline.
2. Put extra instructions in **square brackets** after it, separated by semicolons:
   - `[or Alternate name; accept Another name]` – other correct answers
   - `[prompt on <u>partial</u>]` – a too-vague or partial answer makes the bot ask for more
   - `[do not accept or prompt on "wrong thing"]` – a commonly confused answer that is wrong
3. Anything in round brackets that does not begin with accept/prompt/do-not-accept is
   treated as a comment (pronunciation, clarification) and ignored.
4. Add reasonable alternate names, abbreviations, spellings and titles ("accept **WWI** or
   **World War One**"), but only genuinely equivalent answers.
5. For titles, underline the part that identifies the work (`<u>The Great Gatsby</u>`, or
   `<u>Lord of the Rings</u>` when a leading "The" is not needed).
6. Inside JSON, escape double quotes as `\"`. It is easier to use single quotes or “curly”
   quotes in the text and avoid escapes.
7. Never put the question text, explanations, or citations in `answer`.

Good:
`<b><u>Vincent van Gogh</u></b> [or <b><u>Van Gogh</u></b>; prompt on <u>Vincent</u>]`
`<b><u>photosynthesis</u></b> [accept word forms; prompt on <u>respiration</u> by asking "which process converts light energy?"]`

Bad: `Vincent van Gogh` (no underline, so a player must type the full name exactly).

## Self-check before you finish

- [ ] Valid JSON on every line, exactly the six allowed fields, saved as `.jsonl`.
- [ ] The requester approved the answer list (stage 1).
- [ ] Every clue was checked against two independent sources you actually opened (stage 2), and
      they are listed in the `.sources.md` file.
- [ ] No claim relies on memory alone, and no superlative ("first", "only", "largest") is unconfirmed.
- [ ] Answer not named in the question; the last sentence is the giveaway.
- [ ] Category / subcategory / alternate_subcategory combination matches the tables above.
- [ ] Difficulty roughly matches how obscure the *first* clue is.
- [ ] Every `answer` underlines its required part with `<b><u>` and sensible alternates and prompts.
- [ ] No duplicate questions or answers within the file; nothing copied from qbreader.
- [ ] `python -m trivia_oracle_backend.custom.add --check <file>` passes.

## Do not

- Do not edit the database file, `local/schema.sql`, the sync script, or any code to make
  validation pass. If the validator seems wrong, report it instead.
- Do not write questions about private individuals, or content that is hateful, sexual, or
  graphic. Keep it suitable for a general Telegram group.
- Do not put secrets or personal data (names, Telegram IDs) into questions.
