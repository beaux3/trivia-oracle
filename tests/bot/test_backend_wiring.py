import ast
import os
import unittest

from trivia_oracle_bot.config import ALL_ALT_SUBCATEGORIES
from trivia_questions.local import question_source as local_source

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "trivia_questions")


class BotUsesLocalBackendTest(unittest.TestCase):
    def test_every_alt_subcategory_the_bot_offers_has_a_parent_entry(self):
        self.assertLessEqual(ALL_ALT_SUBCATEGORIES, set(local_source._ALT_SUBCATEGORY_PARENTS))


class DependencyRuleTest(unittest.TestCase):
    def test_trivia_questions_never_imports_the_bot_or_telegram(self):
        offenders = []
        for folder, dirs, files in os.walk(PACKAGE_DIR):
            dirs[:] = [d for d in dirs if d not in ("vendor", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                for node in ast.walk(ast.parse(open(path).read())):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        modules = [node.module]
                    for module in modules:
                        if module.split(".")[0] in ("telegram", "trivia_oracle_bot"):
                            offenders.append(f"{os.path.relpath(path, PACKAGE_DIR)}: {module}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
