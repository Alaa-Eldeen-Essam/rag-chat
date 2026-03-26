import pathlib
import sys
import unittest
from types import SimpleNamespace


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

from utils.prompt_guard import should_bypass_prompt_guard


class PromptGuardBypassTests(unittest.TestCase):
    def test_non_admin_cannot_bypass(self):
        allowed = should_bypass_prompt_guard(
            bypass_requested=True,
            current_user=SimpleNamespace(is_admin=False),
        )
        self.assertFalse(allowed)

    def test_admin_can_bypass(self):
        allowed = should_bypass_prompt_guard(
            bypass_requested=True,
            current_user=SimpleNamespace(is_admin=True),
        )
        self.assertTrue(allowed)

    def test_no_bypass_requested(self):
        allowed = should_bypass_prompt_guard(
            bypass_requested=False,
            current_user=SimpleNamespace(is_admin=True),
        )
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
