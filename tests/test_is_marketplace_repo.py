"""Scope tests for plugins/guidance-activation-check/scripts/is_marketplace_repo.py.

The script must exit 0 only in a marketplace repository, as the guidance
checks define it, and must print nothing in every case.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "guidance-activation-check"
    / "scripts"
    / "is_marketplace_repo.py"
)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.invalid",
}


def git(cwd, *args):
    env = dict(os.environ, **GIT_IDENTITY)
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


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


def run_script(*args, cwd=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class IsMarketplaceRepoTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="is-marketplace-repo-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def assert_silent(self, result):
        self.assertEqual(result.stdout, "", "stdout must be empty")
        self.assertEqual(result.stderr, "", "stderr must be empty")

    def test_a_git_repo_with_marketplace_json_at_root_exits_0(self):
        repo = self.root / "acme-marketplace"
        init_repo(repo)
        write_marketplace(repo)
        result = run_script(str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_silent(result)

    def test_b_a_git_repo_without_marketplace_json_exits_1(self):
        repo = self.root / "plain-repo"
        init_repo(repo)
        result = run_script(str(repo))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_c_marketplace_json_only_in_a_subdirectory_exits_1(self):
        repo = self.root / "acme-workspace"
        init_repo(repo)
        write_marketplace(repo / "plugins" / "acme-tools")
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "sub")

        result = run_script(str(repo))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

        # The subdirectory itself holds the file, but its git top level is
        # the repository root, so it does not qualify either.
        sub = repo / "plugins" / "acme-tools"
        result = run_script(str(sub))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_d_marketplace_json_only_in_a_submodule_exits_1(self):
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
        # Guard the fixture: the manifest exists in the submodule, not above it.
        self.assertTrue(
            (parent / "vendor" / "acme-plugins" / ".claude-plugin" / "marketplace.json").is_file()
        )
        self.assertFalse((parent / ".claude-plugin" / "marketplace.json").exists())

        result = run_script(str(parent))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_e_non_git_directory_with_marketplace_json_exits_1(self):
        plain = self.root / "unpacked-marketplace"
        write_marketplace(plain)
        result = run_script(str(plain))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_f_missing_directory_exits_1(self):
        result = run_script(str(self.root / "does-not-exist"))
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_f_empty_directory_argument_exits_1(self):
        # An unexpanded placeholder reaches the script as an empty argument.
        result = run_script("")
        self.assertEqual(result.returncode, 1)
        self.assert_silent(result)

    def test_g_default_directory_comes_from_claude_project_dir(self):
        repo = self.root / "acme-marketplace"
        init_repo(repo)
        write_marketplace(repo)
        result = run_script(env_extra={"CLAUDE_PROJECT_DIR": str(repo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_silent(result)

    def test_g_default_directory_falls_back_to_current_directory(self):
        repo = self.root / "acme-marketplace"
        init_repo(repo)
        write_marketplace(repo)
        result = run_script(cwd=str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_silent(result)


if __name__ == "__main__":
    unittest.main()
