"""Split a tossup into the clues that are revealed one at a time."""
import re
from typing import List

# A sentence ends at . ! or ?, possibly followed by closing quotes or brackets ("the Rock." Name ...).
_CLOSERS = "\"'”’)]"
_BOUNDARY = re.compile(r"(?<=[.!?\"'”’)\]])\s+")

# Never end a sentence: they are always followed by a name or number.
_HARD_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "mx", "messrs", "mmes", "dr", "prof", "rev", "fr", "hon", "st", "sts", "mt", "ft",
    "gen", "col", "capt", "cpt", "lt", "sgt", "maj", "adm", "cmdr", "cdr", "brig", "pvt", "cpl",
    "sen", "rep", "gov", "pres", "supt", "det", "insp", "ave", "blvd", "rd", "hwy", "fig", "figs", "vol",
    "vols", "ch", "pp", "vs", "v", "ca", "cf", "approx", "dept", "univ", "assn", "bros",
})

# Usually mid-sentence, but can also close one ("...coins, etc. The collection...").
_SOFT_ABBREVIATIONS = frozenset({
    "etc", "jr", "sr", "inc", "ltd", "co", "corp", "no", "al",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
})

# Words that begin a new sentence, so an abbreviation right before one ends the sentence.
_SENTENCE_STARTERS = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "he", "she", "it", "its", "his", "her", "they",
    "their", "we", "i", "you", "in", "on", "at", "after", "before", "during", "for", "name", "identify",
    "give", "one", "another", "both", "each", "some", "many", "when", "while", "as", "by", "with", "from",
    "according", "however", "later", "earlier", "there", "then", "today", "once", "although",
    "because", "if", "note", "described", "depicted", "featuring",
})

_DOTTED_ACRONYM = re.compile(r"(?:[A-Za-z]{1,2}\.){2,}")
_INITIAL = re.compile(r"[A-Za-z]\.")
_LEADING_PUNCTUATION = "\"'“”‘’([{"


def _is_false_boundary(before: str, after: str) -> bool:
    """Whether the whitespace between `before` and `after` sits inside a sentence."""
    before = before.rstrip(_CLOSERS)
    if not before.endswith((".", "!", "?")):
        return True  # a closing quote or bracket with no sentence end before it

    next_word = after.split(None, 1)[0].lstrip(_LEADING_PUNCTUATION)
    if next_word[:1].islower():
        return True  # sentences start with a capital, so this belonged to an abbreviation or a title ("Oklahoma! premiered")
    if not before.endswith("."):
        return False

    token = before.split()[-1].lstrip(_LEADING_PUNCTUATION)
    word = token.rstrip(".").lower()
    if _INITIAL.fullmatch(token):
        # An initial, as in "J. R. R. Tolkien" or "A. A. Milne", unless a sentence starts next ("vitamin C. This").
        return _INITIAL.fullmatch(next_word) is not None or next_word.lower() not in _SENTENCE_STARTERS
    if word in _HARD_ABBREVIATIONS:
        return True
    if word in _SOFT_ABBREVIATIONS or _DOTTED_ACRONYM.fullmatch(token):
        return next_word.lower() not in _SENTENCE_STARTERS
    return False


def split_sentences(text: str) -> List[str]:
    """Break `text` after ., ! and ? without splitting inside abbreviations like "St. Louis" or "U.S."."""
    sentences = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if _is_false_boundary(text[start:match.start()], text[match.end():]):
            continue
        sentences.append(text[start:match.start()])
        start = match.end()
    sentences.append(text[start:])
    return [s.strip() for s in sentences if s.strip()]
