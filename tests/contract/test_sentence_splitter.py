"""
The backend keeps a copy of the bot's sentence splitter (trivia_oracle_backend/custom/sentences.py), because
custom/add.py checks questions clue by clue the way the bot reveals them, and the backend may not import the bot.
Needs both packages importable, like the other contract tests.
"""
import inspect
import unittest

from trivia_oracle_backend.custom import sentences as backend_copy
from trivia_oracle_bot.game import sentences as bot_original


class SentenceSplitterContractTest(unittest.TestCase):
    def test_the_backend_copy_matches_the_bot(self):
        for name in ("_CLOSERS", "_HARD_ABBREVIATIONS", "_SOFT_ABBREVIATIONS", "_SENTENCE_STARTERS",
                     "_LEADING_PUNCTUATION"):
            with self.subTest(name):
                self.assertEqual(getattr(backend_copy, name), getattr(bot_original, name))
        for name in ("_BOUNDARY", "_DOTTED_ACRONYM", "_INITIAL"):
            with self.subTest(name):
                self.assertEqual(getattr(backend_copy, name).pattern, getattr(bot_original, name).pattern)
        for name in ("_is_false_boundary", "split_sentences"):
            with self.subTest(name):
                self.assertEqual(inspect.getsource(getattr(backend_copy, name)),
                                 inspect.getsource(getattr(bot_original, name)))


if __name__ == "__main__":
    unittest.main()
