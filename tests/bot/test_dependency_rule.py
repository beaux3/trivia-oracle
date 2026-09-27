import ast
import os
import unittest

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "trivia_oracle_bot")
FORBIDDEN = ("trivia_oracle_backend",)


class DependencyRuleTest(unittest.TestCase):
    def test_trivia_oracle_bot_never_imports_the_other_side(self):
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
                        if module.split(".")[0] in FORBIDDEN:
                            offenders.append(f"{os.path.relpath(path, PACKAGE_DIR)}: {module}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
