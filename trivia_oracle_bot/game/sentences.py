"""Split a tossup into the clues that are revealed one at a time."""
import re
from typing import List

_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

# Never end a sentence: they are always followed by a name or number.
_HARD_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "mx", "messrs", "mmes", "dr", "prof", "rev", "fr", "hon", "st", "sts", "mt", "ft",
    "gen", "col", "capt", "cpt", "lt", "sgt", "maj", "adm", "cmdr", "cdr", "brig", "pvt", "cpl",
    "sen", "rep", "gov", "pres", "supt", "det", "insp", "ave", "blvd", "rd", "hwy", "fig", "figs", "vol",
    "vols", "ch", "pp", "vs", "v", "ca", "cf", "approx", "dept", "univ", "assn", "bros",
})

# Usually mid-sentence, but can also close one ("...coins, etc. The collection...").
_SOFT_ABBREVIATIONS = frozenset({"etc", "jr", "sr", "inc", "ltd", "co", "corp", "no", "al"})

# Words that begin a new sentence, so an abbreviation right before one ends the sentence.
_SENTENCE_STARTERS = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "he", "she", "it", "its", "his", "her", "they",
    "their", "we", "i", "you", "in", "on", "at", "after", "before", "during", "for", "name", "identify",
    "give", "one", "another", "both", "each", "some", "many", "when", "while", "as", "by", "with", "from",
    "according", "however", "later", "earlier", "there", "then", "today", "once", "although",
    "because", "if", "note", "described", "depicted", "featuring",
})

_DOTTED_ACRONYM = re.compile(r"(?:[A-Za-z]{1,2}\.){2,}")
_LEADING_PUNCTUATION = "\"'“”‘’([{"


def _is_false_boundary(before: str, after: str) -> bool:
    """Whether the whitespace between `before` and `after` sits inside a sentence."""
    if not before.endswith("."):
        return False

    next_word = after.split(None, 1)[0].lstrip(_LEADING_PUNCTUATION)
    if next_word[:1].islower():
        return True  # sentences start with a capital, so this period belonged to an abbreviation

    token = before.split()[-1].lstrip(_LEADING_PUNCTUATION)
    word = token.rstrip(".").lower()
    if re.fullmatch(r"[A-Za-z]\.", token):
        return True  # an initial, as in "J. R. R. Tolkien"
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
