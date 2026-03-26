import pathlib
import sys
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

from stores.llm.templates.template_parser import TemplateParser


class TemplateParserTests(unittest.TestCase):
    def test_none_language_falls_back_to_default(self):
        parser = TemplateParser(language=None, default_language="en")
        self.assertEqual(parser.language, "en")

    def test_missing_key_returns_none(self):
        parser = TemplateParser(language="en", default_language="en")
        value = parser.get("rag", "missing_prompt_key")
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
