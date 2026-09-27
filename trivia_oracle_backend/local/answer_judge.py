"""
AnswerJudge that decides answers itself, with no network access.

The rules follow qbreader's answer checker as far as answerlines need them:
the underlined part of the answer is enough, a typo is forgiven, "prompt on"
asks for more, and "do not accept" always loses. See answerline.py for how an
answerline is read and matching.py for how words are compared.
"""
from dataclasses import dataclass
from typing import Optional

from .answerline import parse_answerline
from .matching import MAX_GIVEN_LENGTH, Phrase


@dataclass(frozen=True)
class LocalJudgement:
    directive: str                          # "accept" | "reject" | "prompt"
    directed_prompt: Optional[str] = None   # what to ask, only for a prompt the answerline words itself
    final: bool = True                      # the verdict stands; the bot must not second-guess a reject


ACCEPT = LocalJudgement("accept")
REJECT = LocalJudgement("reject")


def judge(answerline: str, given: str) -> LocalJudgement:
    """Judge one typed answer against an answerline (HTML, as stored in the database)."""
    if len(given) > MAX_GIVEN_LENGTH:
        return REJECT
    given_phrase = Phrase.from_text(given)
    if not given_phrase:
        return REJECT
    line = parse_answerline(answerline)
    # Order matters: an explicit "do not accept" beats a near-miss on the real answer.
    # Rejections match word for word: "do not accept absorption" must not catch a typo of
    # "adsorption", and "do not accept The Invisible Man" must not catch "Invisible Man".
    if any(phrase.is_exactly(given_phrase) for phrase in line.rejected):
        return REJECT
    if any(phrase.accepts(given_phrase, line.word_forms) for phrase in line.accepted):
        return ACCEPT
    for prompt in line.prompts:
        if prompt.phrase.accepts(given_phrase, line.word_forms):
            return LocalJudgement("prompt", prompt.message)
    return REJECT


class LocalAnswerJudge:
    """Judges answers in this process. Never calls qbreader, and has no fallback that does."""

    async def check(self, answerline: str, given: str) -> LocalJudgement:
        return judge(answerline, given)
