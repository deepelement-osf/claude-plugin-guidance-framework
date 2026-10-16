"""Tests for gc_resolve: where an upstream marketplace is read from, and which version it must hold.

Each test works in a temporary directory. HOME, the registered-copy directory and
the cache directory are all inside it, so no test reads or writes the real ones.
Upstream sources are local git repositories with <plugin>--v<version> tags, which
the settings file names as a git url.

Run from the repository root:

    python3 -B -m unittest tests.test_gc_resolve -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gc_model import COMPILED_FILE, Marketplace, Options  # noqa: E402
from gc_resolve import ResolveError, resolve  # noqa: E402

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}
DEPENDS_ON_CORE = [{"name": "acme-phase", "marketplace": "acme-core", "version": "^1.0.0"}]
TWO_PLUGINS = [
    {"name": "acme-core-build", "marketplace": "acme-core", "version": "^1.0.0"},
    {"name": "acme-core-deliver", "marketplace": "acme-core", "version": "^1.1.0"},
]
# acme-core-build stays at 1.0.0 while acme-core-deliver moves to 1.1.0, so no single
# tag holds both versions a dependent needs. The second commit changes build's
# directory without a new version; a fetch must not keep that change.
TWO_PLUGIN_HISTORY = [
    {"plugins": [("acme-core-build", "1.0.0"), ("acme-core-deliver", "1.0.0")],
     "tags": ["acme-core-build--v1.0.0", "acme-core-deliver--v1.0.0"],
     "files": {"plugins/acme-core-build/MARK": "build at its own tag\n"}},
    {"plugins": [("acme-core-build", "1.0.0"), ("acme-core-deliver", "1.1.0")],
     "tags": ["acme-core-deliver--v1.1.0"],
     "files": {"plugins/acme-core-build/LATER": "after build's tag\n"}},
]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def git(cwd: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    env.update(GIT_IDENTITY)
    result = subprocess.run(["git", *args], cwd=str(cwd), env=env,
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")


def write_marketplace(root: Path, name: str, plugins) -> Path:
    """plugins: dicts with name, version and optional deps (manifest dependency dicts)."""
    entries = []
    for spec in plugins:
        entry = {"name": spec["name"], "source": f"./plugins/{spec['name']}"}
        if spec.get("deps"):
            entry["dependencies"] = spec["deps"]
        entries.append(entry)
        write_json(root / "plugins" / spec["name"] / ".claude-plugin" / "plugin.json",
                   {"name": spec["name"], "version": spec["version"]})
    write_json(root / ".claude-plugin" / "marketplace.json",
               {"name": name, "owner": {"name": "Test"}, "plugins": entries})
    return root


def make_history(root: Path, name: str, commits) -> Path:
    """A git repository holding marketplace name, one commit per entry of commits.

    An entry has plugins (name, version) pairs for the marketplace at that commit, tags
    for the <plugin>--v<version> tags the commit carries, and files for extra files the
    commit adds, as paths from the repository root to text.
    """
    root.mkdir(parents=True)
    git(root, "init", "-q")
    for commit in commits:
        write_marketplace(root, name, [{"name": p, "version": v} for p, v in commit["plugins"]])
        for path, text in commit.get("files", {}).items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "commit")
        for tag in commit.get("tags", []):
            git(root, "tag", tag)
    return root


def write_compiled(root: Path, recorded) -> None:
    """recorded maps an upstream name to {plugin: version}, as the compiled graph records it."""
    upstreams = [{"marketplace": name, "plugins": plugins, "graphHash": "sha256:" + "0" * 64}
                 for name, plugins in sorted(recorded.items())]
    write_json(root / COMPILED_FILE, {"upstreams": upstreams})


def make_source(root: Path, name: str, plugin: str, versions, deps=None) -> Path:
    """A git repository holding marketplace name with one plugin, one commit and tag per version."""
    root.mkdir(parents=True)
    git(root, "init", "-q")
    for version in versions:
        spec = {"name": plugin, "version": version, "deps": deps}
        write_marketplace(root, name, [spec])
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"{plugin} {version}")
        git(root, "tag", f"{plugin}--v{version}")
    return root


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-resolve-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.registry = self.tmp / "registry"
        self.data = self.tmp / "data"
        env = mock.patch.dict(os.environ, {
            "HOME": str(self.tmp / "home"),
            "GUIDANCE_CHECK_MARKETPLACES_DIR": str(self.registry),
            "CLAUDE_PLUGIN_DATA": str(self.data),
        })
        env.start()
        self.addCleanup(env.stop)

    def downstream(self, deps=DEPENDS_ON_CORE, recorded=None, sources=None) -> Marketplace:
        """A marketplace acme-web. sources maps a marketplace name to a git url for the settings file."""
        root = write_marketplace(self.tmp / "acme-web", "acme-web",
                                 [{"name": "acme-app", "version": "1.0.0", "deps": deps}])
        if recorded is not None:
            write_compiled(root, recorded)
        if sources:
            known = {name: {"source": {"source": "git", "url": url}} for name, url in sources.items()}
            write_json(root / ".claude" / "settings.json", {"extraKnownMarketplaces": known})
        return Marketplace.load(root)

    def core_at(self, directory: Path, version: str) -> Path:
        return write_marketplace(directory, "acme-core", [{"name": "acme-phase", "version": version}])

    # -- (a) --upstreams ------------------------------------------------------

    def test_a_given_directory_is_used_as_it_is(self):
        self.core_at(self.tmp / "upstreams" / "acme-core", "1.0.0")
        loaded = resolve(self.downstream(), Options(upstreams_dir=self.tmp / "upstreams"))
        self.assertEqual(loaded["acme-core"].root, self.tmp / "upstreams" / "acme-core")

    def test_a_given_directory_with_an_invalid_guidance_file_is_refused(self):
        # AD2 compares the upstream's prefix, so a copy whose guidance.json the loader would ignore is not used.
        core = self.core_at(self.tmp / "upstreams" / "acme-core", "1.0.0")
        (core / ".claude-plugin" / "guidance.json").write_text('{"pluginPrefix": "Acme"}', encoding="utf-8")
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(), Options(upstreams_dir=self.tmp / "upstreams"))
        self.assertIn("guidance.json is not valid", caught.exception.message)
        self.assertIn("AD2", caught.exception.fix)

    def test_a_absent_directory_falls_through_to_the_next_place(self):
        cache = self.data / "upstreams" / "acme-core"
        self.core_at(cache, "1.0.0")
        loaded = resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}}),
                         Options(upstreams_dir=self.tmp / "upstreams"))
        self.assertEqual(loaded["acme-core"].root, cache)

    # -- (b) Claude Code's registered copy ----------------------------------

    def test_b_registered_copy_at_the_recorded_version_is_used(self):
        copy = make_source(self.registry / "acme-core", "acme-core", "acme-phase", ["1.0.0"])
        loaded = resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}}), Options())
        self.assertEqual(loaded["acme-core"].root, copy)

    def test_b_registered_copy_with_an_invalid_guidance_file_is_refused(self):
        copy = make_source(self.registry / "acme-core", "acme-core", "acme-phase", ["1.0.0"])
        (copy / ".claude-plugin" / "guidance.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}}), Options())
        self.assertIn("Claude Code's registered copy", caught.exception.message)
        self.assertIn("guidance.json is not valid", caught.exception.message)

    def test_b_registered_copy_at_another_version_is_refused(self):
        make_source(self.registry / "acme-core", "acme-core", "acme-phase", ["1.0.0"])
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.1.0"}}), Options())
        self.assertIn("Claude Code's registered copy", caught.exception.message)
        self.assertIn("1.1.0 is needed", caught.exception.message)

    def test_b_registered_copy_with_one_plugin_at_another_version_is_refused(self):
        write_marketplace(self.registry / "acme-core", "acme-core", [
            {"name": "acme-core-build", "version": "1.0.0"},
            {"name": "acme-core-deliver", "version": "1.0.0"},
        ])
        recorded = {"acme-core": {"acme-core-build": "1.0.0", "acme-core-deliver": "1.1.0"}}
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(deps=TWO_PLUGINS, recorded=recorded), Options())
        self.assertIn("Claude Code's registered copy", caught.exception.message)
        self.assertIn("it has acme-core-deliver 1.0.0, and 1.1.0 is needed", caught.exception.message)

    # -- (c) the cache ------------------------------------------------------

    def test_c_cache_at_the_recorded_version_is_used(self):
        cache = self.data / "upstreams" / "acme-core"
        self.core_at(cache, "1.0.0")
        loaded = resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}}), Options())
        self.assertEqual(loaded["acme-core"].root, cache)

    def test_c_cache_with_one_plugin_at_another_version_is_refused_and_fetched(self):
        source = make_history(self.tmp / "source" / "acme-core", "acme-core", TWO_PLUGIN_HISTORY)
        cache = self.data / "upstreams" / "acme-core"
        write_marketplace(cache, "acme-core", [
            {"name": "acme-core-build", "version": "1.0.0"},
            {"name": "acme-core-deliver", "version": "1.0.0"},
        ])
        recorded = {"acme-core": {"acme-core-build": "1.0.0", "acme-core-deliver": "1.1.0"}}
        loaded = resolve(self.downstream(deps=TWO_PLUGINS, recorded=recorded,
                                         sources={"acme-core": str(source)}), Options())
        self.assertEqual(loaded["acme-core"].root, cache)
        self.assertEqual(loaded["acme-core"].plugins["acme-core-deliver"].version, "1.1.0")

    # -- (d) fetch, then cache ----------------------------------------------

    def test_d_fetches_the_recorded_tag_then_later_runs_use_the_cache(self):
        source = make_source(self.tmp / "source" / "acme-core", "acme-core", "acme-phase", ["1.0.0", "1.1.0"])
        recorded = {"acme-core": {"acme-phase": "1.0.0"}}
        loaded = resolve(self.downstream(recorded=recorded, sources={"acme-core": str(source)}), Options())
        cache = self.data / "upstreams" / "acme-core"
        self.assertEqual(loaded["acme-core"].root, cache)
        self.assertEqual(loaded["acme-core"].plugins["acme-phase"].version, "1.0.0")
        self.assertEqual(sorted(p.name for p in (self.data / "upstreams").iterdir()), ["acme-core"])

        shutil.rmtree(source)
        again = resolve(self.downstream(recorded=recorded), Options())
        self.assertEqual(again["acme-core"].root, cache)

    def test_d_a_missing_tag_fails_and_names_the_source(self):
        source = make_source(self.tmp / "source" / "acme-core", "acme-core", "acme-phase", ["1.0.0"])
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(recorded={"acme-core": {"acme-phase": "3.0.0"}},
                                    sources={"acme-core": str(source)}), Options())
        self.assertIn(f"cannot fetch acme-core from {source}", caught.exception.message)
        self.assertFalse((self.data / "upstreams" / "acme-core").exists())

    def test_d_a_plugin_missing_at_its_tag_fails_and_names_the_tag(self):
        source = make_history(self.tmp / "source" / "acme-core", "acme-core", TWO_PLUGIN_HISTORY)
        recorded = {"acme-core": {"acme-core-build": "1.0.0", "acme-core-deliver": "9.0.0"}}
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(deps=TWO_PLUGINS, recorded=recorded,
                                    sources={"acme-core": str(source)}), Options())
        self.assertIn(f"cannot fetch acme-core from {source} at tag acme-core-deliver--v9.0.0",
                      caught.exception.message)
        self.assertFalse((self.data / "upstreams" / "acme-core").exists())
        self.assertEqual(list((self.data / "upstreams").iterdir()), [], "the staging directory must be removed")

    def test_d_two_plugins_at_two_tags_are_fetched_each_from_its_own_tag(self):
        source = make_history(self.tmp / "source" / "acme-core", "acme-core", TWO_PLUGIN_HISTORY)
        recorded = {"acme-core": {"acme-core-build": "1.0.0", "acme-core-deliver": "1.1.0"}}
        loaded = resolve(self.downstream(deps=TWO_PLUGINS, recorded=recorded,
                                         sources={"acme-core": str(source)}), Options())
        cache = self.data / "upstreams" / "acme-core"
        self.assertEqual(loaded["acme-core"].root, cache)
        self.assertEqual(loaded["acme-core"].plugins["acme-core-build"].version, "1.0.0")
        self.assertEqual(loaded["acme-core"].plugins["acme-core-deliver"].version, "1.1.0")
        self.assertEqual((cache / "plugins" / "acme-core-build" / "MARK").read_text(encoding="utf-8"),
                         "build at its own tag\n")
        self.assertFalse((cache / "plugins" / "acme-core-build" / "LATER").exists(),
                         "build's directory must come from its own tag, not from the newer commit")
        self.assertEqual(sorted(p.name for p in (self.data / "upstreams").iterdir()), ["acme-core"])

        # The second run is served by the cache alone: the source is gone.
        shutil.rmtree(source)
        again = resolve(self.downstream(deps=TWO_PLUGINS, recorded=recorded), Options())
        self.assertEqual(again["acme-core"].root, cache)
        self.assertEqual(again["acme-core"].plugins["acme-core-build"].version, "1.0.0")
        self.assertEqual(again["acme-core"].plugins["acme-core-deliver"].version, "1.1.0")

    # -- the chain ----------------------------------------------------------

    def test_the_second_level_is_read_from_its_own_source(self):
        base = make_source(self.tmp / "base-source" / "acme-base", "acme-base", "acme-util", ["2.0.0"])
        write_marketplace(self.tmp / "upstreams" / "acme-core", "acme-core", [{
            "name": "acme-phase", "version": "1.0.0",
            "deps": [{"name": "acme-util", "marketplace": "acme-base", "version": "^2.0.0"}],
        }])
        loaded = resolve(self.downstream(sources={"acme-base": str(base)}),
                         Options(upstreams_dir=self.tmp / "upstreams"))
        self.assertEqual(set(loaded), {"acme-core", "acme-base"})
        self.assertEqual(loaded["acme-base"].plugins["acme-util"].version, "2.0.0")

    # -- versions -----------------------------------------------------------

    def test_compile_takes_the_newest_version_in_range_even_when_one_is_recorded(self):
        source = make_source(self.tmp / "source" / "acme-core", "acme-core", "acme-phase",
                             ["1.0.0", "1.1.0", "1.2.0", "2.0.0"])
        loaded = resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}},
                                         sources={"acme-core": str(source)}),
                         Options(compile=True))
        self.assertEqual(loaded["acme-core"].plugins["acme-phase"].version, "1.2.0")

    def test_check_uses_the_recorded_version_not_the_newest(self):
        source = make_source(self.tmp / "source" / "acme-core", "acme-core", "acme-phase", ["1.0.0", "1.1.0"])
        loaded = resolve(self.downstream(recorded={"acme-core": {"acme-phase": "1.0.0"}},
                                         sources={"acme-core": str(source)}), Options())
        self.assertEqual(loaded["acme-core"].plugins["acme-phase"].version, "1.0.0")

    # -- nothing found ------------------------------------------------------

    def test_nothing_found_names_each_place_tried_in_order(self):
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(), Options())
        message = caught.exception.message
        self.assertIn("acme-core", message)
        order = ["--upstreams: not given", "Claude Code's registered copy", "the cache", "fetch"]
        positions = [message.index(item) for item in order]
        self.assertEqual(positions, sorted(positions), message)
        self.assertIn(".claude/settings.json", caught.exception.fix)

    def test_nothing_found_reports_a_given_directory_that_is_absent(self):
        with self.assertRaises(ResolveError) as caught:
            resolve(self.downstream(), Options(upstreams_dir=self.tmp / "upstreams"))
        self.assertIn(f"--upstreams: {self.tmp / 'upstreams' / 'acme-core'} is not present",
                      caught.exception.message)


if __name__ == "__main__":
    unittest.main()
