# Writing custom questions (instructions for AI models and people)

Your job: write **tossup questions** for the TriviaOracle Telegram bot and save them
as a JSONL file in this folder's `submissions/` directory. A script checks the file
and loads it into the custom question database. You never touch the database
directly.

The bot reads a tossup aloud **one sentence at a time**. Players can buzz in with a
typed answer after any sentence, so early sentences must be hard and clues must get
easier as the question goes on. Whoever answers earliest and correctly scores most.

## Workflow

1. Pick a topic mix and difficulty (ask the requester if they did not say). If no
   count is given, write 20 questions.
2. Write the questions to `trivia_oracle_backend/custom/submissions/<set_name>.jsonl`.
   - The file name (without `.jsonl`) becomes the **set name** shown in the database, so make it
     descriptive: `terence_general_knowledge.jsonl`, `ai_science_batch_01.jsonl`.
     Use letters, digits, `_` and `-`.
   - Never overwrite or delete another contributor's file. Pick a new name or, to add more
     questions, append lines to your own file.
3. Validate from the repo root:
   ```
   python -m trivia_oracle_backend.custom.add --check trivia_oracle_backend/custom/submissions/<set_name>.jsonl
   ```
   Fix every reported problem (each has a line number) and run it again until it says the
   questions are valid. A file with any invalid line is rejected as a whole.
4. Load it (only if asked, or if you have a working environment for it):
   ```
   python -m trivia_oracle_backend.custom.add trivia_oracle_backend/custom/submissions/<set_name>.jsonl
   ```
   This writes to `data/custom_questions.db`. Loading a file replaces that set, so it is safe
   to run repeatedly. The `.jsonl` files are the source of truth; the database can always be
   rebuilt by running the command with no file arguments.

If you cannot run commands, just write the file and say it has not been validated.

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
fields are rejected). The database schema is the qbreader copy's (`../local/schema.sql`) plus
`good_votes` and `bad_votes` columns on each tossup. They start at 0 and are filled in from
player feedback, so never write them in a submission file.

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
| Religion, Mythology, Philosophy, Social Science, Current Events, Geography, Other Academic | the same word as the category (e.g. category `Mythology`, subcategory `Mythology`) |

`alternate_subcategory` is optional; use `null` when none fits. Allowed only with these parents:

| alternate_subcategory | category / subcategory it requires |
|---|---|
| Drama, Long Fiction, Poetry, Short Fiction, Misc Literature | Literature / any literature subcategory |
| Math, Astronomy, Computer Science, Earth Science, Engineering, Misc Science | Science / Other Science |
| Architecture, Dance, Film, Jazz, Musicals, Opera, Photography, Misc Arts | Fine Arts / Other Fine Arts |
| Anthropology, Economics, Linguistics, Psychology, Sociology, Other Social Science | Social Science / Social Science |
| Beliefs, Practices | Religion / Religion |

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

**Only true, verifiable facts.** This is the most important rule. Write only claims you are
confident are correct. If you are not sure of a date, name, number or attribution, drop that clue
or choose another answer. A wrong "fact" gets memorised by players and cannot be detected by
the validator. Do not invent people, works, or events. When unsure, pick a well-documented
answer instead.

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
- [ ] Every fact is one you are sure about; no invented details.
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
