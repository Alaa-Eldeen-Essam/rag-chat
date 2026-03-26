import pathlib
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


class StartupBootstrapConfigTests(unittest.TestCase):
    def test_main_does_not_hardcode_admin_password(self):
        content = (SRC_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('"admin123"', content)
        self.assertIn("INITIAL_ADMIN_PASSWORD_HASH", content)
        self.assertIn("INITIAL_ADMIN_PASSWORD", content)


if __name__ == "__main__":
    unittest.main()
