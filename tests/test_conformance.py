"""Runs every conformance case under spec/conformance against guidance_check.py.

Each case is one subTest, so a failing case is named in the unittest report.
The cases and their verdicts are defined in tests/run_conformance.py.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import run_conformance  # noqa: E402


class ConformanceCases(unittest.TestCase):
    def test_cases_exist(self):
        self.assertTrue(run_conformance.discover(), "no conformance cases were found")

    def test_every_case_agrees_with_its_expectation(self):
        cases = run_conformance.discover()
        self.assertTrue(cases, "no conformance cases were found")
        for case in cases:
            with self.subTest(case=case.label):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = run_conformance.run_case(case)
                self.assertTrue(result.ok, f"{case.label}: {result.detail}")


def _payload(*findings, exit_code=0):
    """A JSON stdout as guidance_check.py --json prints it."""
    return json.dumps({"exit": exit_code, "findings": [
        {"check": check, "severity": severity, "file": None, "message": "m", "fix": "f"}
        for check, severity in findings]})


class JudgeRules(unittest.TestCase):
    PASS = run_conformance.Case("M2", "pass", "case", Path("/nonexistent"))
    FAIL = run_conformance.Case("PIN", "fail", "case", Path("/nonexistent"))

    def verdict(self, case, expect, stdout, returncode=0):
        return run_conformance.judge(case, expect, returncode, stdout)

    def test_listed_warning_must_be_present(self):
        result = self.verdict(self.PASS, {"exit": 0, "checks": [], "warnings": ["M2"]},
                              _payload(("A3", "warn")))
        self.assertFalse(result.ok)
        self.assertIn("no warn finding for M2", result.detail)

    def test_listed_warning_present_passes(self):
        result = self.verdict(self.PASS, {"exit": 0, "checks": [], "warnings": ["M2"]},
                              _payload(("M2", "warn")))
        self.assertTrue(result.ok, result.detail)

    def test_own_warning_in_a_pass_case_fails_unless_listed(self):
        result = self.verdict(self.PASS, {"exit": 0, "checks": []}, _payload(("M2", "warn")))
        self.assertFalse(result.ok)
        self.assertIn("not listed in warnings", result.detail)

    def test_another_checks_warning_does_not_fail_a_pass_case(self):
        result = self.verdict(self.PASS, {"exit": 0, "checks": []}, _payload(("A3", "warn")))
        self.assertTrue(result.ok, result.detail)

    def test_fail_case_needs_each_listed_blocking_id(self):
        result = self.verdict(self.FAIL, {"exit": 2, "checks": ["PIN"]},
                              _payload(("F-schema", "block"), exit_code=2), returncode=2)
        self.assertFalse(result.ok)
        self.assertIn("no blocking finding for PIN", result.detail)

    def test_exit_must_equal_the_expected_exit(self):
        result = self.verdict(self.FAIL, {"exit": 2, "checks": ["PIN"]},
                              _payload(("PIN", "block"), exit_code=1), returncode=1)
        self.assertFalse(result.ok)
        self.assertIn("expected 2", result.detail)

    def test_stdout_must_be_json(self):
        result = self.verdict(self.PASS, {"exit": 0, "checks": []}, "not json")
        self.assertFalse(result.ok)


class CommandRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-runner-")
        self.case_path = Path(self._tmp.name) / "case"
        self.case_path.mkdir()
        self.case = run_conformance.Case("PIN", "fail", "case", self.case_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_flags_and_relative_paths(self):
        cmd = run_conformance.command_for(self.case, {"exit": 0, "checks": []})
        self.assertEqual(cmd[3:], ["marketplace", "--no-official", "--no-pin", "--json"])

    def test_args_replace_the_default_flags(self):
        cmd = run_conformance.command_for(self.case, {"exit": 2, "checks": ["PIN"],
                                                      "args": ["--json", "--no-official", "--repo", "marketplace"]})
        self.assertEqual(cmd[3:], ["marketplace", "--json", "--no-official", "--repo", "marketplace"])

    def test_upstreams_and_previous_are_added_only_when_present(self):
        (self.case_path / "upstreams").mkdir()
        cmd = run_conformance.command_for(self.case, {"exit": 0, "checks": []})
        self.assertIn("--upstreams", cmd)
        self.assertEqual(cmd[cmd.index("--upstreams") + 1], "upstreams")
        self.assertNotIn("--previous", cmd)


if __name__ == "__main__":
    unittest.main()
