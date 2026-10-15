"""Runs every conformance case under spec/conformance against guidance_check.py.

Each case is one subTest, so a failing case is named in the unittest report.
The cases and their verdicts are defined in tests/run_conformance.py.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import sys
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


if __name__ == "__main__":
    unittest.main()
