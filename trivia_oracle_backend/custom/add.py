"""
Validate custom questions and load them into the custom question database.

    python -m trivia_oracle_backend.custom.add                      # every file in custom/submissions/
    python -m trivia_oracle_backend.custom.add my_set.jsonl         # only these files
    python -m trivia_oracle_backend.custom.add --check my_set.jsonl # validate, write nothing

A submission file is JSONL, one tossup per line (fields in CONTRIBUTING.md). The
file name (without .jsonl) is the set name, and line order is the question
number. Loading a file replaces that set, so the file stays the source of truth
and running the command twice changes nothing. A file with any invalid line is
not loaded at all; every problem is printed with its line number.

Besides the format, the checks enforce CONTRIBUTING.md's writing rules that a
program can see: the question's shape clue by clue (split the way the bot reveals
it, see sentences.py), its wording, the answerline's markup and what the answer
judge makes of it, and that the question never contains a string the answerline
accepts or prompts on. Every problem is an error, --check or not; the only warning
is an answer repeated within the file or already used in another submission file.

The database has exactly the schema of the qbreader copy (local/schema.sql), so
the local backend can read it as it is. Custom sets and questions have is_custom = 1,
which is what will tell them apart if they are moved into the main database later.
Players' votes (good_votes, bad_votes) live only in the database, and reloading a
file keeps the votes of every question that is still in it.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from ..config import CUSTOM_QUESTIONS_DB
from ..local.answer_judge import judge
from ..local.answerline import parse_answerline
from ..local.db import connect, replace_set
from .sentences import split_sentences

SUBMISSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submissions")

# category -> allowed subcategories. Categories without an entry of their own use
# the category name as the subcategory, the way qbreader stores them. Singapore,
# Snowsports, Memes, Japan, Anime and Cultivation / Returner Slop are custom-only
# categories, not qbreader filter values; they can be added to the main database when
# these questions move there.
SUBCATEGORIES = {
    "Literature": ["American Literature", "British Literature", "Classical Literature",
                   "European Literature", "World Literature", "Other Literature"],
    "History": ["American History", "Ancient History", "European History", "World History", "Other History"],
    "Science": ["Biology", "Chemistry", "Physics", "Other Science"],
    "Fine Arts": ["Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts"],
    "Pop Culture": ["Movies", "Music", "Sports", "Television", "Video Games", "Other Pop Culture"],
}
for _category in ["Religion", "Mythology", "Philosophy", "Social Science", "Current Events",
                  "Geography", "Other Academic", "Singapore", "Snowsports", "Memes", "Japan",
                  "Anime", "Cultivation / Returner Slop"]:
    SUBCATEGORIES[_category] = [_category]

# alternate subcategory -> (category, subcategory) it must sit under; None = any.
ALTERNATE_SUBCATEGORIES = {
    **dict.fromkeys(["Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature"], ("Literature", None)),
    **dict.fromkeys(["Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science"],
                    ("Science", "Other Science")),
    **dict.fromkeys(["Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts"],
                    ("Fine Arts", "Other Fine Arts")),
    **dict.fromkeys(["Anthropology", "Economics", "Linguistics", "Psychology", "Sociology", "Other Social Science"],
                    ("Social Science", "Social Science")),
    **dict.fromkeys(["Beliefs", "Practices"], ("Religion", "Religion")),
}

FIELDS = {"category", "subcategory", "alternate_subcategory", "difficulty", "question", "answer"}
REQUIRED = FIELDS - {"alternate_subcategory"}
# The shape of a tossup (CONTRIBUTING.md, "How to write a good tossup"), counted in _WORD words.
MIN_SENTENCES, MAX_SENTENCES = 4, 7
MIN_SENTENCE_WORDS, MAX_SENTENCE_WORDS = 5, 40
MIN_QUESTION_WORDS, MAX_QUESTION_WORDS = 60, 200
# Players type their answers, so at least one accepted answer must need at most this many characters.
MAX_TYPED_ANSWER_CHARS = 30
MAX_ANSWER_CHARS = 400  # the whole answerline; more means explanations or clues crept in

_TAG = re.compile(r"<[^>]*>")
_HTML_IN_QUESTION = re.compile(r"</?[a-zA-Z][^>]*>")
_WORD = re.compile(r"[^\s\"“”()\[\]]+")
_ANSWER_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
_ANSWER_TAGS = {"b", "u", "i", "em", "strong"}
_EMPHASISED = re.compile(r"<(b|u|strong)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_QUOTED = re.compile(r"[\"“][^\"“”]*[\"”]")
_DIRECTIVE_GROUP = re.compile(
    r"\[[^\]]*\]|\((?:\s*(?:also\s+)?(?:accept|prompt|anti-?prompt|reject|do\s+not|don't|or)\b)[^)]*\)", re.IGNORECASE)
_UNDERSTOOD_INSTRUCTION = re.compile(r"(?:any\s+|all\s+|other\s+)?word\s+forms?(?:\s+(?:like|such\s+as|including))?"
                                     r"|either\s+(?:of\s+the\s+)?(?:underlined|bolded|bold)(?:\s+(?:part|portion)s?)?",
                                     re.IGNORECASE)
# Words of an instruction for a human reader. The answer checker reads them as an answer to match instead.
_INSTRUCTION_WORDS = re.compile(r"\b(?:partial|equivalents?|synonyms?|descriptions?|similar|reasonable|etc|any|anything"
                                r"|clear\s+knowledge|like|such\s+as|including)\b", re.IGNORECASE)
_GIVEAWAY = re.compile(r"\bfor\s+(?:10|ten)\s+points\b", re.IGNORECASE)
# The giveaway points at the answer: "name this novel", or "give the four-word catchphrase ...".
_GIVEAWAY_REFERENCE = re.compile(r"\b(?:this|these)\b|\b(?:name|give|identify)\s+the\b", re.IGNORECASE)
_LEAD_REFERENCE = re.compile(r"^[\"“(]?(?:its|his|her|their)\b|\b(?:this|these|here)\b", re.IGNORECASE)
# "vitamin C. Churchill ...": the bot takes C. for an initial and runs the two sentences together. Only after
# words that are followed by a single letter, since "and J. Cole" really is an initial.
_JOINED_INITIAL = re.compile(r"\b(?:vitamin|plan|type|class|grade|group|section|part|war|act|book|volume|chapter"
                             r"|appendix|exhibit|option|model|series|phase|stage|level|gate|terminal|zone|division)"
                             r"\s+([A-Z]\.)\s+[A-Z][a-z]", re.IGNORECASE)
_SINGLE_QUOTED = re.compile(r"(?<!\w)['‘][A-Za-z][^'‘’\"“”]*?['’](?!\w)")
_JUNK_PREFIX = re.compile(r"^(?:toss-?up\b|q\s*[:.]|\(?\d+\s*[.):]\s)", re.IGNORECASE)
_MARKDOWN = re.compile(r"\*\*|`")  # not "__": fill-in-the-blank clues write the blank as "___"
_URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")


def strip_tags(markup: str) -> str:
    return html.unescape(_TAG.sub("", markup))


def validate(record) -> list:
    """Return the problems with one submitted tossup (an empty list means it is fine)."""
    if not isinstance(record, dict):
        return ["line is not a JSON object"]
    problems = []
    if unknown := sorted(set(record) - FIELDS):
        problems.append(f"unknown field(s): {', '.join(unknown)}")
    if missing := sorted(REQUIRED - set(record)):
        problems.append(f"missing field(s): {', '.join(missing)}")
    if problems:
        return problems

    category, subcategory, alternate = record["category"], record["subcategory"], record.get("alternate_subcategory")
    if category not in SUBCATEGORIES:
        problems.append(f"category {category!r} is not one of: {', '.join(SUBCATEGORIES)}")
    elif subcategory not in SUBCATEGORIES[category]:
        problems.append(f"subcategory {subcategory!r} does not belong to {category}; use one of: "
                        f"{', '.join(SUBCATEGORIES[category])}")
    if alternate is not None:
        if alternate not in ALTERNATE_SUBCATEGORIES:
            problems.append(f"alternate_subcategory {alternate!r} is not a known alternate subcategory (or use null)")
        else:
            parent_category, parent_subcategory = ALTERNATE_SUBCATEGORIES[alternate]
            if category != parent_category or (parent_subcategory and subcategory != parent_subcategory):
                where = f"{parent_category} / {parent_subcategory}" if parent_subcategory else parent_category
                problems.append(f"alternate_subcategory {alternate!r} must sit under {where}")

    difficulty = record["difficulty"]
    if isinstance(difficulty, bool) or not isinstance(difficulty, int) or not 1 <= difficulty <= 10:
        problems.append("difficulty must be an integer from 1 to 10")

    question, answer = record["question"], record["answer"]
    if not isinstance(question, str) or not question.strip():
        problems.append("question must be non-empty text")
    else:
        problems += question_problems(question)
    if not isinstance(answer, str) or not answer.strip():
        problems.append("answer must be non-empty text")
    else:
        problems += answer_problems(answer)
    return problems


def _excerpt(sentence: str, words: int = 6) -> str:
    """The start of a sentence, to say which one a problem is in."""
    head = sentence.split()
    return " ".join(head[:words]) + (" ..." if len(head) > words else "")


def text_problems(text: str, field: str) -> list:
    """Problems with characters, quotes and brackets, shared by the question and the answer (without its tags)."""
    problems = []
    if any(c in "\t\r\n" for c in text) or any(unicodedata.category(c) in ("Cc", "Cf") for c in text):
        problems.append(f"{field} contains a tab, line break, control or invisible character; use plain spaces")
    if "  " in text:
        problems.append(f"{field} contains a double space")
    if quoted := _SINGLE_QUOTED.search(text):
        problems.append(f"{field} uses single quotes as quotation marks ({quoted.group()}); use double quotes")
    opener = None
    for c in text:
        if opener is None and c == "”":
            problems.append(f"{field} has a closing ” without an opening “")
            break
        if opener is None and c in "\"“":
            opener = c
        elif opener is not None and c in "\"”":
            if opener + c in ("\"”", "“\""):
                problems.append(f"{field} opens a quote with {opener} and closes it with {c}; use a matching pair")
                break
            opener = None
    else:
        if opener is not None:
            problems.append(f"{field} has a quote that is never closed")
    stack = []
    for c in _QUOTED.sub("", text):
        if c in "([":
            stack.append(c)
        elif c in ")]":
            if not stack or stack.pop() != "([)]"[")]".index(c)]:
                stack = [None]
                break
    if stack:
        problems.append(f"{field} has unbalanced ( ) or [ ] brackets")
    return problems


def question_problems(question: str) -> list:
    """What breaks CONTRIBUTING.md's rules for the question text, judged clue by clue as the bot reveals it."""
    problems = []
    if question != question.strip():
        problems.append("question starts or ends with whitespace")
    if _HTML_IN_QUESTION.search(question):
        problems.append("question must be plain text without HTML tags")
    if _JUNK_PREFIX.match(question) or _MARKDOWN.search(question) or _URL.search(question):
        problems.append("question must be plain text: no \"TOSSUP\" or numbering prefix, markdown or links")
    problems += text_problems(question, "question")
    if not _SENTENCE_END.search(question.strip()):
        problems.append("question must end with . ? or !")

    words = len(_WORD.findall(question))
    if not MIN_QUESTION_WORDS <= words <= MAX_QUESTION_WORDS:
        problems.append(f"question has {words} words; a tossup has {MIN_QUESTION_WORDS} to {MAX_QUESTION_WORDS} "
                        f"(aim for 80 to 180)")
    sentences = split_sentences(question.strip())
    if not MIN_SENTENCES <= len(sentences) <= MAX_SENTENCES:
        problems.append(f"question has {len(sentences)} sentences as the bot splits it; a tossup has "
                        f"{MIN_SENTENCES} to {MAX_SENTENCES}")
    for number, sentence in enumerate(sentences, 1):
        where = f"sentence {number} ({_excerpt(sentence)!r})"
        count = len(_WORD.findall(sentence))
        if count > MAX_SENTENCE_WORDS:
            problems.append(f"{where} has {count} words; keep each clue to at most {MAX_SENTENCE_WORDS} (aim for "
                            f"15 to 30). If it is really two sentences, see \"Sentence boundaries\" in CONTRIBUTING.md")
        elif count < MIN_SENTENCE_WORDS:
            problems.append(f"{where} has only {count} words; the bot shows it as a clue of its own. If it is not "
                            f"meant to end there, see \"Sentence boundaries\" in CONTRIBUTING.md")
        if sentence.count('"') % 2 or sentence.count("“") != sentence.count("”"):
            problems.append(f"{where}: the bot ends this clue inside a quotation, at a . ? or ! followed by a "
                            f"capital; rephrase so the quotation stays within one sentence")
        if joined := _JOINED_INITIAL.search(sentence):
            problems.append(f"{where}: the bot takes {joined.group(1)!r} for an initial and joins the next "
                            f"sentence to it; rephrase so no sentence ends with a single capital letter")
    if sentences:
        giveaways = _GIVEAWAY.findall(question)
        if len(giveaways) != 1 or not _GIVEAWAY.search(sentences[-1]):
            problems.append("the last sentence, and only it, must be the giveaway starting \"For 10 points\"")
        elif not _GIVEAWAY_REFERENCE.search(sentences[-1]):
            problems.append("the giveaway must point at the answer: \"name this ...\" or \"give the ...\"")
        if not _LEAD_REFERENCE.search(sentences[0]):
            problems.append("the first sentence never points at the answer; refer to it as \"this ...\" (or begin "
                            "with its/his/her/their, or say \"here\" for a place)")
    return problems


def answer_problems(answer: str) -> list:
    """What breaks CONTRIBUTING.md's rules for the answerline, including how the answer checker reads it."""
    problems = []
    if len(answer) > MAX_ANSWER_CHARS:
        problems.append(f"answer is {len(answer)} characters (at most {MAX_ANSWER_CHARS}); keep explanations and "
                        f"clues out of the answerline")
    open_tags = []
    for tag in _ANSWER_TAG.finditer(answer):
        closing, name = tag.group(1), tag.group(2).lower()
        if name not in _ANSWER_TAGS:
            problems.append(f"answer uses <{name}>; only <b>, <u>, <i>, <em> and <strong> are allowed")
            break
        if not closing:
            open_tags.append(name)
        elif not open_tags or open_tags.pop() != name:
            open_tags = [None]
            break
    if open_tags:
        problems.append("answer has an unclosed or mismatched tag")
    problems += text_problems(strip_tags(answer), "answer")

    plain = strip_tags(_EMPHASISED.sub(" ", answer))  # instructions only; what a player may type is emphasised or quoted
    for group in _DIRECTIVE_GROUP.findall(_QUOTED.sub(" ", plain)):
        if instruction := _INSTRUCTION_WORDS.search(_UNDERSTOOD_INSTRUCTION.sub(" ", group)):
            problems.append(f"answer says {instruction.group()!r} in {group.strip()}, which the answer checker "
                            f"would take for an answer to match; list the actual answers instead")
            break

    try:
        answerline = parse_answerline(answer)
    except Exception as e:  # the parser is the judge's own; whatever it chokes on the bot would too
        return problems + [f"answer could not be parsed: {e}"]
    if not answerline.accepted:
        return problems + ["answer has no answer text before its [brackets]"]
    typed = [" ".join(phrase.required or phrase.tokens) for phrase in answerline.accepted]
    if min(len(t) for t in typed) > MAX_TYPED_ANSWER_CHARS:
        problems.append(f"every accepted answer needs more than {MAX_TYPED_ANSWER_CHARS} characters of typing "
                        f"(shortest: {min(typed, key=len)!r}); underline less, or accept a shorter form")
    if not any(t.isascii() for t in typed):
        problems.append("no accepted answer can be typed in the Latin alphabet; accept a romanised form")
    for phrase in answerline.accepted:
        given = " ".join(phrase.literal)
        if (directive := judge(answer, given).directive) != "accept":
            problems.append(f"the answer checker does not accept {given!r}, which the answerline accepts "
                            f"(it would {directive}); check the brackets, quotes and separators")
    for prompt in answerline.prompts:
        given = " ".join(prompt.phrase.literal)
        if (directive := judge(answer, given).directive) != "prompt":
            problems.append(f"the answer checker does not prompt on {given!r}, which the answerline prompts on "
                            f"(it would {directive})")
    return problems


def leaked_phrase(record: dict, directive: str = "accept"):
    """The shortest run of words in the question that the answer judge would accept as the answer, or None.

    This is CONTRIBUTING.md's "no answer leaks" rule judged the way the bot judges a typed answer, typo
    tolerance included. With directive="prompt" it finds a run the judge would prompt on instead, since a
    question must not contain those either.
    """
    answer = record["answer"]
    answerline = parse_answerline(answer)
    phrases = answerline.accepted if directive == "accept" else [prompt.phrase for prompt in answerline.prompts]
    if not phrases:
        return None
    # Every word of the longest phrase, "the" included, plus one for a word the question splits in two
    # ("Gas Light" for gaslight).
    longest = max(len(phrase.literal) for phrase in phrases) + 1
    words = _WORD.findall(record["question"])
    for size in range(1, longest + 1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start:start + size]).strip(".,;:!?'’")
            if phrase and judge(answer, phrase).directive == directive:
                return phrase
    return None


def leak_problems(record) -> list:
    """The strings in the question that its answerline accepts or prompts on, as problems (none if it cannot tell)."""
    if not isinstance(record, dict) or not isinstance(record.get("question"), str):
        return []
    answer = record.get("answer")
    try:
        if not isinstance(answer, str) or not parse_answerline(answer).accepted:
            return []  # validate() reports the answer itself
    except Exception:
        return []
    problems = []
    if phrase := leaked_phrase(record):
        problems.append(f"the question gives away its own answer: {phrase!r}")
    if phrase := leaked_phrase(record, "prompt"):
        problems.append(f"the question contains {phrase!r}, which the answerline prompts on")
    return problems


def answer_keys(answer: str) -> set:
    """What a player must type for each accepted answer (its required words), used to spot repeated answers."""
    return {" ".join(phrase.required or phrase.tokens) for phrase in parse_answerline(answer).accepted}


def answer_index(paths) -> dict:
    """Answer key -> [(file name, line number), ...] for the questions in these submission files."""
    index = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                lines = list(f)
        except (OSError, UnicodeDecodeError):  # an unreadable file is reported when it is checked itself
            continue
        for line_number, line in enumerate(lines, 1):
            try:
                keys = answer_keys(json.loads(line)["answer"])
            except Exception:  # likewise a broken line
                continue
            for key in keys:
                index.setdefault(key, []).append((os.path.basename(path), line_number))
    return index


def repeated_answers(path: str, numbered: list, index: dict) -> list:
    """(line number, problem) for each answer already accepted by an earlier line or by another file in index."""
    own, first_use, found = os.path.basename(path), {}, []
    for line_number, record in numbered:
        keys = answer_keys(record["answer"])
        places = {f"line {first_use[key]}" for key in keys if key in first_use}
        places |= {f"{name}:{line}" for key in keys for name, line in index.get(key, ()) if name != own}
        found += [(line_number, f"same answer as {place}") for place in sorted(places)]
        for key in keys:
            first_use.setdefault(key, line_number)
    return found


def load_file(path: str, index: Optional[dict] = None):
    """Read and validate a submission file. Returns (records, errors, warnings) as printable lines.

    Every problem is an error, including a question that contains a string its answerline accepts or prompts
    on. A repeated answer, within the file or (given an answer_index) in another submission file, is a warning.
    """
    records, errors, warnings, seen, numbered = [], [], [], {}, []
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{path}:{line_number}: not valid JSON ({e})")
                continue
            problems = validate(record)
            problems += leak_problems(record)  # also for an otherwise invalid line, so one run lists everything
            if not problems:
                question = record["question"].strip()
                if question in seen:
                    problems.append(f"duplicate of line {seen[question]}")
                seen[question] = line_number
            errors += [f"{path}:{line_number}: {p}" for p in problems]
            if not problems:
                records.append(record)
                numbered.append((line_number, record))
    if not records and not errors:
        errors.append(f"{path}: no questions found")
    for line_number, problem in repeated_answers(path, numbered, index or {}):
        warnings.append(f"{path}:{line_number}: warning: {problem}")
    return records, errors, warnings


def to_tossup(set_name: str, packet_number: int, number: int, record: dict, updated_at: str) -> dict:
    """Shape a validated record like a qbreader tossup, which is what replace_set stores."""
    question = record["question"].strip()
    answer = record["answer"].strip()
    digest = hashlib.sha1(f"{set_name}\n{question}".encode("utf-8")).hexdigest()[:24]
    return {
        "_id": f"custom-{digest}",
        "set": {"_id": None, "name": set_name, "year": datetime.now(timezone.utc).year, "standard": False},
        "packet": {"number": packet_number},
        "number": number,
        "category": record["category"],
        "subcategory": record["subcategory"],
        "alternate_subcategory": record.get("alternate_subcategory"),
        "difficulty": record["difficulty"],
        "question_sanitized": question,
        "answer": answer,
        "answer_sanitized": strip_tags(answer),
        "updatedAt": updated_at,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate custom questions and load them into the custom database.")
    parser.add_argument("files", nargs="*", metavar="FILE.jsonl",
                        help="submission files (default: every .jsonl in custom/submissions/)")
    parser.add_argument("--check", action="store_true", help="only validate; do not touch the database")
    parser.add_argument("--db", default=CUSTOM_QUESTIONS_DB, help=f"database file (default: {CUSTOM_QUESTIONS_DB})")
    args = parser.parse_args(argv)

    submissions = sorted(
        os.path.join(SUBMISSIONS_DIR, name) for name in os.listdir(SUBMISSIONS_DIR) if name.endswith(".jsonl")
    )
    files = args.files or submissions
    if not files:
        print(f"No .jsonl files in {SUBMISSIONS_DIR}")
        return 1

    index = answer_index(submissions)
    conn = None if args.check else connect(args.db)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    failed = 0
    for path in files:
        records, errors, warnings = load_file(path, index=index)
        if warnings:
            print("\n".join(warnings))
        if errors:
            failed += 1
            print("\n".join(errors))
            print(f"{os.path.basename(path)}: NOT loaded, fix the {len(errors)} problem(s) above")
            continue
        set_name = os.path.splitext(os.path.basename(path))[0]
        if conn is None:
            print(f"{os.path.basename(path)}: {len(records)} question(s) are valid")
            continue
        tossups = [to_tossup(set_name, 1, number, r, updated_at) for number, r in enumerate(records, 1)]
        count = replace_set(conn, set_name, 1, tossups, custom=True)
        print(f"{os.path.basename(path)}: loaded {count} question(s) as set {set_name!r}")
    if conn is not None:
        total_sets, total = conn.execute("SELECT COUNT(*), COALESCE(SUM(tossup_count), 0) FROM sets").fetchone()
        conn.close()
        print(f"{args.db} now holds {total_sets} set(s), {total} tossup(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
