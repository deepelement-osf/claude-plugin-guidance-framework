#!/usr/bin/env python3
"""Check a marketplace repository against guidance's standards, and compile its concept graph.

Standard library only. Run it from the root of a marketplace repository:

    python3 plugins/guidance-conventions/scripts/guidance_check.py [DIRECTORY]
    python3 plugins/guidance-conventions/scripts/guidance_check.py --compile

Exit codes
    0  every check passed, or only warnings were reported
    1  at least one blocking finding was reported (or the compile failed)
    2  the check could not run at all (not a marketplace, a missing upstream,
       a pin mismatch, a missing tool)

Options
    --json             print {"exit": n, "findings": [...]} instead of text
    --compile          write concept-graph.json and stop; the checks do not run
    --upstreams DIR    directory that holds each upstream marketplace, by name
    --previous DIR     directory that holds the previous concept-graph.json
    --repo PATH        marketplace repository whose .claude/settings.json pin is read
                       (default: the checked directory; see read_pin)
    --no-official      skip the official "claude plugin validate" check
    --no-pin           skip the pin check

Check modules
    gc_checks_f, gc_checks_x, gc_checks_v, gc_checks_m and gc_checks_a are imported
    when they exist (see CHECK_MODULES). Each
    must expose run(ctx) -> list[Finding]. A missing module is skipped; any
    other failure to import or run one exits 2. F-official is in this file, so
    those modules must not emit it.

Public API
----------
CannotRun(check, message, fix="")
guidance_plugin_version() -> str
read_pin(repo) -> str | None
check_pin(repo, version, findings) -> None
resolve_upstreams(marketplace, options) -> dict[str, Marketplace]
official_findings(root, options, findings) -> None
run_check_modules(ctx) -> list[Finding]
render_text(exit_code, findings, notes=()) -> str
render_json(exit_code, findings) -> str
main(argv=None) -> int
"""

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gc_compile import CompileError, compile, write_compiled  # noqa: E402
from gc_model import (  # noqa: E402
    COMPILED_FILE,
    GUIDANCE_MARKETPLACE,
    CannotRun,
    Context,
    Finding,
    Marketplace,
    MarketplaceError,
    Options,
)
from gc_parse import load_json  # noqa: E402
from gc_resolve import ResolveError, resolve  # noqa: E402

PIN_PREFIX = "guidance-conventions--v"
SETTINGS_RELPATH = ".claude/settings.json"
MANIFEST_RELPATH = ".claude-plugin/marketplace.json"
CHECK_MODULES = ("gc_checks_f", "gc_checks_x", "gc_checks_v", "gc_checks_m", "gc_checks_a")


def guidance_plugin_version() -> str:
    path = SCRIPT_DIR.parent / ".claude-plugin" / "plugin.json"
    try:
        manifest = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CannotRun("PIN", f"cannot read {path.name} of this plugin: {exc}",
                        "restore plugins/guidance-conventions/.claude-plugin/plugin.json") from None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version:
        raise CannotRun("PIN", "this plugin's plugin.json has no string version",
                        "restore the version field in plugins/guidance-conventions/.claude-plugin/plugin.json")
    return version


def read_pin(repo) -> Optional[str]:
    """The guidance-conventions version that repo pins, or None.

    The pin is in the repository's committed .claude/settings.json, at
    extraKnownMarketplaces.<guidance marketplace>.source.ref, which is expected
    to read guidance-conventions--v<version>. A missing file, entry or ref, and
    a ref that is not such a tag, all give None. A settings file that is not
    readable JSON exits 2.
    """
    path = Path(repo) / SETTINGS_RELPATH
    if not path.is_file():
        return None
    try:
        settings = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CannotRun("PIN", f"{path} is not readable JSON: {exc}",
                        "fix the JSON syntax of .claude/settings.json, or pass --no-pin") from None
    if not isinstance(settings, dict):
        return None
    known = settings.get("extraKnownMarketplaces")
    entry = known.get(GUIDANCE_MARKETPLACE) if isinstance(known, dict) else None
    source = entry.get("source") if isinstance(entry, dict) else None
    ref = source.get("ref") if isinstance(source, dict) else None
    if not isinstance(ref, str) or not ref.startswith(PIN_PREFIX):
        return None
    return ref[len(PIN_PREFIX):] or None


def check_pin(repo, version: str, findings: List[Finding]) -> None:
    """Compare this check's version with the pin in repo. A mismatch exits 2 (see read_pin)."""
    if repo is None:
        return
    pinned = read_pin(repo)
    if pinned is None:
        findings.append(Finding(
            "PIN", "warn", SETTINGS_RELPATH,
            f"{SETTINGS_RELPATH} pins no {PIN_PREFIX}<version> for {GUIDANCE_MARKETPLACE}; "
            f"this check runs version {version}, and results can differ between authors",
            f"set extraKnownMarketplaces.{GUIDANCE_MARKETPLACE}.source.ref to {PIN_PREFIX}{version}, "
            "or pass --no-pin"))
        return
    if pinned != version:
        raise CannotRun(
            "PIN",
            f"the repository pins guidance-conventions {pinned}, but this check is version {version}",
            f"run claude plugin marketplace update {GUIDANCE_MARKETPLACE}, then "
            f"claude plugin update guidance-conventions@{GUIDANCE_MARKETPLACE}")


def resolve_upstreams(marketplace: Marketplace, options: Options) -> Dict[str, Marketplace]:
    """Load every upstream marketplace, transitively. The order of sources is in gc_resolve."""
    try:
        return resolve(marketplace, options, GUIDANCE_MARKETPLACE)
    except ResolveError as exc:
        raise CannotRun("X-resolve", exc.message, exc.fix) from None


def load_previous(options: Options) -> Optional[dict]:
    if options.previous_dir is None:
        return None
    directory = Path(options.previous_dir)
    if not directory.is_dir():
        raise CannotRun("F-compiled", f"--previous directory {directory} does not exist",
                        "pass the directory that holds the previous concept-graph.json")
    path = directory / COMPILED_FILE
    if not path.is_file():
        return None
    try:
        graph = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CannotRun("F-compiled", f"previous {path} cannot be read: {exc}",
                        "pass a directory with a valid concept-graph.json") from None
    if not isinstance(graph, dict):
        raise CannotRun("F-compiled", f"previous {path} is not a JSON object",
                        "pass a directory with a valid concept-graph.json")
    return graph


OFFICIAL_TIMEOUT_SECONDS = 60


def official_findings(root, options: Options, findings: List[Finding]) -> None:
    """Run the official validation, which is the Claude Code plugin validator, with --strict.

    The validator is started with a list of arguments, never through a shell, and with
    no standard input, so it cannot wait for an interactive session. A missing binary,
    a start failure or a run longer than OFFICIAL_TIMEOUT_SECONDS is a could-not-run
    result (CannotRun, exit 2).
    """
    if options.no_official:
        return
    claude = shutil.which("claude")
    if claude is None:
        raise CannotRun("F-official", "the claude command is not on PATH",
                        "install Claude Code, or pass --no-official to skip the official validation")
    try:
        result = subprocess.run([claude, "plugin", "validate", "--strict", str(root)],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                timeout=OFFICIAL_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise CannotRun("F-official",
                        f"claude plugin validate --strict did not finish in {OFFICIAL_TIMEOUT_SECONDS} seconds",
                        "run it by hand to see where it stops, or pass --no-official to skip it") from None
    except OSError as exc:
        raise CannotRun("F-official", f"claude plugin validate cannot be started: {exc}",
                        "check the Claude Code installation") from None
    if result.returncode != 0:
        lines = [ln for ln in (result.stderr or result.stdout or "").splitlines() if ln.strip()]
        detail = lines[-1] if lines else f"exit {result.returncode}"
        findings.append(Finding(
            "F-official", "block", None,
            f"claude plugin validate --strict reports a failure: {detail}",
            f"run claude plugin validate --strict {root} and fix what it reports"))


def run_check_modules(ctx: Context) -> List[Finding]:
    findings: List[Finding] = []
    for name in CHECK_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            raise CannotRun(name, f"{name} needs a module that cannot be found: {exc.name}",
                            "install the missing module beside guidance_check.py") from None
        except Exception as exc:  # import-time failure is not a verdict
            raise CannotRun(name, f"{name} cannot be imported: {exc!r}",
                            "fix the import error in that module") from None
        try:
            result = module.run(ctx)
        except CannotRun:
            raise
        except Exception as exc:
            raise CannotRun(name, f"{name}.run failed: {exc!r}",
                            "this is a defect in that module; fix it and run again") from None
        findings.extend(list(result))
    return findings


def render_text(exit_code: int, findings: Sequence[Finding], notes: Sequence[str] = ()) -> str:
    lines = list(notes)
    for finding in findings:
        location = finding.file or "-"
        lines.append(f"{finding.severity.upper():<5} {finding.check:<12} {location}: {finding.message}")
        if finding.fix:
            lines.append(f"      fix: {finding.fix}")
    blocking = sum(1 for f in findings if f.blocking)
    warnings = len(findings) - blocking
    lines.append(f"{blocking} blocking, {warnings} warnings; exit {exit_code}")
    return "\n".join(lines) + "\n"


def render_json(exit_code: int, findings: Sequence[Finding]) -> str:
    payload = {"exit": exit_code, "findings": [f.to_dict() for f in findings]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _compile(root: Path, marketplace: Marketplace, upstreams: Dict[str, Marketplace],
             findings: List[Finding], notes: List[str]) -> Tuple[int, List[Finding]]:
    findings.extend(marketplace.findings)
    if any(f.blocking for f in marketplace.findings):
        return 1, findings
    if marketplace.missing_sources:
        # The checks report M1, but this path runs no checks; a graph without the plugin must not be written.
        for name, source in marketplace.missing_sources:
            findings.append(Finding(
                "M1", "block", MANIFEST_RELPATH,
                f"plugin {name} has source {source}, which is not a directory in this repository",
                "create the plugin directory under plugins/, or correct the source"))
        return 1, findings
    try:
        graph = compile(marketplace, upstreams)
        path = write_compiled(root, graph)
    except CompileError as exc:
        findings.append(Finding(exc.check, "block", None, exc.message,
                                "fix the marketplace so that it compiles, then run again"))
        return 1, findings
    notes.append(f"wrote {path.name} (graphHash {graph['graphHash']})")
    return 0, findings


def _run(directory: Path, options: Options, notes: List[str]) -> Tuple[int, List[Finding]]:
    root = directory.resolve()
    try:
        marketplace = Marketplace.load(root)
    except MarketplaceError as exc:
        raise CannotRun("SCOPE", str(exc), "run this from the root of a marketplace repository") from None

    findings: List[Finding] = []
    version = guidance_plugin_version()
    if not options.no_pin:
        check_pin(options.repo or root, version, findings)

    upstreams = resolve_upstreams(marketplace, options)
    if options.compile:
        return _compile(root, marketplace, upstreams, findings, notes)

    official_findings(root, options, findings)
    previous = load_previous(options)
    ctx = Context(root=root, marketplace=marketplace, upstreams=upstreams,
                  previous_graph=previous, options=options, guidance_version=version)
    findings.extend(marketplace.findings)
    findings.extend(run_check_modules(ctx))
    return (1 if any(f.blocking for f in findings) else 0), findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guidance_check.py",
        description="Check a marketplace repository against guidance's standards.")
    parser.add_argument("directory", nargs="?", default=".",
                        help="root of the marketplace repository (default: current directory)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--compile", action="store_true",
                        help="write concept-graph.json and stop; the checks do not run")
    parser.add_argument("--upstreams", metavar="DIR",
                        help="directory holding each upstream marketplace, by its name")
    parser.add_argument("--previous", metavar="DIR",
                        help="directory holding the previous concept-graph.json")
    parser.add_argument("--repo", metavar="PATH",
                        help="guidance repository whose pin is checked")
    parser.add_argument("--no-official", action="store_true",
                        help="skip the official claude plugin validate check")
    parser.add_argument("--no-pin", action="store_true", help="skip the pin check")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    options = Options(
        json=args.json,
        compile=args.compile,
        upstreams_dir=Path(args.upstreams) if args.upstreams else None,
        previous_dir=Path(args.previous) if args.previous else None,
        repo=Path(args.repo) if args.repo else None,
        no_official=args.no_official,
        no_pin=args.no_pin,
    )
    notes: List[str] = []
    try:
        code, findings = _run(Path(args.directory), options, notes)
    except CannotRun as exc:
        code = 2
        findings = [Finding(exc.check, "block", None, exc.message, exc.fix)]
    if options.json:
        sys.stdout.write(render_json(code, findings))
    else:
        sys.stdout.write(render_text(code, findings, notes))
    return code


if __name__ == "__main__":
    sys.exit(main())
