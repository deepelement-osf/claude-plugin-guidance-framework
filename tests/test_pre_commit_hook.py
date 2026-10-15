"""Tests for plugins/guidance-conventions/scripts/pre_commit_hook.py.

The hook acts only on a git commit made in a marketplace repository, and exits
0 silently in every other case. The check itself is replaced by a stub here,
so these tests do not depend on guidance_check.py. The stub is injected into
decide(), which the hook's main path calls.

Run from the repository root:
    python3 -m unittest tests.test_pre_commit_hook -v
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "guidance-conventions"
HOOK = PLUGIN / "scripts" / "pre_commit_hook.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"

_spec = importlib.util.spec_from_file_location("pre_commit_hook", HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
}


def clean_env(extra=None):
    """The process environment without variables that would steer git or the hook."""
    drop = set(hook.GIT_ENV_VARS) | {"CLAUDE_PROJECT_DIR"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(extra or {})
    return env


def git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=dict(clean_env(), **GIT_IDENTITY),
        check=True,
        capture_output=True,
        text=True,
    )


def git_out(cwd, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=dict(clean_env(), **GIT_IDENTITY),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")


def write_marketplace(directory):
    manifest = directory / ".claude-plugin" / "marketplace.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "acme-marketplace", "plugins": []}),
        encoding="utf-8",
    )
    return manifest


def make_marketplace(root):
    """A marketplace repository with one committed file, a.txt."""
    repo = root / "acme-marketplace"
    init_repo(repo)
    write_marketplace(repo)
    (repo / "a.txt").write_text("committed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "marketplace")
    return repo


def run_hook(command, cwd, project_dir=None):
    """Run the hook as Claude Code does: the Bash input on stdin."""
    env = clean_env({"CLAUDE_PROJECT_DIR": str(project_dir)} if project_dir else None)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class StubChecker:
    """Stands in for guidance_check.py. Records what it was given."""

    def __init__(self, code=0, findings=(), error=""):
        self.code = code
        self.findings = list(findings)
        self.error = error
        self.calls = []

    def __call__(self, export_dir, repo):
        files = {}
        for dirpath, _, names in os.walk(export_dir):
            for name in names:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, export_dir)
                with open(full, encoding="utf-8") as handle:
                    files[rel] = handle.read()
        self.calls.append({"export_dir": export_dir, "repo": repo, "files": files})
        return self.code, list(self.findings), self.error


class ScopeTests(unittest.TestCase):
    """The marketplace-repository test decides whether the hook acts at all."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pre-commit-scope-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", "stdout must be empty")

    def test_a_repo_without_marketplace_json_exits_silently(self):
        repo = self.root / "plain-repo"
        init_repo(repo)
        self.assert_silent(run_hook("git commit -m x", repo, project_dir=repo))

    def test_b_marketplace_json_only_in_a_subdirectory_exits_silently(self):
        repo = self.root / "acme-workspace"
        init_repo(repo)
        write_marketplace(repo / "plugins" / "acme-tools")
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "sub")
        self.assert_silent(run_hook("git commit -m x", repo, project_dir=repo))

    def test_c_marketplace_json_only_in_a_submodule_exits_silently(self):
        upstream = self.root / "acme-plugins"
        init_repo(upstream)
        write_marketplace(upstream)
        git(upstream, "add", "-A")
        git(upstream, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "manifest")

        parent = self.root / "acme-workspace"
        init_repo(parent)
        git(
            parent,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(upstream),
            "vendor/acme-plugins",
        )
        # Guard the fixture: the manifest is in the submodule, not above it.
        self.assertTrue(
            (parent / "vendor" / "acme-plugins" / ".claude-plugin" / "marketplace.json").is_file()
        )
        self.assertFalse((parent / ".claude-plugin" / "marketplace.json").exists())
        self.assert_silent(run_hook("git commit -m x", parent, project_dir=parent))

    def test_no_claude_project_dir_falls_back_to_the_input_cwd(self):
        repo = self.root / "plain-repo"
        init_repo(repo)
        self.assert_silent(run_hook("git commit -m x", repo))

    def test_non_commit_command_in_a_marketplace_repo_exits_silently(self):
        repo = make_marketplace(self.root)
        stub = StubChecker(code=1, findings=[{"check": "F-files", "message": "m", "fix": "f"}])
        for command in ["git status", "git log --oneline", "git add -A", "ls -la"]:
            payload = {"tool_input": {"command": command}, "cwd": str(repo)}
            self.assertIsNone(hook.decide(payload, clean_env({"CLAUDE_PROJECT_DIR": str(repo)}), stub))
            self.assert_silent(run_hook(command, repo, project_dir=repo))
        self.assertEqual(stub.calls, [], "the checker must not run for a non-commit")

    def test_commit_in_another_repository_exits_silently(self):
        repo = make_marketplace(self.root)
        other = self.root / "other-repo"
        init_repo(other)
        stub = StubChecker(code=1, findings=[{"check": "F-files", "message": "m", "fix": "f"}])
        for command in [f"git -C {other} commit -m x", f"cd {other} && git commit -m x"]:
            payload = {"tool_input": {"command": command}, "cwd": str(repo)}
            env = clean_env({"CLAUDE_PROJECT_DIR": str(repo)})
            self.assertIsNone(hook.decide(payload, env, stub), command)
        self.assertEqual(stub.calls, [], "a commit outside the project must not be checked")
        self.assert_silent(run_hook(f"git -C {other} commit -m x", repo, project_dir=repo))


class ParseTests(unittest.TestCase):
    """collect() lists the commit and add commands, in order, with their directories."""

    BASE = "/base"

    def test_plain_commit(self):
        self.assertEqual(hook.collect("git commit -m x", self.BASE), [("commit", self.BASE, False)])

    def test_git_c_commit_resolves_the_directory(self):
        self.assertEqual(
            hook.collect("git -C sub commit -m x", self.BASE),
            [("commit", os.path.join(self.BASE, "sub"), False)],
        )

    def test_git_c_options_apply_in_order(self):
        self.assertEqual(
            hook.collect("git -C a -C b commit -m x", self.BASE),
            [("commit", os.path.join(self.BASE, "a", "b"), False)],
        )

    def test_global_config_option_is_skipped(self):
        self.assertEqual(
            hook.collect("git -c user.name=x commit -m y", self.BASE),
            [("commit", self.BASE, False)],
        )

    def test_add_then_commit_in_a_chain(self):
        self.assertEqual(
            hook.collect("git add -A && git commit -m x", self.BASE),
            [("add", self.BASE, ["-A"]), ("commit", self.BASE, False)],
        )

    def test_cd_then_commit_moves_the_directory(self):
        self.assertEqual(
            hook.collect("cd sub && git commit -m x", self.BASE),
            [("commit", os.path.join(self.BASE, "sub"), False)],
        )

    def test_commit_after_a_semicolon_and_a_newline(self):
        self.assertEqual(
            hook.collect("echo hi; git commit -m x", self.BASE),
            [("commit", self.BASE, False)],
        )
        self.assertEqual(
            hook.collect("git status\ngit commit -m x", self.BASE),
            [("commit", self.BASE, False)],
        )

    def test_two_commits_in_one_chain_are_both_listed(self):
        self.assertEqual(
            hook.collect("git commit -m a && git add b && git commit -m c", self.BASE),
            [("commit", self.BASE, False), ("add", self.BASE, ["b"]), ("commit", self.BASE, False)],
        )

    def test_all_flag_forms(self):
        for command in ["git commit -a -m x", "git commit --all -m x", "git commit -am x", "git commit -F m -a"]:
            self.assertEqual(hook.collect(command, self.BASE), [("commit", self.BASE, True)], command)

    def test_a_flag_that_is_the_value_of_another_option_is_not_all(self):
        for command in ["git commit -m -a", "git commit -m x -m -a", "git commit -ma msg"]:
            self.assertEqual(hook.collect(command, self.BASE), [("commit", self.BASE, False)], command)

    def test_quoted_operators_are_not_split(self):
        self.assertEqual(
            hook.collect('git commit -m "a && b; git log"', self.BASE),
            [("commit", self.BASE, False)],
        )

    def test_shell_wrapper_is_read_one_level_deep(self):
        self.assertEqual(
            hook.collect('bash -c "git add -A && git commit -m x"', self.BASE),
            [("add", self.BASE, ["-A"]), ("commit", self.BASE, False)],
        )

    def test_commands_that_are_not_commits_yield_nothing(self):
        for command in ["git log --oneline", "git status # git commit", "ls -la", "echo commit"]:
            self.assertEqual(hook.collect(command, self.BASE), [], command)

    def test_unbalanced_quotes_yield_nothing(self):
        self.assertEqual(hook.collect('git commit -m "unterminated', self.BASE), [])


class DecideTests(unittest.TestCase):
    """Inside a marketplace repository, decide() checks the commit's contents."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pre-commit-decide-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = make_marketplace(self.root)
        self.env = clean_env({"CLAUDE_PROJECT_DIR": str(self.repo)})

    def decide(self, command, checker):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.repo)}
        return hook.decide(payload, self.env, checker)

    def test_a_clean_check_allows_the_commit_silently(self):
        stub = StubChecker(code=0)
        self.assertIsNone(self.decide("git commit -m x", stub))
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(stub.calls[0]["repo"], os.path.realpath(self.repo))

    def test_blocking_findings_deny_with_a_text_report(self):
        stub = StubChecker(
            code=1,
            findings=[
                {
                    "check": "F-agree",
                    "severity": "block",
                    "file": "skills/concept/SKILL.md",
                    "message": "the graph bullet differs from the frontmatter",
                    "fix": "make the bullet match the declared value",
                }
            ],
        )
        reason = self.decide("git commit -m x", stub)
        self.assertIsNotNone(reason)
        self.assertIn("[F-agree]", reason)
        self.assertIn("block: skills/concept/SKILL.md: the graph bullet differs", reason)
        self.assertIn("fix: make the bullet match the declared value", reason)
        self.assertIn("commit again", reason)

    def test_a_check_that_cannot_run_denies(self):
        stub = StubChecker(code=2, findings=[], error="upstream could not be resolved")
        reason = self.decide("git commit -m x", stub)
        self.assertIsNotNone(reason)
        self.assertIn("could not run", reason)
        self.assertIn("upstream could not be resolved", reason)

    def test_staged_export_holds_the_index_not_the_working_copy(self):
        (self.repo / "a.txt").write_text("staged\n", encoding="utf-8")
        git(self.repo, "add", "a.txt")
        (self.repo / "a.txt").write_text("unstaged\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        stub = StubChecker(code=0)
        self.assertIsNone(self.decide("git commit -m x", stub))
        files = stub.calls[0]["files"]
        self.assertEqual(files["a.txt"], "staged\n")
        self.assertNotIn("new.txt", files)
        self.assertFalse(os.path.exists(stub.calls[0]["export_dir"]), "the export must be removed")

    def test_git_add_in_the_chain_is_replayed_without_touching_the_real_index(self):
        (self.repo / "a.txt").write_text("unstaged\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        stub = StubChecker(code=0)
        self.assertIsNone(self.decide("git add -A && git commit -m x", stub))
        files = stub.calls[0]["files"]
        self.assertEqual(files["a.txt"], "unstaged\n")
        self.assertEqual(files["new.txt"], "untracked\n")
        self.assertNotIn("new.txt", git_out(self.repo, "ls-files").split("\n"))
        self.assertIn("new.txt", git_out(self.repo, "status", "--porcelain"))

    def test_all_flag_exports_the_tracked_working_copy(self):
        (self.repo / "a.txt").write_text("unstaged\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        stub = StubChecker(code=0)
        self.assertIsNone(self.decide("git commit -a -m x", stub))
        files = stub.calls[0]["files"]
        self.assertEqual(files["a.txt"], "unstaged\n")
        self.assertNotIn("new.txt", files)

    def test_git_c_into_a_directory_of_the_same_repository_is_checked(self):
        sub = self.repo / "plugins" / "acme-tools"
        sub.mkdir(parents=True)
        (sub / "README.md").write_text("tool\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        stub = StubChecker(code=1, findings=[{"check": "F-files", "message": "m", "fix": "f"}])
        self.assertIsNotNone(self.decide("git -C plugins/acme-tools commit -m x", stub))
        self.assertEqual(stub.calls[0]["repo"], os.path.realpath(self.repo))
        self.assertIn("plugins/acme-tools/README.md", stub.calls[0]["files"])

    def test_deny_output_has_the_pretooluse_shape(self):
        out = hook.deny_output("reason text")
        self.assertEqual(
            out,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "reason text",
                }
            },
        )


class HooksJsonTests(unittest.TestCase):
    def test_a_pretooluse_bash_hook_runs_the_script_with_a_300_second_timeout(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = config["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "Bash")
        (hook_entry,) = entries[0]["hooks"]
        self.assertEqual(hook_entry["type"], "command")
        self.assertEqual(
            hook_entry["command"],
            'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pre_commit_hook.py"',
        )
        self.assertEqual(hook_entry["timeout"], 300)


if __name__ == "__main__":
    unittest.main()
