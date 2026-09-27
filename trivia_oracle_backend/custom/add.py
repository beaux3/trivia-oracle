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
from datetime import datetime, timezone

from ..config import CUSTOM_QUESTIONS_DB
from ..local.answerline import parse_answerline
from ..local.db import connect, replace_set

SUBMISSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submissions")

# category -> allowed subcategories. Categories without an entry of their own use
# the category name as the subcategory, the way qbreader stores them. Singapore,
# Snowsports, Memes, Japan and Anime are custom-only categories, not qbreader filter
# values; they can be added to the main database when these questions move there.
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
                  "Anime"]:
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
MIN_QUESTION_CHARS = 100
_TAG = re.compile(r"<[^>]*>")
_HTML_IN_QUESTION = re.compile(r"</?[a-zA-Z][^>]*>")


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
        if len(question) < MIN_QUESTION_CHARS:
            problems.append(f"question is only {len(question)} characters; a tossup needs several clues "
                            f"(at least {MIN_QUESTION_CHARS})")
        if _HTML_IN_QUESTION.search(question):
            problems.append("question must be plain text without HTML tags")
    if not isinstance(answer, str) or not answer.strip():
        problems.append("answer must be non-empty text")
    else:
        try:
            if not parse_answerline(answer).accepted:
                problems.append("answer has no answer text before its [brackets]")
        except Exception as e:  # the parser is the judge's own; whatever it chokes on the bot would too
            problems.append(f"answer could not be parsed: {e}")
    return problems


def load_file(path: str):
    """Read and validate a submission file. Returns (records, errors) with errors as printable lines."""
    records, errors, seen = [], [], {}
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
            if not problems:
                question = record["question"].strip()
                if question in seen:
                    problems.append(f"duplicate of line {seen[question]}")
                seen[question] = line_number
            errors += [f"{path}:{line_number}: {p}" for p in problems]
            if not problems:
                records.append(record)
    if not records and not errors:
        errors.append(f"{path}: no questions found")
    return records, errors


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

    files = args.files or sorted(
        os.path.join(SUBMISSIONS_DIR, name) for name in os.listdir(SUBMISSIONS_DIR) if name.endswith(".jsonl")
    )
    if not files:
        print(f"No .jsonl files in {SUBMISSIONS_DIR}")
        return 1

    conn = None if args.check else connect(args.db)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    failed = 0
    for path in files:
        records, errors = load_file(path)
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
