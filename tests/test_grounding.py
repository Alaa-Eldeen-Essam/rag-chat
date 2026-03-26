import pathlib
import sys
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

from utils.grounding import grounding_report


class GroundingReportTests(unittest.TestCase):
    def test_grounded_answer_passes(self):
        answer = "The committee approved the proposal in 2021."
        evidence = "Meeting minutes confirm the committee approved the proposal in 2021."
        report = grounding_report(answer, evidence)
        self.assertTrue(bool(report.get("grounded")))

    def test_ungrounded_answer_fails(self):
        answer = "The committee approved the proposal in 2021. A satellite launched in 2035."
        evidence = "Meeting minutes confirm the committee approved the proposal in 2021."
        report = grounding_report(
            answer,
            evidence,
            max_ungrounded_claims=0,
        )
        self.assertFalse(bool(report.get("grounded")))
        self.assertGreaterEqual(int(report.get("ungrounded_claims") or 0), 1)

    def test_one_ungrounded_claim_can_be_tolerated(self):
        answer = "The committee approved the proposal in 2021. It also drafted future plans."
        evidence = "Meeting minutes confirm the committee approved the proposal in 2021."
        strict = grounding_report(answer, evidence, max_ungrounded_claims=0)
        tolerant = grounding_report(answer, evidence, max_ungrounded_claims=1)
        self.assertFalse(bool(strict.get("grounded")))
        self.assertTrue(bool(tolerant.get("grounded")))

    def test_report_includes_grounded_claim_ratio(self):
        answer = "The committee approved the proposal in 2021."
        evidence = "Meeting minutes confirm the committee approved the proposal in 2021."
        report = grounding_report(answer, evidence)
        ratio = float(report.get("grounded_claim_ratio") or 0.0)
        self.assertGreaterEqual(ratio, 0.5)

    def test_empty_answer_has_zero_grounded_ratio(self):
        report = grounding_report("", "any evidence")
        self.assertEqual(float(report.get("grounded_claim_ratio") or 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
