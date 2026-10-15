#!/usr/bin/env python3
"""Run every conformance case under spec/conformance against guidance_check.py.

A case is a directory spec/conformance/<check-id>/{pass,fail}/<case>/ holding
marketplace/, optional upstreams/ and previous/, and expect.json. Each case runs
the script with this invocation:

    python3 plugins/guidance-conventions/scripts/guidance_check.py <case>/marketplace \\
        --upstreams <case>/upstreams --previous <case>/previous --no-official --no-pin --json

(--upstreams and --previous are given only when that directory exists.)

Verdicts, from expect.json:
    every case   the exit code equals "exit"
    fail         each id in "checks" appears as a blocking finding
    pass         no blocking finding carries the case's check id

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


def command_for(case: Case) -> List[str]:
    cmd = [sys.executable, "-B", str(SCRIPT), str(case.path / "marketplace")]
    if (case.path / "upstreams").is_dir():
        cmd += ["--upstreams", str(case.path / "upstreams")]
    if (case.path / "previous").is_dir():
        cmd += ["--previous", str(case.path / "previous")]
    cmd += ["--no-official", "--no-pin", "--json"]
    return cmd


def _blocking_checks(findings: list) -> set:
    return {f.get("check") for f in findings if f.get("severity") == "block"}


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
    if returncode != want_exit:
        blocking = sorted(_blocking_checks(payload["findings"]) - {None})
        return Result(case, False, f"exit {returncode}, expected {want_exit}; blocking: {', '.join(blocking) or 'none'}")

    blocking = _blocking_checks(payload["findings"])
    if case.outcome == "fail":
        missing = [cid for cid in expect.get("checks", []) if cid not in blocking]
        if missing:
            return Result(case, False, f"no blocking finding for {', '.join(missing)}")
        return Result(case, True, f"exit {returncode}, blocking {', '.join(sorted(blocking))}")

    if case.check in blocking:
        return Result(case, False, f"blocking finding for {case.check} in a pass case")
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
        proc = subprocess.run(command_for(case), capture_output=True, text=True,
                              cwd=str(ROOT), timeout=600, check=False)
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
