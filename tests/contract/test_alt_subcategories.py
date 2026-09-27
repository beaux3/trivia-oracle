"""
Needs both packages importable, so it runs outside the two images, e.g. from
the repository root with the dependencies of both installed. Neither image
holds the other's code.
"""
import unittest

from trivia_oracle_backend.local import question_source as local_source
from trivia_oracle_bot.config import ALL_ALT_SUBCATEGORIES


class AltSubcategoryContractTest(unittest.TestCase):
    def test_every_alt_subcategory_the_bot_offers_is_known_to_the_backend(self):
        self.assertLessEqual(ALL_ALT_SUBCATEGORIES, set(local_source.ALT_SUBCATEGORY_PARENTS))


if __name__ == "__main__":
    unittest.main()
