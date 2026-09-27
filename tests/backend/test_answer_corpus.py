"""
The local checker against every answerline in a real questions.db.

Skipped unless a database is available (QUESTIONS_DB, or data/questions.db). Mount it to run:
    docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/data:/app/data:ro" trivia-oracle-backend \
        python -m unittest tests.backend.test_answer_corpus -v

The two checks that matter: an answerline must accept its own answer as printed, and must not
accept the answer of an unrelated question.
"""
import os
import random
import sqlite3
import unittest

from trivia_oracle_backend.config import QUESTIONS_DB
from trivia_oracle_backend.local.answer_judge import judge
from trivia_oracle_backend.local.answerline import _split_groups, _styled_chars, parse_answerline

# Some rows hold a whole question or a copyright notice in the answer field; their
# "answer" is a paragraph and says nothing about the checker.
MAX_ANSWER_LENGTH = 300


@unittest.skipUnless(os.path.exists(QUESTIONS_DB), f"no database at {QUESTIONS_DB}")
class CorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = sqlite3.connect(f"file:{QUESTIONS_DB}?mode=ro", uri=True)
        cls.answers = [a for (a,) in conn.execute("SELECT answer FROM tossups") if len(a) <= MAX_ANSWER_LENGTH]
        conn.close()
        cls.printed = []
        for answer in cls.answers:
            main, _ = _split_groups(_styled_chars(answer))
            cls.printed.append("".join(c for c, _ in main).strip())

    def test_every_answerline_has_something_to_accept(self):
        # A handful of rows have no answer text at all (qbreader stores them empty); nothing to accept there.
        empty = [a for a, p in zip(self.answers, self.printed) if p and not parse_answerline(a).accepted]
        self.assertEqual(empty, [])

    def test_answers_accept_themselves_as_printed(self):
        failures = [
            (a, p) for a, p in zip(self.answers, self.printed)
            if p and judge(a, p).directive != "accept"
        ]
        # A few answerlines contradict themselves ("do not accept" their own answer) or hold pasted text.
        self.assertLessEqual(len(failures), len(self.answers) * 0.001, failures[:10])

    def test_answers_accept_their_underlined_words(self):
        failures = []
        for answer in self.answers:
            main, _ = _split_groups(_styled_chars(answer))
            text = "".join(c for c, _ in main)
            runs, run = [], []
            for c, emphasised in main:
                if emphasised:
                    run.append(c)
                elif run:
                    runs.append("".join(run))
                    run = []
            if run:
                runs.append("".join(run))
            # Underlines that cover only part of a word ("I" in "Indira", "ship" in "ships") are read as whole words.
            if any(r.strip() and (text.find(r) > 0 and text[text.find(r) - 1].isalnum()) for r in runs):
                continue
            given = " ".join(r.strip() for r in runs).strip()
            if given and judge(answer, given).directive != "accept":
                failures.append((answer, given))
        self.assertLessEqual(len(failures), len(self.answers) * 0.001, failures[:10])

    def test_answers_do_not_accept_other_questions_answers(self):
        rng = random.Random(2024)
        indices = range(len(self.answers))
        wrong = []
        trials = 20000
        for _ in range(trials):
            i, j = rng.sample(indices, 2)
            given = self.printed[j]
            # The same answer under two questions is not a false accept.
            if given and given != self.printed[i] and judge(self.answers[i], given).directive == "accept":
                if not any(given.lower() == p.lower() for p in self._accepted_texts(self.answers[i])):
                    wrong.append((self.answers[i], given))
        self.assertLessEqual(len(wrong), trials * 0.0005, wrong[:10])

    @staticmethod
    def _accepted_texts(answerline):
        return [" ".join(p.tokens) for p in parse_answerline(answerline).accepted]

    def test_checking_is_fast(self):
        import time
        start = time.monotonic()
        for answer, given in zip(self.answers[:5000], self.printed[:5000]):
            judge(answer, given)
        self.assertLess(time.monotonic() - start, 10)


if __name__ == "__main__":
    unittest.main()
