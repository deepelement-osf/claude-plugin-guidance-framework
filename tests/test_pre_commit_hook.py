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


def run_hook(command, cwd, project_dir=None, extra_env=None):
    """Run the hook as Claude Code does: the Bash input on stdin. extra_env is added to its environment."""
    extra = {"CLAUDE_PROJECT_DIR": str(project_dir)} if project_dir else {}
    extra.update(extra_env or {})
    env = clean_env(extra)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    return subprocess.run(
        [sys.executable, "-B", str(HOOK)],
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


def write_plugin_marketplace(root, name, plugins):
    """A marketplace with plugins: dicts of name, version and optional deps (manifest dependency dicts)."""
    entries = []
    for spec in plugins:
        entry = {"name": spec["name"], "source": f"./plugins/{spec['name']}"}
        if spec.get("deps"):
            entry["dependencies"] = spec["deps"]
        entries.append(entry)
        plugin_json = root / "plugins" / spec["name"] / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir(parents=True, exist_ok=True)
        plugin_json.write_text(json.dumps({"name": spec["name"], "version": spec["version"]}), encoding="utf-8")
    manifest = root / ".claude-plugin" / "marketplace.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": name, "owner": {"name": "Test"}, "plugins": entries}), encoding="utf-8")


class UpstreamCommitTests(unittest.TestCase):
    """A commit in a marketplace that depends on an upstream, through the real hook and checker.

    The upstream is a git repository named acme-core, with the tag acme-phase--v1.0.0.
    The downstream compiles against a copy of it, given with --upstreams, and records
    that version. Its settings register acme-core by git url. Nothing else holds the
    upstream, so the hook must fetch the recorded tag from that url, and the check
    must pass on it. The fake claude makes the official validation pass.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pre-commit-upstream-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        fake_bin = self.tmp / "bin"
        fake_bin.mkdir()
        claude = fake_bin / "claude"
        claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        claude.chmod(0o755)
        self.data = self.tmp / "data"
        self.env = {
            "HOME": str(self.tmp / "home"),
            "CLAUDE_PLUGIN_DATA": str(self.data),
            "GUIDANCE_CHECK_MARKETPLACES_DIR": str(self.tmp / "registry"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        self.core = self.tmp / "upstreams" / "acme-core"
        self.repo = self.tmp / "acme-web"

        write_plugin_marketplace(self.core, "acme-core", [{"name": "acme-phase", "version": "1.0.0"}])
        init_repo(self.core)
        git(self.core, "add", "-A")
        git(self.core, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "core 1.0.0")
        git(self.core, "tag", "acme-phase--v1.0.0")

        write_plugin_marketplace(self.repo, "acme-web", [{
            "name": "web-app", "version": "1.0.0",
            "deps": [{"name": "acme-phase", "marketplace": "acme-core", "version": "^1.0.0"}],
        }])
        manifest = self.repo / ".claude-plugin" / "marketplace.json"
        declared = json.loads(manifest.read_text(encoding="utf-8"))
        (self.repo / ".claude-plugin" / "guidance.json").write_text(
            json.dumps({"pluginPrefix": "web"}), encoding="utf-8")
        declared["allowCrossMarketplaceDependenciesOn"] = ["acme-core"]
        manifest.write_text(json.dumps(declared), encoding="utf-8")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text(json.dumps({
            "extraKnownMarketplaces": {"acme-core": {"source": {"source": "git", "url": str(self.core)}}},
        }), encoding="utf-8")
        init_repo(self.repo)
        (self.repo / "LICENSE").write_text("Synthetic license text for a unit test.\n", encoding="utf-8")
        (self.repo / "README.md").write_text(
            "# acme-web\n\n"
            "Synthetic marketplace for the upstream commit tests.\n\n"
            "## Required marketplaces\n\n"
            "Register these in your consuming workspace before installing plugins from this\n"
            "marketplace. Settings are not transitive; nothing registers them for you. Register\n"
            "each marketplace under exactly its name below.\n\n"
            "| Marketplace name | Registration source | Plugins used (range) | Why |\n"
            "|---|---|---|---|\n"
            "| `acme-core` | `acme/acme-core` (git) | `acme-phase` `^1.0.0` | The web app builds on the core phase |\n\n"
            "## License\n\n"
            "It is licensed under the terms in the LICENSE file.\n",
            encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "marketplace")

        # Compile against the upstream copy, so the graph records acme-phase 1.0.0.
        compile_run = subprocess.run(
            [sys.executable, "-B", str(hook.CHECKER), str(self.repo), "--compile", "--no-official", "--no-pin",
             "--upstreams", str(self.tmp / "upstreams")],
            cwd=str(self.repo), env=dict(clean_env(self.env), **GIT_IDENTITY),
            capture_output=True, text=True, check=False)
        self.assertEqual(compile_run.returncode, 0, compile_run.stdout + compile_run.stderr)
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "compiled")
        (self.repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
        git(self.repo, "add", "NOTES.md")

    def test_commit_passes_and_the_recorded_upstream_is_fetched_into_the_cache(self):
        result = run_hook("git commit -m notes", self.repo, project_dir=self.repo, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", result.stdout)
        cached = self.data / "upstreams" / "acme-core" / ".claude-plugin" / "marketplace.json"
        self.assertTrue(cached.is_file(), "the hook must have fetched acme-core into the cache")

    def test_commit_is_denied_when_the_upstream_cannot_be_found(self):
        shutil.rmtree(self.core)
        result = run_hook("git commit -m notes", self.repo, project_dir=self.repo, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        decision = reply["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("X-resolve", decision["permissionDecisionReason"])
        self.assertIn("acme-core", decision["permissionDecisionReason"])


class TwoPluginUpstreamCommitTests(unittest.TestCase):
    """A commit in a marketplace that depends on two plugins of one upstream, at two versions.

    The upstream is a git repository named acme-core, with one tag per plugin version:
    acme-core-build--v1.0.0 is on its first commit, and acme-core-deliver--v1.1.0 on its
    second, where build is still 1.0.0. The downstream compiles against the upstream and
    records build 1.0.0 and deliver 1.1.0. No single tag holds both, so the hook must fetch
    each plugin from its own tag. The fake claude makes the official validation pass.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pre-commit-two-plugins-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        fake_bin = self.tmp / "bin"
        fake_bin.mkdir()
        claude = fake_bin / "claude"
        claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        claude.chmod(0o755)
        self.data = self.tmp / "data"
        self.env = {
            "HOME": str(self.tmp / "home"),
            "CLAUDE_PLUGIN_DATA": str(self.data),
            "GUIDANCE_CHECK_MARKETPLACES_DIR": str(self.tmp / "registry"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        self.core = self.tmp / "upstreams" / "acme-core"
        self.repo = self.tmp / "acme-web"

        init_repo(self.core)
        write_plugin_marketplace(self.core, "acme-core", [
            {"name": "acme-core-build", "version": "1.0.0"},
            {"name": "acme-core-deliver", "version": "1.0.0"},
        ])
        git(self.core, "add", "-A")
        git(self.core, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "core 1.0.0")
        git(self.core, "tag", "acme-core-build--v1.0.0")
        git(self.core, "tag", "acme-core-deliver--v1.0.0")
        write_plugin_marketplace(self.core, "acme-core", [
            {"name": "acme-core-build", "version": "1.0.0"},
            {"name": "acme-core-deliver", "version": "1.1.0"},
        ])
        git(self.core, "add", "-A")
        git(self.core, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "deliver 1.1.0")
        git(self.core, "tag", "acme-core-deliver--v1.1.0")

        write_plugin_marketplace(self.repo, "acme-web", [{
            "name": "web-app", "version": "1.0.0",
            "deps": [
                {"name": "acme-core-build", "marketplace": "acme-core", "version": "^1.0.0"},
                {"name": "acme-core-deliver", "marketplace": "acme-core", "version": "^1.1.0"},
            ],
        }])
        manifest = self.repo / ".claude-plugin" / "marketplace.json"
        declared = json.loads(manifest.read_text(encoding="utf-8"))
        (self.repo / ".claude-plugin" / "guidance.json").write_text(
            json.dumps({"pluginPrefix": "web"}), encoding="utf-8")
        declared["allowCrossMarketplaceDependenciesOn"] = ["acme-core"]
        manifest.write_text(json.dumps(declared), encoding="utf-8")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text(json.dumps({
            "extraKnownMarketplaces": {"acme-core": {"source": {"source": "git", "url": str(self.core)}}},
        }), encoding="utf-8")
        init_repo(self.repo)
        (self.repo / "LICENSE").write_text("Synthetic license text for a unit test.\n", encoding="utf-8")
        (self.repo / "README.md").write_text(
            "# acme-web\n\n"
            "Synthetic marketplace for the two-plugin upstream commit tests.\n\n"
            "## Required marketplaces\n\n"
            "Register these in your consuming workspace before installing plugins from this\n"
            "marketplace. Settings are not transitive; nothing registers them for you. Register\n"
            "each marketplace under exactly its name below.\n\n"
            "| Marketplace name | Registration source | Plugins used (range) | Why |\n"
            "|---|---|---|---|\n"
            "| `acme-core` | `acme/acme-core` (git) | `acme-core-build` `^1.0.0`, `acme-core-deliver` `^1.1.0` "
            "| The web app builds on both core plugins |\n\n"
            "## License\n\n"
            "It is licensed under the terms in the LICENSE file.\n",
            encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "marketplace")

        compile_run = subprocess.run(
            [sys.executable, "-B", str(hook.CHECKER), str(self.repo), "--compile", "--no-official", "--no-pin",
             "--upstreams", str(self.tmp / "upstreams")],
            cwd=str(self.repo), env=dict(clean_env(self.env), **GIT_IDENTITY),
            capture_output=True, text=True, check=False)
        self.assertEqual(compile_run.returncode, 0, compile_run.stdout + compile_run.stderr)
        graph = json.loads((self.repo / "concept-graph.json").read_text(encoding="utf-8"))
        self.assertEqual(graph["upstreams"][0]["plugins"],
                         {"acme-core-build": "1.0.0", "acme-core-deliver": "1.1.0"})
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "compiled")
        (self.repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
        git(self.repo, "add", "NOTES.md")

    def test_commit_passes_with_each_plugin_fetched_from_its_own_tag(self):
        result = run_hook("git commit -m notes", self.repo, project_dir=self.repo, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", result.stdout)
        cached = self.data / "upstreams" / "acme-core" / ".claude-plugin" / "marketplace.json"
        self.assertTrue(cached.is_file(), "the hook must have fetched acme-core into the cache")

    def test_a_later_commit_passes_from_the_cache_alone(self):
        self.assertEqual(run_hook("git commit -m notes", self.repo, project_dir=self.repo,
                                  extra_env=self.env).returncode, 0)
        shutil.rmtree(self.core)
        result = run_hook("git commit -m again", self.repo, project_dir=self.repo, extra_env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", result.stdout)


if __name__ == "__main__":
    unittest.main()
