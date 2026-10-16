"""Validates every conformance expect.json against spec/schemas/conformance-expect.schema.json.

The schema is read and applied with the guidance subset validator in gc_parse, so the
check needs no third-party package. An id that does not match the pattern fails here,
before the case runner reads the file.

Run from the repository root:
    python3 -m unittest tests.test_conformance_expect -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gc_parse import validate_json_schema  # noqa: E402

SCHEMA_PATH = REPO / "spec" / "schemas" / "conformance-expect.schema.json"
CONFORMANCE = REPO / "spec" / "conformance"


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def expect_files():
    return sorted(CONFORMANCE.glob("*/*/*/expect.json"))


class ExpectSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_every_expect_file_validates(self):
        files = expect_files()
        self.assertTrue(files, "no expect.json files were found")
        for path in files:
            with self.subTest(path=str(path.relative_to(REPO))):
                instance = json.loads(path.read_text(encoding="utf-8"))
                errors = validate_json_schema(instance, self.schema, self.schema)
                self.assertEqual(errors, [])

    def test_check_id_pattern_accepts_digits_after_the_prefix(self):
        for ok in ("F-tier3", "A8", "X-placement", "AD3", "V-major"):
            with self.subTest(check=ok):
                instance = {"exit": 1, "checks": [ok]}
                self.assertEqual(validate_json_schema(instance, self.schema, self.schema), [])

    def test_check_id_pattern_rejects_a_non_matching_id(self):
        for bad in ("f-schema", "F_tier3", "F-Tier3", "a8", "F-tier-3 ", "X--resolve"):
            with self.subTest(check=bad):
                instance = {"exit": 1, "checks": [bad]}
                errors = validate_json_schema(instance, self.schema, self.schema)
                self.assertTrue(errors, f"{bad!r} should not match the check id pattern")

    def test_expect_file_with_a_bad_id_fails_validation(self):
        instance = {"exit": 1, "checks": ["X-resolve", "x-placement"]}
        errors = validate_json_schema(instance, self.schema, self.schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("$.checks[1]", errors[0])


if __name__ == "__main__":
    unittest.main()
