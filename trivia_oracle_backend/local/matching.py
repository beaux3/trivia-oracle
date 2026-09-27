"""
Text folding and fuzzy comparison for the local answer checker.

Everything here works on a `Phrase`: an answer reduced to lowercase words with
accents, punctuation and most articles removed. A phrase written with
qbreader's formatting also remembers which words were underlined or bold,
because a player only has to say those (the required part).
"""
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

# Longest answer we will judge. Real answers are a few words; this keeps a pasted
# essay from being fed through the edit-distance code.
MAX_GIVEN_LENGTH = 300

# Symbols that change an answer ("C" is not "C++" or "C#") are spelled out; other punctuation is dropped.
_SPECIAL = {
    "ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i",
    "&": " and ", "+": " plus ", "#": " sharp ", "♯": " sharp ", "♭": " flat ", "%": " percent ",
}
_JOINING = "'’‘`´ʻʼ"  # dropped, so "Meier's" is one word and "don't" is "dont"


def fold_char(char: str) -> str:
    """One character as lowercase letters/digits, with anything else turned into a space."""
    out = []
    for c in char.casefold():
        for d in unicodedata.normalize("NFKD", _SPECIAL.get(c, c)):
            if unicodedata.combining(d) or d in _JOINING or unicodedata.category(d) == "Cf":  # Cf: zero-width spaces, soft hyphens
                continue
            out.append(d if d.isalnum() else " ")
    return "".join(out)


def _roman_numerals() -> dict:
    ones = ["", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix"]
    tens = ["", "x", "xx", "xxx"]
    return {t + o: str(10 * i + j) for i, t in enumerate(tens) for j, o in enumerate(ones) if t + o}


ROMAN_NUMERALS = _roman_numerals()  # "i".."xxxix"; bigger ones do not occur in answers


def clean_tokens(words: Iterable[Tuple[str, bool]]) -> List[Tuple[str, bool]]:
    """
    Drop "the" and a leading "a"/"an", and write Roman numerals as digits.

    Only leading "a"/"an" go, because elsewhere they can matter ("Vitamin A").
    Each word is a (text, flag) pair and keeps its flag.
    """
    words = [w for w in words if w[0]]
    without_the = [w for w in words if w[0] != "the"]
    words = without_the or words
    if len(words) > 1 and words[0][0] in ("a", "an"):
        words = words[1:]
    return [(ROMAN_NUMERALS.get(t, t), flag) for t, flag in words]


def allowed_errors(length: int) -> int:
    """
    How many typos to forgive in a word this long: none up to 5 letters (Kant is not Kent), one up to 14
    letters, then 2 and at most 3. Two edits are not allowed in a word of 14 or fewer letters, because
    real neighbours differ by two ("reflection" and "refraction", "conservation" and "conversation").
    """
    return 0 if length <= 5 else 1 if length <= 14 else 2 if length <= 20 else 3


def edit_distance(left: str, right: str, limit: int) -> int:
    """Damerau-Levenshtein distance (a swap of neighbours is one edit); any result above `limit` is returned as limit + 1."""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous2 = None
    previous = list(range(len(right) + 1))
    for i, lc in enumerate(left, 1):
        row = [i] + [0] * len(right)
        for j, rc in enumerate(right, 1):
            row[j] = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (lc != rc))
            if i > 1 and j > 1 and lc == right[j - 2] and left[i - 2] == rc:
                row[j] = min(row[j], previous2[j - 2] + 1)
        if min(row) > limit:
            return limit + 1
        previous2, previous = previous, row
    return previous[-1]


def same_stem(left: str, right: str) -> bool:
    """Forms of one word: "donating" and "donate", "Italy" and "Italian". Needs 4 shared opening letters."""
    if len(left) < 4 or len(right) < 4 or not (left.isalpha() and right.isalpha()):
        return False
    shared = len(os.path.commonprefix([left, right]))
    return shared >= max(4, min(len(left), len(right)) - 2)


def words_match(left: str, right: str, typos: bool = True, forms: bool = False) -> bool:
    """
    Two words are the same, give or take a typo (and, with `forms`, a change of ending).
    Anything with a digit must match exactly.
    """
    if left == right or (forms and same_stem(left, right)):
        return True
    if not typos or left[0] != right[0] or any(c.isdigit() for c in left + right):
        return False
    limit = allowed_errors(max(len(left), len(right)))
    return limit > 0 and edit_distance(left, right, limit) <= limit


_DIGITS = re.compile(r"\d+")


def strings_match(left: str, right: str, typos: bool = True) -> bool:
    """Two answers with the spaces removed are the same, give or take a typo. Their numbers must be identical."""
    if left == right:
        return bool(left)
    if not typos or not left or not right or left[0] != right[0] or _DIGITS.findall(left) != _DIGITS.findall(right):
        return False
    limit = allowed_errors(max(len(left), len(right)))
    return limit > 0 and edit_distance(left, right, limit) <= limit


def _same_words(left: Sequence[str], right: Sequence[str], typos: bool, forms: bool = False) -> bool:
    """Two word lists say the same thing. Typos are judged word by word, so "Tang" never passes for "Han"."""
    if not left or not right:
        return False
    if "".join(left) == "".join(right):  # also covers "newyork" for "new york"
        return True
    if not typos:
        return False
    if len(left) == len(right):
        return all(words_match(a, b, forms=forms) for a, b in zip(left, right))
    return strings_match("".join(left), "".join(right))


@dataclass(frozen=True)
class Phrase:
    tokens: Tuple[str, ...]        # every word
    required: Tuple[str, ...]      # words with any underlined/bold letter; empty if nothing is marked
    core: Tuple[str, ...]          # just the marked letters' words ("ship" for <u>ship</u>s); empty if nothing is marked
    literal: Tuple[str, ...]       # every word, "the" included, for answers that must not be matched loosely

    @classmethod
    def from_styled(cls, chars: Sequence[Tuple[str, bool]]) -> "Phrase":
        """Build from (character, is_underlined_or_bold) pairs, the form answerline.py produces."""
        letters = []
        for i, (c, emphasised) in enumerate(chars):
            negative = c in "-−" and i + 1 < len(chars) and chars[i + 1][0].isdigit() and (i == 0 or not chars[i - 1][0].isalnum())
            letters += [(f, emphasised) for f in (" minus " if negative else fold_char(c))]
        words, word, marked = [], [], False
        chunks, run = [], []
        for f, emphasised in letters + [(" ", False)]:
            if f == " ":
                if word:
                    words.append(("".join(word), marked))
                word, marked = [], False
            else:
                word.append(f)
                marked = marked or emphasised
            if emphasised:
                run.append(f)
            elif run:
                chunks.append("".join(run))
                run = []
        cleaned = clean_tokens(words)
        core = [t for chunk in chunks for t, _ in clean_tokens((t, True) for t in chunk.split())]
        return cls(
            tokens=tuple(t for t, _ in cleaned),
            required=tuple(t for t, flag in cleaned if flag),
            core=tuple(core),
            literal=tuple(ROMAN_NUMERALS.get(t, t) for t, _ in words),
        )

    @classmethod
    def from_text(cls, text: str) -> "Phrase":
        return cls.from_styled([(c, False) for c in text])

    def __bool__(self) -> bool:
        return bool(self.tokens)

    def accepts(self, given: "Phrase", word_forms: bool = False) -> bool:
        """
        Whether `given` (a player's answer) is this answer.

        True when the player said the whole answer, or just the underlined
        part, or a mix of its words that includes every required word and
        nothing foreign ("Ulysses Grant" for "Ulysses S. <Grant>"). Typos are
        forgiven, and so are other forms of a word ("donating" for "donate") when
        `word_forms` is set, as it is for answerlines that say "accept word forms".
        """
        if not self or not given:
            return False
        if _same_words(given.tokens, self.tokens, True, word_forms):
            return True
        if _same_words(given.tokens, self.core, True, word_forms):
            return True
        return bool(self.required) and (
            all(any(words_match(g, t, forms=word_forms) for t in self.tokens) for g in given.tokens)
            and all(any(words_match(g, r, forms=word_forms) for g in given.tokens) for r in self.required)
        )

    def is_exactly(self, given: "Phrase") -> bool:
        """The player typed this, word for word (articles and all). Used for "do not accept"."""
        return bool(self.literal) and "".join(self.literal) == "".join(given.literal)
