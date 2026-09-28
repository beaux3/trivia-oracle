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

- Find **at least one source** for each clue you plan to use. Prefer it to be *authoritative*
  when you have a choice:
  - *Authoritative* means the primary source itself (the work, the paper, the law, official
    records) or a publisher with editorial responsibility for the subject: Britannica and other
    edited reference works, national biographies, museum, university, government and publisher
    pages, peer-reviewed articles, newspapers of record.
  - Wikipedia and sites that copy or paraphrase it (mirrors, fandom wikis, quiz and "fun fact"
    sites, AI-generated summaries) are acceptable as your one source. Do not use blogs, forums or
    quote sites.
- Check dates, spellings of names, numbers, and attributions ("first", "only", "largest") in the
  sources themselves. Superlatives are the most often wrong; if sources disagree or you cannot
  confirm one, do not use that clue.
- Note each clue's sources. If an answer ends up with fewer than 4 confirmed clues, replace the
  answer (tell the requester which one and why) instead of padding it with unverified claims.
- Confirm the **answerline** too: the standard name, common alternate names and spellings,
  and any commonly confused answer that should be rejected.
- Do **not** copy wording from the sources. Do not use qbreader or other quizbowl questions as
  sources: the bot already plays qbreader's questions, and old tossups contain errors.

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
   - You do **not** need to create a new `_batch_NN` file every time. A new numbered batch (or
     new file) is for a genuinely new topic; if a submission file for this same topic already
     exists, append the new questions to it instead of starting another batch.
2. Write `trivia_oracle_backend/custom/submissions/<set_name>.sources.md` next to it. It is
   not loaded anywhere; it lets a human spot-check your work. Format, per question in file order:
   ```
   ## 1. angular momentum
   - "Conserved in the absence of external torques": https://...
   - "SI units kg m^2 / s": https://...
   ```
   Put the full URL of at least one source next to every clue. Never invent a URL and never list
   one you did not actually open.
3. Validate from the repo root:
   ```
   python -m trivia_oracle_backend.custom.add --check trivia_oracle_backend/custom/submissions/<set_name>.jsonl
   ```
   Fix every reported problem (each has a line number) and run it again until it says the
   questions are valid. A file with any invalid line is rejected as a whole, with or without
   `--check`. Besides the format, it checks the rules in this file that a program can see (see
   "What the validator checks" below), including any question that gives its own answer away. It
   only warns about an answer already used on another line or in another submission file: change
   that answer unless the requester wants the repeat. It does not check facts, so do the
   self-check below yourself.
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
{"category": "Science", "subcategory": "Physics", "alternate_subcategory": null, "difficulty": 5, "question": "Kepler's second law, the equal-areas law, follows from the conservation of this quantity for a planet orbiting the Sun. Its SI units are kilogram meters squared per second. For a point particle, it is the cross product of the position vector with mass times velocity. It is conserved in the absence of external torques. A figure skater spins faster after pulling in her arms because this quantity stays constant. For 10 points, name this rotational counterpart of mass times velocity.", "answer": "<b><u>angular momentum</u></b> [prompt on <u>momentum</u>; do not accept or prompt on “linear momentum”]"}
{"category": "Literature", "subcategory": "American Literature", "alternate_subcategory": "Long Fiction", "difficulty": 4, "question": "In this novel, a faded billboard showing a huge pair of spectacles looms over the Valley of Ashes. Myrtle Wilson is killed by a car that, the narrator later learns, was being driven by Daisy Buchanan. The narrator, Nick Carraway, rents a small house next door to a mansion famous for its lavish parties. Its title character reaches out toward a green light at the end of Daisy's dock across the bay. For 10 points, name this 1925 F. Scott Fitzgerald novel set on Long Island during the Jazz Age.", "answer": "<u>The Great Gatsby</u>"}
```

## Categories, subcategories and alternate subcategories

| category | allowed `subcategory` values |
|---|---|
| Literature | American Literature, British Literature, Classical Literature, European Literature, World Literature, Other Literature |
| History | American History, Ancient History, European History, World History, Other History |
| Science | Biology, Chemistry, Physics, Other Science |
| Fine Arts | Visual Fine Arts, Auditory Fine Arts, Other Fine Arts |
| Pop Culture | Movies, Music, Sports, Television, Video Games, Other Pop Culture |
| Religion, Mythology, Philosophy, Social Science, Current Events, Geography, Other Academic, Singapore, Snowsports, Memes, Japan, Anime, Cultivation / Returner Slop | the same word as the category (e.g. category `Mythology`, subcategory `Mythology`) |

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
`null`, whatever the topic. `Snowsports` is a custom-only category in the same way (skiing and
snowboarding: gear, lifts, resorts, brands, technique, culture), with `subcategory` `"Snowsports"`. So is `Memes` (internet memes, slang and viral trends),
with `subcategory` `"Memes"`. So is `Japan` (anything about Japan not already covered by a qbreader
category: places, food, transit, language, culture), with `subcategory` `"Japan"`.
If the requester names a category, use exactly that one.

`Anime` is also custom-only: use `category` and `subcategory` `"Anime"`, with
`alternate_subcategory` `null`. Anime questions are played through the existing **Custom**
toggle; this label is not a separate qbreader filter or a new settings button. Follow the
requester's scope for the answers and clues (for example, anime titles only, with no
manga-only details).

`Cultivation / Returner Slop` is custom-only in the same way: Korean manhwa, webtoons and web novels,
Chinese web novels (cultivation and otherwise), their shared tropes and in-world mechanics (murim,
cultivation realms, regression, system screens), and the reading ecosystem around them (platforms,
translation and piracy sites, industry news). Use the full name, slash included, as both `category`
and `subcategory`, with `alternate_subcategory` `null`. Answers can be titles, characters, mechanics,
authors or sites; when several answers in a file come from one series, check that no question names
another question's answer.

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

**Structure (pyramidal).** 4–7 sentences of about 15–30 words each, roughly 80–180 words in all.
The validator counts sentences the way the bot splits them and rejects fewer than 4 or more
than 7, any sentence under 5 or over 40 words, and a question under 60 or over 200 words.
- Sentence 1 (the "lead"): the hardest clue, and one that **an expert in the subject could
  answer from that sentence alone**. Being unique is not enough. An exact attendance figure, a
  catalogue number or a minor relative's name may fit only one answer, but nobody would buzz on
  it. If you cannot picture a specialist recognising the clue, it is too obscure for a lead.
  The lead must also point at the answer: say "this novel", "this man" and so on (or begin
  with "Its", "His", "Her" or "Their", or say "here" for a place). A lead that only talks about
  something related ("The original photograph first circulated ...", "Later in the same
  ceremony ...") leaves players guessing what is being asked, and the validator rejects it.
- Middle sentences: progressively better-known clues (see "Ordering clues by difficulty").
- Last sentence ("giveaway"): a clue almost anyone who knows the answer gets, starting with
  **"For 10 points, name this ..."** (or "identify this", "give the ..."). "For 10 points" appears
  in this sentence and nowhere else. The giveaway must not contain the answer either (see "No
  answer leaks").
- One clue per sentence, or at most two closely linked facts (a work and its year, an event and
  where it happened). The bot shows each sentence and then waits the same time before the next,
  so a long sentence full of clues reveals easy and hard information at once and flattens the
  pyramid.

**Ordering clues by difficulty.** Judge how widely known each clue is, not how hard it feels to you.
- Where the fact appears: in the opening paragraph of the encyclopedia article, in school
  textbooks, or in nearly everything written about the answer means late. Only in specialist
  or primary sources means early.
- Who would know it: anyone who has heard of the answer (giveaway); someone who has studied the
  subject (middle); a specialist (lead).
- Test the order: a player who knows a clue should almost certainly know every clue after it.

Do not search or read qbreader while writing. The bot's main question database comes from it, so
a custom question must not repeat one there, and reading those tossups makes that likely.

**No answer leaks, anywhere.** No string that the answerline accepts or prompts on may appear
anywhere in the question, **the giveaway included**. That means:
- the underlined answer and every word of it that is underlined;
- every alternate in `[or ...]` / `[accept ...]`: other names, spellings, abbreviations,
  symbols and translations;
- every string in `[prompt on ...]`;
- other forms of all of these (photosynthetic or photosynthesize for photosynthesis,
  Gatsby's for Gatsby).

Refer to the answer as "this man", "this novel", "this element", and so on. Typical leaks:
"name this element, also called wolfram" (an alternate), "name this Fitzgerald novel about Jay
Gatsby" (an underlined word), "name this anthem, whose title means Onward Singapore" when
"Onward Singapore" is an accepted alternate.

Allowed:
- Indirect clues that point to a name without containing it: an etymology ("its name comes
  from the Swedish for 'heavy stone'"), or a translation, **unless** the answerline accepts that
  translation.
- Strings the answerline lists under "do not accept", as long as they contain no accepted or
  prompted word. "Chloroplast" may appear in a question on mitochondria that rejects it, but
  "linear momentum" may not appear in a question on angular momentum, because "momentum" is
  part of the answer.

If the noun you want for "this ___" is something you would prompt on ("this organelle"), do not
prompt on it: the question has already told players that much.

The validator tests this with the local answer checker (the one the bot uses unless it is set to
judge with qbreader.org): it fails a question if any run of its words would be accepted as the
answer, or would be prompted on. That includes the checker's typo tolerance, so a different word
one letter away from a long answer word ("reader" for Reaper) counts too. Reword the clue, or, if
the word is genuinely different, reject it in the answerline (`[do not accept “reader”]`).

**Unique answer.** Every clue must be true of the answer and, taken together, the question must
point to exactly one answer. Clues that also fit a more famous alternative belong later, or need
an extra distinguishing detail.

**Only true, verified facts.** This is the most important rule. Every claim must have been
confirmed in stage 2 against a source you actually opened. If you are not sure of a date, name,
number or attribution, drop that clue or choose another answer. A wrong "fact" gets memorised by
players and cannot be detected by the validator. Do not invent people, works, or events, and do
not write a clue just because it "sounds right".

**Original text.** Write the clues yourself from your stage 2 sources. Do not copy tossups from
qbreader, packets, or other question sets, and do not reproduce copyrighted passages. Facts
are free to use; wording is not.

**Plain text question.** No HTML, no markdown, no links, no numbering, no "TOSSUP:" prefix, no
tabs, line breaks, invisible characters or double spaces, and it ends with `.`, `?` or `!`.
Spell out enough of the context that the sentence works when read on its own. A
fill-in-the-blank clue may write the blank as `___`.

**Quotes.** The same rule applies to `question` and `answer`: use double quotes, either curly
(“...”, no escaping needed) or straight (written `\"` inside JSON), and do not open with a
straight `"` and close with a curly `”`. Never use single quotes (`'...'` or `‘...’`) as
quotation marks; apostrophes ("Kepler's") are fine. In `answer` the parser does not treat
single quotes as quotes, so a comma, "or" or directive word inside them splits the text
(`do not accept 'Romeo, Juliet'` rejects "Romeo" and "Juliet" separately). Quote marks never
affect whether a typed answer matches; they are ignored in the comparison. The validator
rejects single-quoted quotations, mismatched pairs and unclosed quotes.

**Sentence boundaries.** The bot splits the question after `.`, `!` or `?` followed by a space
(and any closing quote or bracket) when the next word starts with a capital letter. It
recognises common abbreviations, so "Dr. Livingstone", "St. Louis", "the U.S. Army", "T. S.
Eliot", "c. 1850", "No. 5", "Sept. 11" and decimals like "3.5" stay within one sentence, and a
sentence ending inside a quote (`He called it "the Rock." Name ...`) is split correctly. It
gets these wrong:
- **A sentence that ends with a single capital letter** ("vitamin C.", "World War I.", "Plan
  B.") is taken for an initial and joined to the next one, unless that one starts with a
  common word like "The" or "This". Rephrase.
- **A `?` or `!` followed by a capitalised word inside a sentence** ("the musical Oklahoma!
  Rodgers wrote ...", a quotation like `"Boo! Boo to the party!"`) ends the sentence there.
  Put the title at the end of its sentence, or rephrase. With a lowercase word next
  ("Oklahoma! premiered in 1943") there is no problem.
- **An abbreviation at the end of a sentence followed by a name** ("... across the U.S. Lincoln
  then ...") is not split. Write "United States" at a sentence end.

The validator shows you the result: a clue under 5 or over 40 words usually means one of these
went wrong, and it names the sentence. It also rejects a quotation split across two clues and a
single capital letter after words like "vitamin", "war" or "plan".

**Variety.** Within one file, vary categories, subcategories and answer types (people, works,
places, concepts), do not repeat an answer, do not reuse the same clue twice, and do not let one
question name another question's answer.

**Fiction.** For novels, comics, anime, games and shows, avoid clues that spoil how the story
ends, and keep to the version the question asks about: a detail that only happens in a TV
adaptation does not belong in a question about the original comic, or the reverse.

## Writing the answerline

The answerline (`answer`) is what the bot uses to judge typed answers. It is HTML-ish text in
the qbreader style. Small typos are forgiven in words of 6 or more letters, and
"the" and a leading "a"/"an" are ignored.

1. Wrap the **required** part in `<b><u>...</u></b>` (or just `<u>...</u>`). Players must
   say at least this, so keep it to the shortest form a knowledgeable person would give
   (`Josip Broz <b><u>Tito</u></b>` needs only "Tito"). With no underline at all the bot
   requires every word of the answer, so always underline.
2. Put extra instructions in **square brackets** after it, separated by semicolons:
   - `[or <b><u>Alternate name</u></b>; accept <b><u>Another name</u></b>]`: other correct
     answers. Underline alternates the same way as the main answer. An alternate with no
     underline is accepted only when the player types all of its words.
   - `[prompt on <u>partial</u>]`: an answer that is right but not specific enough ("Vincent"
     for Van Gogh) makes the bot ask for more. Do not prompt on a wrong answer, however
     closely related it is.
   - `[do not accept or prompt on “wrong thing”]`: a commonly confused answer that is wrong.
     It is matched word for word, without typo tolerance, so write it the way players would
     type it.
3. Anything in round brackets that does not begin with accept/prompt/do-not-accept is
   treated as a comment (pronunciation, clarification) and ignored.
4. Add reasonable alternate names, abbreviations, spellings, translations and singular/plural
   forms (`accept <b><u>WWI</u></b> or <b><u>World War One</u></b>`), but only genuinely
   equivalent answers. Every string you add becomes off-limits in the question (see "No
   answer leaks").
5. Other forms of a word: list the ones players are likely to type as alternates rather than
   relying on "accept word forms". The bot does understand that phrase, but only for small
   changes of ending: it accepts "photosynthesize" for photosynthesis but not
   "photosynthetic". It also applies to prompts.
6. For titles, underline the part that identifies the work (`<u>The Great Gatsby</u>`, or
   `<u>Lord of the Rings</u>` when a leading "The" is not needed).
7. Quote with double quotes (see "Quotes" above), never single quotes.
8. Never put the question text, explanations, or citations in `answer`. The validator rejects an
   answerline over 400 characters.
9. **Keep it typeable.** Players type their answers, so at least one accepted answer (the main
   one or an alternate) must need at most **30 characters** of typing: its underlined words (all
   its words if nothing is underlined), not counting punctuation or "the". For a long quotation
   or title, underline the part everyone remembers
   (`I know what I have to do, but I don't know if I have the <b><u>strength to do it</u></b>`)
   or accept a short form (`[or <b><u>The Ultimate Showdown</u></b>]`). At least one accepted
   answer must also be in the Latin alphabet: add a romanised form next to one in Japanese,
   Chinese or Korean script.
10. **Only answers inside the brackets.** The bot's checker reads every item after `or`,
    `accept`, `prompt on` and `do not accept` as an answer to match. Instructions meant for a
    human reader ("prompt on partial answer", "accept equivalents", "accept any similar
    description") become strings nobody will ever type, so the validator rejects them. List the
    actual partial answers and equivalents instead. The checker does understand "accept word
    forms", "accept either underlined portion" and "prompt on X by asking “...”".
11. Only `<b>`, `<u>`, `<i>`, `<em>` and `<strong>` tags, each closed in order, with every `[`
    and `(` closed too.

The validator also runs each listed answer through the checker: every alternate must be accepted
and every prompt must be prompted on. A prompt that the checker accepts outright never happens,
for example `<b><u>Amogus</u></b> [prompt on <u>Among Us</u>]`, where "Among Us" is within
typo tolerance of the answer. Drop such a prompt, or accept it if it really is correct.

Good:
- `<b><u>Vincent van Gogh</u></b> [or <b><u>Van Gogh</u></b>; prompt on <u>Vincent</u>]`.
  All three words are underlined, so "Van Gogh" needs its own alternate.
- `<b><u>mitochondria</u></b> [or <b><u>mitochondrion</u></b>]`. The singular differs by two
  letters, too many for typo tolerance, so it is listed.
- `<b><u>tungsten</u></b> [or <b><u>wolfram</u></b>; accept <b><u>W</u></b>]`. The question
  must now avoid "wolfram" and the symbol W as well as "tungsten".

Bad:
- `Vincent van Gogh` (no underline, so a player must type all three words, and "Van Gogh" is
  marked wrong).
- `<b><u>photosynthesis</u></b> [prompt on <u>respiration</u>]` (respiration is a wrong answer,
  not a partial one).

## What the validator checks

`python -m trivia_oracle_backend.custom.add` (with or without `--check`) rejects a file if any
line breaks one of these. Each is explained in the sections above.

- **Format:** the six fields, the category tables, difficulty 1–10, no duplicate question.
- **Shape**, with sentences split as the bot splits them: 4–7 sentences, each 5–40 words, 60–200
  words in all; "For 10 points" only in the last sentence, which says "name this ..." or "give
  the ..."; a lead that points at the answer.
- **Text:** plain text ending in `.`, `?` or `!`; double quotes in matching pairs, never single
  quotes as quotation marks; no quotation split across sentences; no single capital letter
  ending a sentence after "vitamin", "war", "plan" and the like; no tabs, line breaks, invisible
  characters or double spaces.
- **Leaks:** no run of words in the question that the answer checker accepts or prompts on.
- **Answerline:** at most 400 characters; only `<b>`, `<u>`, `<i>`, `<em>`, `<strong>`, closed in
  order; balanced brackets; no instructions for a human reader inside them; an accepted answer
  of at most 30 characters of typing and one in the Latin alphabet; the checker accepts every
  alternate and prompts on every prompt.
- **Warning only:** an answer already used on another line or in another submission file.

It cannot check facts, whether clues get easier, or whether the lead is fair; that is the
self-check below.

## Self-check before you finish

- [ ] Valid JSON on every line, exactly the six allowed fields, saved as `.jsonl`.
- [ ] 4–7 sentences as the bot splits them, each 5–40 words (aim for 15–30), 60–200 words in all
      (aim for 80–180).
- [ ] The lead says "this ..." (or begins with its/his/her/their); the giveaway is the only
      sentence with "For 10 points" and says "name this ..." or "give the ...".
- [ ] Double quotes only, in matching pairs; no quotation split across two sentences.
- [ ] The requester approved the answer list (stage 1).
- [ ] Every clue was checked against a source you actually opened (stage 2), and it is listed in
      the `.sources.md` file.
- [ ] No claim relies on memory alone, and no superlative ("first", "only", "largest") is unconfirmed.
- [ ] No accepted or prompted string, or another form of one, appears anywhere in the question,
      giveaway included; no question names another question's answer.
- [ ] An expert could answer from the lead alone; each clue is easier than the one before; the
      last sentence is the giveaway.
- [ ] No sentence is over about 30 words, and none of the splitting traps under "Sentence
      boundaries" occurs.
- [ ] Category / subcategory / alternate_subcategory combination matches the tables above.
- [ ] Difficulty roughly matches how obscure the *first* clue is.
- [ ] Every `answer` underlines its required part and its alternates with `<b><u>`, and prompts
      only on partial answers.
- [ ] Every `answer` has an accepted form of at most 30 characters of typing, in the Latin
      alphabet, lists actual answers rather than instructions ("partial answer", "equivalents"),
      and is at most 400 characters.
- [ ] No duplicate questions or answers within the file; nothing copied from qbreader.
- [ ] `python -m trivia_oracle_backend.custom.add --check <file>` passes, and every repeated-answer
      warning it prints is either fixed or a repeat the requester asked for.

## Do not

- Do not edit the database file, `local/schema.sql`, the sync script, or any code to make
  validation pass. If the validator seems wrong, report it instead.
- Do not write questions about private individuals, or content that is hateful, sexual, or
  graphic. Keep it suitable for a general Telegram group.
- Do not put secrets or personal data (names, Telegram IDs) into questions.
