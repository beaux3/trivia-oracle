"""
Read a qbreader answerline into what it accepts, prompts on and rejects.

Answerlines are HTML written by question editors, for example

    <b><u>Constantine</u></b> the <b><u>Great</u></b> [or <b><u>Constantine I</u></b>;
    prompt on <u>Constantine</u>; do not accept or prompt on “Constantine II”]

Underlined/bold text is what a player must say. Square brackets, and round
brackets that open with a directive word, hold the directives: accept / or,
prompt on, and do not accept / reject. Other round brackets (pronunciations)
are ignored. Each item is a `Phrase`, see matching.py.
"""
import html
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple

from .matching import Phrase

Styled = List[Tuple[str, bool]]  # (character, is_underlined_or_bold)

_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
_EMPHASIS_TAGS = {"b", "u", "strong"}
_OPENERS = {"[": "]", "(": ")"}

# A directive word starts a new list of items. "Do not accept or prompt on" is one directive.
_DIRECTIVE = re.compile(
    r"(?<![\w-])(?:also\s+)?(?:"
    r"(?P<reject>(?:do\s+not|don't|never)\s+(?:accept|prompt)(?:\s+or\s+prompt)?(?:\s+on)?|reject)"
    r"|(?P<prompt>(?:anti-?)?prompt(?:\s+on)?)"
    r"|(?P<accept>accept)"
    r")(?![\w-])",
    re.IGNORECASE,
)
_LEADING_DIRECTIVE = re.compile(r"\s*(?:also\s+)?(?:accept|prompt|anti-?prompt|reject|do\s+not|don't|or)(?![\w-])", re.IGNORECASE)
_OR = re.compile(r"(?<![\w-])or(?![\w-])", re.IGNORECASE)
_BY_ASKING = re.compile(r"\s+by\s+asking\s+", re.IGNORECASE)
# "prompt on X before the first “galaxy”": the timing condition cannot apply to a typed answer.
_TIMING = re.compile(
    r"\s+(?:before|after|until)\s+(?:mention|read\b|is\b|are\b|the\s+(?:first|second|last|word|phrase|mention)|[\"“])",
    re.IGNORECASE,
)
_INSTRUCTION = re.compile(r"\s*either\b", re.IGNORECASE)  # "accept either underlined portion": an instruction, not an answer
_WORD_FORMS = re.compile(r"word\s+forms?", re.IGNORECASE)
# "accept word forms like Italy": the instruction is not an answer, but the example after it is.
_WORD_FORMS_ITEM = re.compile(
    r"\s*(?:(?:any|all|other)\s+)?word\s+forms?\b(?:\s+(?:like|such\s+as|including)\b)?", re.IGNORECASE
)
_EITHER_UNDERLINED = re.compile(r"either\s+(?:of\s+the\s+)?(?:underlined|bolded|bold)\b", re.IGNORECASE)
_QUOTE_MASK = "\0"


@dataclass(frozen=True)
class Prompt:
    phrase: Phrase
    message: Optional[str]  # what to ask the player, when the answerline says ("by asking ...")


@dataclass(frozen=True)
class Answerline:
    accepted: Tuple[Phrase, ...]
    prompts: Tuple[Prompt, ...]
    rejected: Tuple[Phrase, ...]
    word_forms: bool = False  # the answerline says "accept word forms"


def _styled_chars(markup: str) -> Styled:
    """Strip tags and entities, remembering which characters are underlined or bold."""
    chars: Styled = []
    depth = 0
    position = 0
    for tag in _TAG.finditer(markup):
        text = html.unescape(markup[position:tag.start()])
        chars += [(c, depth > 0) for c in text.replace("\xa0", " ")]
        if tag.group(2).lower() in _EMPHASIS_TAGS:
            depth = max(0, depth + (-1 if tag.group(1) else 1))
        position = tag.end()
    chars += [(c, depth > 0) for c in html.unescape(markup[position:]).replace("\xa0", " ")]
    return chars


def _split_groups(chars: Styled) -> Tuple[Styled, List[Tuple[str, Styled]]]:
    """Separate the text outside brackets from the top-level [...] and (...) groups."""
    main: Styled = []
    groups: List[Tuple[str, Styled]] = []
    closer, depth, current, opener = None, 0, [], ""
    for char, emphasised in chars:
        if closer is None:
            if char in _OPENERS:
                opener, closer, depth, current = char, _OPENERS[char], 1, []
            else:
                main.append((char, emphasised))
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                groups.append((opener, current))
                closer = None
                continue
        current.append((char, emphasised))
    if closer is not None:  # never closed: treat the rest as a group anyway
        groups.append((opener, current))
    return main, groups


def _mask_quotes(text: str) -> str:
    """
    Blank out quoted text so the words inside are never taken for directives or separators.
    Either closing mark ends a quote whichever mark opened it, because editors mix "straight” and “curly".
    """
    out, quoted = [], False
    for c in text:
        if not quoted:
            out.append(c)
            quoted = c in ('"', "“")
        elif c in ('"', "”"):
            out.append(c)
            quoted = False
        else:
            out.append(_QUOTE_MASK)
    return "".join(out)


def _is_directive_group(opener: str, chars: Styled) -> bool:
    if opener == "[":
        return True
    return bool(_LEADING_DIRECTIVE.match("".join(c for c, _ in chars)))


def _clauses(chars: Styled) -> List[Tuple[str, Styled]]:
    """Cut a group into (directive kind, text) clauses at ; , and directive words."""
    text = "".join(c for c, _ in chars)
    masked = _mask_quotes(text)
    cuts = [(0, 0, "")]  # (start of clause, start of its text, directive word or "")
    for m in re.finditer(r"[;,]", masked):
        cuts.append((m.start(), m.end(), ""))
    for m in _DIRECTIVE.finditer(masked):
        kind = "reject" if m.group("reject") else "prompt" if m.group("prompt") else "accept"
        cuts.append((m.start(), m.end(), kind))
    cuts.sort()
    clauses = []
    for i, (start, text_start, kind) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(chars)
        clauses.append((kind, chars[text_start:end]))
    return clauses


def _items(chars: Styled) -> List[Styled]:
    """Split one clause on the word "or"; a leading "or" is dropped."""
    masked = _mask_quotes("".join(c for c, _ in chars))
    items, start = [], 0
    for m in _OR.finditer(masked):
        items.append(chars[start:m.start()])
        start = m.end()
    items.append(chars[start:])
    return items


def _strip_timing(chars: Styled) -> Styled:
    masked = _mask_quotes("".join(c for c, _ in chars))
    m = _TIMING.search(masked)
    return chars[:m.start()] if m else chars


def _message(chars: Styled) -> Tuple[Styled, Optional[str]]:
    """Split 'X by asking "question?"' into X and the question."""
    masked = _mask_quotes("".join(c for c, _ in chars))
    m = _BY_ASKING.search(masked)
    if not m:
        return chars, None
    asked = "".join(c for c, _ in chars[m.end():]).strip().strip("\"“” ").strip()
    return chars[:m.start()], asked or None


def _strip_word_forms(chars: Styled) -> Styled:
    """Drop a leading "word forms" instruction, keeping any example after it ("like Italy")."""
    m = _WORD_FORMS_ITEM.match("".join(c for c, _ in chars))
    return chars[m.end():] if m else chars


def _emphasised_runs(chars: Styled) -> List[Styled]:
    runs, run = [], []
    for char, emphasised in chars:
        if emphasised:
            run.append((char, emphasised))
        elif run:
            runs.append(run)
            run = []
    return runs + ([run] if run else [])


@lru_cache(maxsize=1024)
def parse_answerline(answerline: str) -> Answerline:
    main, groups = _split_groups(_styled_chars(answerline))
    accepted, prompts, rejected = [], [], []
    main_phrase = Phrase.from_styled(main)
    if main_phrase:
        accepted.append(main_phrase)

    word_forms = False
    for opener, group in groups:
        if not _is_directive_group(opener, group):
            continue
        group_text = "".join(c for c, _ in group)
        word_forms = word_forms or bool(_WORD_FORMS.search(group_text))
        if _EITHER_UNDERLINED.search(group_text):
            accepted += [Phrase.from_styled([(c, True) for c, _ in run]) for run in _emphasised_runs(main)]
        kind = "accept"
        for clause_kind, clause in _clauses(group):
            kind = clause_kind or kind
            for item in _items(clause):
                item, message = _message(item)
                item = _strip_word_forms(_strip_timing(item))
                phrase = Phrase.from_styled(item)
                if not phrase or _INSTRUCTION.match("".join(c for c, _ in item)):
                    continue
                if kind == "accept":
                    accepted.append(phrase)
                elif kind == "prompt":
                    prompts.append(Prompt(phrase, message))
                else:
                    rejected.append(phrase)
    # An answer cannot also be rejected. This happens when a comma inside a rejected title
    # ("do not accept House Mouse, Senate Mouse") is read as a separator.
    rejected = [r for r in rejected if not any(r.is_exactly(a) for a in accepted)]
    return Answerline(tuple(accepted), tuple(prompts), tuple(rejected), word_forms)
