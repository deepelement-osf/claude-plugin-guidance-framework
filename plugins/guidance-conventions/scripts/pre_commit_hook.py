#!/usr/bin/env python3
"""PreToolUse hook: check a marketplace commit before the agent makes it.

Claude Code runs this hook before each Bash tool call. It acts only when the
call makes a git commit, including `git -C <dir> commit` and a commit chained
after other commands, and only when all of these hold:

- the project directory (CLAUDE_PROJECT_DIR, else the input's cwd) is a
  marketplace repository: it holds .claude-plugin/marketplace.json, and it is
  the top level of its own git repository. A manifest in a subdirectory, in a
  submodule, or in a directory that is not a git repository does not qualify;
- the repository the commit lands in is that project repository.

It exports what the commit will contain to a temporary directory and runs
guidance_check.py on it with --json. Blocking findings (exit 1), or a check
that could not run (exit 2), deny the call. The reason carries a text report,
so the agent can fix the findings and commit again. Every other case exits 0
with no output.

What the commit will contain:
- by default, the index as the commit will see it. A `git add` earlier in the
  same chain is replayed on a copy of the index, so the real index is never
  written;
- with -a or --all, the tracked files of the working copy.

Limits: other index-changing commands in a chain (git rm, git mv, git reset)
are not replayed. A directory named by a shell variable is read from the
environment of the hook process.

Standard library only. The hook cannot import the marketplace-repository
probe from another plugin, so the same test is written out here.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "guidance_check.py")
MANIFEST = os.path.join(".claude-plugin", "marketplace.json")

# Variables that a parent process may set. They would point git at another
# repository, so every git call made here drops them.
GIT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")

OPERATOR_CHARS = frozenset("();<>|&")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELLS = ("sh", "bash", "zsh")
MAX_SHELL_DEPTH = 3

# git options before the subcommand that take a separate value.
GIT_OPTS_WITH_VALUE = frozenset(
    ["-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"]
)
# commit options that take a value, so the value is not read as a flag.
COMMIT_LONG_WITH_VALUE = frozenset(
    [
        "--message",
        "--file",
        "--author",
        "--date",
        "--cleanup",
        "--template",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--trailer",
        "--pathspec-from-file",
    ]
)
# commit short options whose value follows (attached, or as the next token).
COMMIT_SHORT_WITH_VALUE = frozenset("mFCctu")


class ExportError(Exception):
    """The commit's contents could not be exported for the check."""


def git_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_VARS}
    if extra:
        env.update(extra)
    return env


def run_git(directory, args, extra_env=None):
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        env=git_env(extra_env),
        capture_output=True,
        text=True,
        check=False,
    )


def top_level(directory):
    """Return the real path of the git top level of directory, or None."""
    if not os.path.isdir(directory):
        return None
    try:
        result = run_git(directory, ["rev-parse", "--show-toplevel"])
    except OSError:
        return None
    top = result.stdout.strip()
    if result.returncode != 0 or not top:
        return None
    return os.path.realpath(top)


def is_marketplace_repo(directory):
    """The marketplace-repository test: the manifest is at the git top level."""
    real = os.path.realpath(directory)
    if not os.path.isfile(os.path.join(real, MANIFEST)):
        return False
    return top_level(real) == real


def resolve(base, path):
    expanded = os.path.expanduser(os.path.expandvars(path))
    return os.path.normpath(os.path.join(base, expanded))


def split_segments(command):
    """Split a shell command into simple-command token lists at operators.

    Returns None when the command has unbalanced quotes. Newlines count as
    operators, and quoted text is never split.
    """
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments, current = [], []
    for token in tokens:
        if token and set(token) <= OPERATOR_CHARS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [segment for segment in segments if segment]


def commit_takes_all(args):
    """True when the commit arguments include -a or --all."""
    all_files = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            break
        if token == "--all":
            all_files = True
        elif token.startswith("--"):
            if "=" not in token and token in COMMIT_LONG_WITH_VALUE:
                i += 1
        elif token.startswith("-") and len(token) > 1:
            for position, letter in enumerate(token[1:], start=1):
                if letter == "a":
                    all_files = True
                if letter in COMMIT_SHORT_WITH_VALUE:
                    if position == len(token) - 1:
                        i += 1
                    break
        i += 1
    return all_files


def parse_git(tokens):
    """Return (subcommand, [-C dirs], args) for a git simple command, or None."""
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    dirs = []
    j = 1
    while j < len(tokens) and tokens[j].startswith("-"):
        token = tokens[j]
        if token == "-C":
            if j + 1 >= len(tokens):
                return None
            dirs.append(tokens[j + 1])
            j += 2
        elif token in GIT_OPTS_WITH_VALUE:
            j += 2
        else:
            j += 1
    if j >= len(tokens):
        return None
    return tokens[j], dirs, tokens[j + 1 :]


def collect(command, cwd, depth=0):
    """List the git commit and git add commands in a command, in order.

    Each record is ("commit", directory, all_files) or ("add", directory, args).
    A directory is where git runs: the shell's cwd, moved by `cd`, then by
    each `git -C`. `sh -c` and similar wrappers are read one level deeper.
    """
    segments = split_segments(command)
    if segments is None:
        return []
    records = []
    current = cwd
    for tokens in segments:
        i = 0
        while i < len(tokens) and ASSIGNMENT.match(tokens[i]):
            i += 1
        words = tokens[i:]
        if not words:
            continue
        head = os.path.basename(words[0])
        if head == "cd":
            targets = [w for w in words[1:] if not w.startswith("-")]
            if targets:
                current = resolve(current, targets[0])
            else:
                current = os.path.expanduser("~")
            continue
        if head in SHELLS and "-c" in words[1:] and depth < MAX_SHELL_DEPTH:
            index = words.index("-c", 1)
            if index + 1 < len(words):
                records.extend(collect(words[index + 1], current, depth + 1))
            continue
        parsed = parse_git(words)
        if parsed is None:
            continue
        subcommand, dirs, args = parsed
        directory = current
        for step in dirs:
            directory = resolve(directory, step)
        if subcommand == "commit":
            records.append(("commit", directory, commit_takes_all(args)))
        elif subcommand == "add":
            records.append(("add", directory, args))
    return records


def copy_index(directory, destination):
    """Copy the repository's real index to destination and return it.

    A repository with no index yet gets no copy. Git creates the index at
    destination on the first add, so the replay starts from an empty index.
    """
    result = run_git(directory, ["rev-parse", "--git-path", "index"])
    if result.returncode != 0 or not result.stdout.strip():
        raise ExportError("could not locate the git index")
    source = os.path.join(directory, result.stdout.strip())
    if os.path.exists(source):
        shutil.copyfile(source, destination)
    return destination


def replay_add(directory, args, index_file):
    """Apply a git add to the index copy at index_file, not the real index.

    A failing add is ignored. The chain would not reach the commit after a
    failed add with &&, and the check is conservative when it does.
    """
    run_git(directory, ["add", *args], extra_env={"GIT_INDEX_FILE": index_file})


def export_staged(repo, index_file, destination):
    extra = {"GIT_INDEX_FILE": index_file} if index_file else None
    result = run_git(
        repo, ["checkout-index", "-a", "--prefix=" + destination + os.sep], extra_env=extra
    )
    if result.returncode != 0:
        raise ExportError(result.stderr.strip() or "git checkout-index failed")


def export_all(repo, index_file, destination):
    extra = {"GIT_INDEX_FILE": index_file} if index_file else None
    result = run_git(repo, ["ls-files", "-z"], extra_env=extra)
    if result.returncode != 0:
        raise ExportError(result.stderr.strip() or "git ls-files failed")
    for rel in result.stdout.split("\0"):
        if not rel:
            continue
        source = os.path.join(repo, rel)
        target = os.path.join(destination, rel)
        # A deleted file and a submodule directory are not copied.
        if os.path.islink(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(os.readlink(source), target)
        elif os.path.isfile(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)


def run_checker(export_dir, repo):
    """Run guidance_check.py on export_dir. Return (exit, findings, error)."""
    try:
        result = subprocess.run(
            [sys.executable, CHECKER, export_dir, "--json", "--repo", repo],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as err:
        return 2, [], str(err)
    error = result.stderr.strip()
    code = result.returncode if result.returncode in (0, 1, 2) else 2
    try:
        report = json.loads(result.stdout)
        findings = report.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("findings is not a list")
    except ValueError:
        return 2, [], error or result.stdout.strip() or "no report was written"
    return code, findings, error


def report_text(code, findings, error):
    """Build the text report that the deny reason carries."""
    lines = [f"Guidance checks did not pass for this commit (exit {code})."]
    if not findings:
        lines.append(f"The checker could not run: {error}" if error else "The checker could not run.")
    groups = {}
    for finding in findings:
        groups.setdefault(finding.get("check", "unknown"), []).append(finding)
    for check, group in groups.items():
        lines.append("")
        lines.append(f"[{check}]")
        for finding in group:
            severity = finding.get("severity", "block")
            where = finding.get("file") or "(no file)"
            lines.append(f"  {severity}: {where}: {finding.get('message', '')}")
            lines.append(f"    fix: {finding.get('fix', '')}")
    lines.append("")
    lines.append("Fix the findings, stage the fixes, and commit again.")
    return "\n".join(lines)


def decide(payload, environ, checker=run_checker):
    """Return the text reason to deny the call, or None to exit silently.

    checker(export_dir, repo) is injectable so tests need not run the script.
    """
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not isinstance(command, str) or "commit" not in command:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    project = os.path.realpath(environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if not is_marketplace_repo(project):
        return None
    records = collect(command, cwd)
    if not any(kind == "commit" for kind, _, _ in records):
        return None

    work = tempfile.mkdtemp(prefix="guidance-precommit-")
    try:
        index_file = None
        for kind, directory, detail in records:
            repo = top_level(directory)
            if repo is None or repo != project:
                continue
            try:
                if kind == "add":
                    if index_file is None:
                        index_file = copy_index(repo, os.path.join(work, "index"))
                    replay_add(directory, detail, index_file)
                    continue
                export_dir = tempfile.mkdtemp(dir=work)
                if detail:
                    export_all(repo, index_file, export_dir)
                else:
                    export_staged(repo, index_file, export_dir)
            except (ExportError, OSError) as err:
                return (
                    "Guidance checks could not run, so this commit was not checked: "
                    f"{err}. Fix the git state, then commit again."
                )
            code, findings, error = checker(export_dir, repo)
            if code != 0:
                return report_text(code, findings, error)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def deny_output(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    reason = decide(payload, os.environ)
    if reason:
        print(json.dumps(deny_output(reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
