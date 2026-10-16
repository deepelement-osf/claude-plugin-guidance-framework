#!/usr/bin/env python3
"""Run every conformance case under spec/conformance against guidance_check.py.

A case is a directory spec/conformance/<check-id>/{pass,fail}/<case>/ holding
marketplace/, optional upstreams/ and previous/, and expect.json. The script runs
with the case directory as its working directory, so every path it receives is
relative to the case:

    python3 -B plugins/guidance-conventions/scripts/guidance_check.py marketplace \\
        --upstreams upstreams --previous previous --no-official --no-pin --json

(--upstreams and --previous are given only when that directory exists.)

expect.json has these fields:
    exit      required; the exit code the script must return (0, 1 or 2)
    checks    required; check ids that must be blocking findings (fail cases)
    args      optional; a list of strings that replaces the default flags
              "--no-official --no-pin --json". It must still include "--json",
              because the verdict is read from stdout. Use it for flags such as
              "--repo marketplace" (a path relative to the case). The
              marketplace positional and the --upstreams/--previous options are
              always added by the runner.
    warnings  optional; check ids that must appear as warn findings

Verdicts:
    every case   the exit code equals "exit"; each id in "warnings" appears as a
                 warn finding
    fail         each id in "checks" appears as a blocking finding
    pass         no blocking finding carries the case's check id, and no warn
                 finding carries it unless "warnings" lists it

The schema for expect.json is spec/schemas/conformance-expect.schema.json.

Run from the repository root, one line per case:

    python3 tests/run_conformance.py

It exits 0 when every case agrees with its expect.json, and 1 otherwise. The
script is run with -B so that no bytecode is written into the checkout.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFORMANCE = ROOT / "spec" / "conformance"
SCRIPT = ROOT / "plugins" / "guidance-conventions" / "scripts" / "guidance_check.py"
DEFAULT_ARGS = ["--no-official", "--no-pin", "--json"]


class Case(NamedTuple):
    check: str
    outcome: str  # "pass" or "fail"
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.check}/{self.outcome}/{self.name}"


class Result(NamedTuple):
    case: Case
    ok: bool
    detail: str


def discover(root: Path = CONFORMANCE) -> List[Case]:
    """Every case directory, in a stable order."""
    cases: List[Case] = []
    if not root.is_dir():
        return cases
    for check_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for outcome in ("pass", "fail"):
            outcome_dir = check_dir / outcome
            if not outcome_dir.is_dir():
                continue
            for case_dir in sorted(p for p in outcome_dir.iterdir() if p.is_dir()):
                cases.append(Case(check_dir.name, outcome, case_dir.name, case_dir))
    return cases


def command_for(case: Case, expect: Optional[dict] = None) -> List[str]:
    """The argv for one case. Its paths are relative to the case directory, which is the working directory."""
    args = expect.get("args") if isinstance(expect, dict) else None
    if args is None:
        args = DEFAULT_ARGS
    cmd = [sys.executable, "-B", str(SCRIPT), "marketplace", *args]
    if (case.path / "upstreams").is_dir():
        cmd += ["--upstreams", "upstreams"]
    if (case.path / "previous").is_dir():
        cmd += ["--previous", "previous"]
    return cmd


def _checks_at(findings: list, severity: str) -> set:
    return {f.get("check") for f in findings if f.get("severity") == severity}


def judge(case: Case, expect: dict, returncode: int, stdout: str) -> Result:
    """Compare one run with its expect.json. Returns the verdict and a reason."""
    try:
        payload = json.loads(stdout)
    except ValueError:
        return Result(case, False, f"stdout is not JSON (exit {returncode})")
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        return Result(case, False, "stdout JSON has no findings list")
    if payload.get("exit") != returncode:
        return Result(case, False, f"JSON exit {payload.get('exit')} differs from process exit {returncode}")

    want_exit = expect.get("exit")
    blocking = _checks_at(payload["findings"], "block")
    if returncode != want_exit:
        listed = sorted(blocking - {None})
        return Result(case, False, f"exit {returncode}, expected {want_exit}; blocking: {', '.join(listed) or 'none'}")

    warned = _checks_at(payload["findings"], "warn")
    listed_warnings = expect.get("warnings", [])
    missing_warnings = [cid for cid in listed_warnings if cid not in warned]
    if missing_warnings:
        return Result(case, False, f"no warn finding for {', '.join(missing_warnings)}")

    if case.outcome == "fail":
        missing = [cid for cid in expect.get("checks", []) if cid not in blocking]
        if missing:
            return Result(case, False, f"no blocking finding for {', '.join(missing)}")
        return Result(case, True, f"exit {returncode}, blocking {', '.join(sorted(blocking))}")

    if case.check in blocking:
        return Result(case, False, f"blocking finding for {case.check} in a pass case")
    if case.check in warned and case.check not in listed_warnings:
        return Result(case, False, f"warn finding for {case.check} in a pass case, not listed in warnings")
    return Result(case, True, f"exit {returncode}")


def run_case(case: Case) -> Result:
    expect_path = case.path / "expect.json"
    try:
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Result(case, False, f"cannot read expect.json: {exc}")
    if not isinstance(expect, dict) or not isinstance(expect.get("exit"), int):
        return Result(case, False, "expect.json needs an integer exit")
    if not (case.path / "marketplace").is_dir():
        return Result(case, False, "case has no marketplace/ directory")
    try:
        proc = subprocess.run(command_for(case, expect), capture_output=True, text=True,
                              cwd=str(case.path), timeout=600, check=False)
    except subprocess.TimeoutExpired:
        return Result(case, False, "script did not finish in 600 seconds")
    return judge(case, expect, proc.returncode, proc.stdout)


def run_all(cases: Optional[List[Case]] = None, out=None) -> List[Result]:
    out = out or sys.stdout
    cases = discover() if cases is None else cases
    results = []
    for case in cases:
        result = run_case(case)
        results.append(result)
        status = "ok  " if result.ok else "FAIL"
        out.write(f"{status} {case.label}: {result.detail}\n")
    failed = [r for r in results if not r.ok]
    out.write(f"{len(results) - len(failed)} of {len(results)} cases agree with expect.json\n")
    return results


def main() -> int:
    cases = discover()
    if not cases:
        sys.stderr.write(f"no conformance cases under {CONFORMANCE}\n")
        return 1
    results = run_all(cases)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
