import pathlib
import sys
import importlib.util
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

_spec = importlib.util.spec_from_file_location(
    "routes.nlp_answer_utils",
    SRC_ROOT / "routes" / "nlp_answer_utils.py",
)
_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)

exposed_chat_history = _module.exposed_chat_history
exposed_full_prompt = _module.exposed_full_prompt
should_fallback_for_low_confidence = _module.should_fallback_for_low_confidence


class NlpAnswerUtilsTests(unittest.TestCase):
    def test_prompt_exposure_disabled(self):
        self.assertIsNone(
            exposed_full_prompt("secret prompt", debug_include_prompts=False)
        )
        self.assertEqual(
            exposed_chat_history(
                [{"role": "system", "content": "hidden"}],
                debug_include_prompts=False,
            ),
            [],
        )

    def test_prompt_exposure_enabled(self):
        self.assertEqual(
            exposed_full_prompt("prompt", debug_include_prompts=True),
            "prompt",
        )

    def test_low_confidence_fallback_trigger(self):
        self.assertTrue(
            should_fallback_for_low_confidence(
                {"answer_confidence": 0.12},
                min_confidence=0.20,
            )
        )
        self.assertFalse(
            should_fallback_for_low_confidence(
                {"answer_confidence": 0.55},
                min_confidence=0.20,
            )
        )


if __name__ == "__main__":
    unittest.main()
