"""Tests for the concept-graph core: the YAML subset, the schema subset, the model,
the compiler and the command. Standard library only.

Run from the repository root:

    python3 -m unittest tests.test_gc_core -v
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gc_compile  # noqa: E402
import guidance_check  # noqa: E402
from gc_compile import CompileError, compile, graph_hash, render, write_compiled  # noqa: E402
from gc_model import Finding, Marketplace, MarketplaceError, concept_name, declared_references  # noqa: E402
from gc_parse import (  # noqa: E402
    FrontmatterError,
    SchemaSubsetError,
    YamlSubsetError,
    extract_frontmatter,
    load_json,
    parse_graph_participation,
    parse_yaml_subset,
    participation_bullets,
    realizes_block,
    validate_json_schema,
)

CHECK_SCRIPT = SCRIPTS / "guidance_check.py"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _clean_env(**extra):
    drop = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(GIT_IDENTITY)
    env.update(extra)
    return env


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value) -> None:
    write(path, json.dumps(value, indent=2) + "\n")


CONCEPT_SKILL = """---
name: concept
description: a phase concept
graph:
  role: phase
  interaction: pause
---

# Phase

## Graph participation

- **Entry:** the start of the phase
- **Exit:** the end of the phase
"""

CAPABILITY_SKILL = """---
name: concept
description: a capability concept
---

# Glossary
"""

REALIZATION_SKILL = """---
name: realize-local
description: a local realization
default: true
graph:
  runs: local
  builds_on: none
---

# Local realization

```realizes
concept: {concept}
name: {name}
```
"""


def build_marketplace(root: Path, name: str, plugins, order=None) -> Path:
    """Write a marketplace. plugins: dicts with name, version, concept (bool),
    realizations (list of str), capability (bool), deps (list of dicts).
    order, when given, lists plugin names in the order the manifest uses."""
    by_name = {p["name"]: p for p in plugins}
    names = order or [p["name"] for p in plugins]
    entries = []
    prefix = name.split("-", 1)[0]
    for plugin_name in names:
        spec = by_name[plugin_name]
        entry = {"name": plugin_name, "source": f"./plugins/{plugin_name}"}
        if spec.get("deps"):
            entry["dependencies"] = spec["deps"]
        entries.append(entry)
        base = root / "plugins" / plugin_name
        write_json(base / ".claude-plugin" / "plugin.json",
                   {"name": plugin_name, "version": spec.get("version", "1.0.0")})
        if spec.get("concept"):
            write(base / "skills" / "concept" / "SKILL.md", CONCEPT_SKILL)
            contract = base / "skills" / "realization-contract"
            write_json(contract / "graph-contract.json",
                       {"graphSpecVersion": "1.0", "outputs": ["plan"]})
            write_json(contract / "schema.json", {"type": "object", "required": ["id"]})
            write(contract / "SKILL.md", "---\nname: realization-contract\n---\n")
        if spec.get("capability"):
            write(base / "skills" / "concept" / "SKILL.md", CAPABILITY_SKILL)
        for realization in spec.get("realizations", []):
            concept_ref = f"{concept_name(plugin_name, prefix)}@{name}"
            write(base / "skills" / f"realize-{realization}" / "SKILL.md",
                  REALIZATION_SKILL.format(concept=concept_ref, name=realization))
    write_json(root / ".claude-plugin" / "marketplace.json",
               {"name": name, "owner": {"name": "Test"}, "plugins": entries})
    return root


def make_git_repo(path: Path, tag: str = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    subprocess.run(["git", "init", "-q"], cwd=str(path), env=env, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=str(path), env=env, check=True)
    if tag:
        subprocess.run(["git", "tag", tag], cwd=str(path), env=env, check=True)
    return path


def run_check(directory, *args):
    home = tempfile.mkdtemp(prefix="gc-home-")
    env = _clean_env(HOME=home, CLAUDE_PLUGIN_DATA=home)
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), str(directory), "--no-official", *args],
        capture_output=True, text=True, env=env, check=False)


class YamlSubsetTests(unittest.TestCase):
    def test_plain_scalars_and_nested_mapping(self):
        text = ("name: demo\ncount: 3\nratio: 1.5\nflag: true\nempty: null\n"
                "items:\n  - alpha\n  - 2\nnested:\n  key: value\n")
        self.assertEqual(parse_yaml_subset(text), {
            "name": "demo", "count": 3, "ratio": 1.5, "flag": True, "empty": None,
            "items": ["alpha", 2], "nested": {"key": "value"},
        })

    def test_double_quoted_string_is_a_string(self):
        self.assertEqual(parse_yaml_subset('a: "text: with colon"'), {"a": "text: with colon"})

    def test_rejected_constructs_name_the_line(self):
        cases = {
            "anchor": "a: 1\nb: &x 2\n",
            "alias": "a: 1\nb: *x\n",
            "tag": "a: 1\nb: !!str 2\n",
            "block scalar": "a: 1\nb: |\n  text\n",
            "single quotes": "a: 1\nb: 'quoted'\n",
            "duplicate key": "a: 1\na: 2\n",
            "tab indentation": "a:\n\tb: 1\n",
            "document marker": "a: 1\n---\nb: 2\n",
            "nested flow": "a: [[1]]\n",
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(YamlSubsetError) as ctx:
                    parse_yaml_subset(text, source="case")
                self.assertIn("line", str(ctx.exception))

    def test_error_reports_the_offending_line_number(self):
        with self.assertRaises(YamlSubsetError) as ctx:
            parse_yaml_subset("a: 1\nb: &x 2\n")
        self.assertIn("line 2", str(ctx.exception))

    def test_frontmatter_split(self):
        front, body = extract_frontmatter("---\nname: x\n---\nbody\n")
        self.assertEqual(front, "name: x")
        self.assertIn("body", body)
        self.assertEqual(extract_frontmatter("no front matter\n"), (None, "no front matter\n"))
        with self.assertRaises(FrontmatterError):
            extract_frontmatter("---\nname: x\n")

    def test_load_json_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory(prefix="gc-json-") as tmp:
            path = Path(tmp) / "dup.json"
            write(path, '{"a": 1, "a": 2}')
            with self.assertRaises(ValueError):
                load_json(path)


class ParticipationAndRealizesTests(unittest.TestCase):
    def test_participation_bullets_stop_at_next_heading(self):
        body = ("# T\n\n## Graph participation\n\n- **Entry:** start\n- **Exit:** end\n\n"
                "## Next\n\n- **Ignored:** x\n")
        self.assertEqual(participation_bullets(body), [("Entry", "start"), ("Exit", "end")])
        self.assertEqual(parse_graph_participation(body), {"Entry": "start", "Exit": "end"})

    def test_participation_absent(self):
        self.assertIsNone(participation_bullets("# T\n\nno section here\n"))
        self.assertIsNone(parse_graph_participation("# T\n"))

    def test_realizes_block(self):
        body = "# R\n\n```realizes\nconcept: phase@acme-core\nname: local\n```\n"
        self.assertEqual(realizes_block(body), {"concept": "phase@acme-core", "name": "local"})
        self.assertIsNone(realizes_block("# R\n"))

    def test_two_realizes_blocks_are_rejected(self):
        body = "```realizes\na: 1\n```\n\n```realizes\nb: 2\n```\n"
        with self.assertRaises(YamlSubsetError):
            realizes_block(body)


class SchemaSubsetTests(unittest.TestCase):
    def assertValid(self, instance, schema):
        self.assertEqual(validate_json_schema(instance, schema), [])

    def assertInvalid(self, instance, schema):
        self.assertTrue(validate_json_schema(instance, schema), f"expected errors for {instance!r}")

    def test_type(self):
        self.assertValid("x", {"type": "string"})
        self.assertInvalid(1, {"type": "string"})
        self.assertValid(True, {"type": "boolean"})
        self.assertInvalid(True, {"type": "integer"})

    def test_properties_required_and_additional(self):
        schema = {"type": "object", "required": ["id"],
                  "properties": {"id": {"type": "string"}}, "additionalProperties": False}
        self.assertValid({"id": "a"}, schema)
        self.assertInvalid({}, schema)
        self.assertInvalid({"id": "a", "extra": 1}, schema)

    def test_enum_and_const(self):
        self.assertValid("plan", {"enum": ["plan", "build"]})
        self.assertInvalid("test", {"enum": ["plan", "build"]})
        self.assertValid(1.0, {"const": 1})
        self.assertInvalid("2", {"const": "1"})

    def test_items_and_min_items(self):
        schema = {"type": "array", "minItems": 2, "items": {"type": "integer"}}
        self.assertValid([1, 2], schema)
        self.assertInvalid([1], schema)
        self.assertInvalid([1, "two"], schema)

    def test_pattern(self):
        self.assertValid("alpha", {"type": "string", "pattern": "^a"})
        self.assertInvalid("beta", {"type": "string", "pattern": "^a"})

    def test_one_of_needs_exactly_one(self):
        schema = {"oneOf": [{"type": "string"}, {"type": "string", "pattern": "^x"}]}
        self.assertValid(1, {"oneOf": [{"type": "integer"}, {"type": "string"}]})
        self.assertInvalid("xy", schema)

    def test_local_ref(self):
        schema = {"$defs": {"id": {"type": "string"}},
                  "type": "object", "properties": {"x": {"$ref": "#/$defs/id"}}}
        self.assertValid({"x": "a"}, schema)
        self.assertInvalid({"x": 1}, schema)

    def test_unknown_keyword_is_an_error(self):
        with self.assertRaises(SchemaSubsetError):
            validate_json_schema({}, {"frobnicate": 1})

    def test_annotation_keywords_are_ignored(self):
        self.assertValid({}, {"title": "t", "description": "d", "$schema": "x", "type": "object"})


class ModelTests(unittest.TestCase):
    def test_marketplace_without_manifest_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="gc-model-") as tmp:
            with self.assertRaises(MarketplaceError):
                Marketplace.load(tmp)

    def test_concept_name_strips_marketplace_prefix(self):
        self.assertEqual(concept_name("acme-phase", "acme"), "phase")
        self.assertEqual(concept_name("standalone", "acme"), "standalone")

    def test_declared_references(self):
        graph = {"refines": "a@acme-core", "observes": ["b@acme-core", "all"],
                 "edges": [{"to": "c@acme-core"}]}
        self.assertEqual(sorted(declared_references(graph)), [
            ("edges", "c@acme-core"), ("observes", "b@acme-core"), ("refines", "a@acme-core"),
        ])

    def test_finding_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            Finding("F-files", "info", None, "x")
        self.assertTrue(Finding("F-files", "block", None, "x").blocking)
        self.assertFalse(Finding("PIN", "warn", None, "x").blocking)


class CompileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-compile-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def plugins(self):
        return [
            {"name": "acme-phase", "version": "2.0.0", "concept": True,
             "realizations": ["local", "remote"]},
            {"name": "acme-glossary", "version": "1.1.0", "capability": True},
        ]

    def test_same_contents_in_different_order_compile_to_identical_bytes(self):
        first = build_marketplace(self.tmp / "one", "acme-core", self.plugins())
        second = build_marketplace(self.tmp / "two", "acme-core", list(reversed(self.plugins())),
                                   order=["acme-glossary", "acme-phase"])
        bytes_one = render(compile(Marketplace.load(first))).encode("utf-8")
        bytes_two = render(compile(Marketplace.load(second))).encode("utf-8")
        self.assertEqual(bytes_one, bytes_two)

    def test_graph_shape(self):
        root = build_marketplace(self.tmp / "shape", "acme-core", self.plugins())
        graph = compile(Marketplace.load(root))
        self.assertEqual(graph["graphSpecVersion"], "1.0")
        self.assertEqual(graph["marketplace"], "acme-core")
        self.assertEqual([n["id"] for n in graph["nodes"]], ["phase@acme-core"])
        node = graph["nodes"][0]
        self.assertEqual(node["role"], "phase")
        self.assertEqual(node["interaction"], "pause")
        self.assertEqual(node["plugin"], "acme-phase")
        self.assertEqual(node["version"], "2.0.0")
        self.assertEqual(node["contract"], {"outputs": ["plan"]})
        # The "## Graph participation" bullets are prose; F-agree checks them against the frontmatter.
        self.assertNotIn("participation", node)
        self.assertEqual(sorted(node), sorted(["id", "plugin", "version", "role", "interaction",
                                               "contract", "realizations"]))
        self.assertEqual([r["name"] for r in node["realizations"]], ["local", "remote"])
        self.assertEqual(node["realizations"][0]["effects"], [])
        self.assertEqual([c["id"] for c in graph["capabilities"]], ["glossary@acme-core"])
        self.assertNotIn("role", graph["capabilities"][0])
        self.assertNotIn("interaction", graph["capabilities"][0])
        self.assertEqual(graph["upstreams"], [])

    def test_default_interaction_is_autonomous(self):
        root = self.tmp / "auto"
        build_marketplace(root, "acme-core", [{"name": "acme-phase", "concept": True}])
        skill = root / "plugins" / "acme-phase" / "skills" / "concept" / "SKILL.md"
        write(skill, CONCEPT_SKILL.replace("  interaction: pause\n", ""))
        graph = compile(Marketplace.load(root))
        self.assertEqual(graph["nodes"][0]["interaction"], "autonomous")

    def test_graph_hash_verifies_and_write_checks_it(self):
        root = build_marketplace(self.tmp / "hash", "acme-core", self.plugins())
        graph = compile(Marketplace.load(root))
        self.assertEqual(graph["graphHash"], graph_hash(graph))
        path = write_compiled(root, graph)
        written = load_json(path)
        self.assertEqual(written["graphHash"], graph_hash(written))
        tampered = copy.deepcopy(graph)
        tampered["nodes"] = []
        with self.assertRaises(CompileError) as ctx:
            write_compiled(root, tampered)
        self.assertEqual(ctx.exception.check, "X-hashes")

    def test_upstream_hash_is_the_upstream_compiled_hash(self):
        alpha = build_marketplace(self.tmp / "alpha", "alpha-core",
                                  [{"name": "alpha-phase", "concept": True}])
        beta = build_marketplace(self.tmp / "beta", "beta-core", [
            {"name": "beta-phase", "concept": True,
             "deps": [{"name": "alpha-phase", "marketplace": "alpha-core", "version": "1.0.0"}]},
        ])
        alpha_m = Marketplace.load(alpha)
        beta_graph = compile(Marketplace.load(beta), {"alpha-core": alpha_m})
        self.assertEqual(len(beta_graph["upstreams"]), 1)
        entry = beta_graph["upstreams"][0]
        self.assertEqual(entry["marketplace"], "alpha-core")
        self.assertEqual(entry["graphHash"], compile(alpha_m)["graphHash"])
        self.assertEqual(entry["plugins"], {"alpha-phase": "1.0.0"})

    def test_missing_upstream_is_refused(self):
        beta = build_marketplace(self.tmp / "beta2", "beta-core", [
            {"name": "beta-phase", "concept": True,
             "deps": [{"name": "alpha-phase", "marketplace": "alpha-core", "version": "1.0.0"}]},
        ])
        with self.assertRaises(CompileError) as ctx:
            compile(Marketplace.load(beta))
        self.assertEqual(ctx.exception.check, "X-resolve")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-command-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_directory_without_marketplace_exits_two(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = run_check(empty)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("SCOPE", result.stdout)

    def test_json_output_shape_for_exit_two(self):
        empty = self.tmp / "empty-json"
        empty.mkdir()
        result = run_check(empty, "--json")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["exit"], 2)
        self.assertEqual(payload["findings"][0]["check"], "SCOPE")

    def test_pin_mismatch_exits_two_and_names_both_commands(self):
        repo = make_git_repo(self.tmp / "guidance-pinned", tag="guidance-conventions--v0.0.1")
        build_marketplace(repo, "claude-plugin-guidance", [{"name": "guidance-conventions"}])
        result = run_check(repo, "--repo", str(repo))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("0.0.1", result.stdout)
        self.assertIn("claude plugin update", result.stdout)
        self.assertIn("guidance_check.py", result.stdout)

    def test_pin_match_exits_zero(self):
        version = guidance_check.guidance_plugin_version()
        repo = make_git_repo(self.tmp / "guidance-match",
                             tag=f"guidance-conventions--v{version}")
        build_marketplace(repo, "claude-plugin-guidance", [{"name": "guidance-conventions"}])
        result = run_check(repo, "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_pin_warns_and_exits_zero(self):
        repo = make_git_repo(self.tmp / "guidance-unpinned")
        build_marketplace(repo, "claude-plugin-guidance", [{"name": "guidance-conventions"}])
        result = run_check(repo, "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)
        self.assertIn("PIN", result.stdout)

    def test_no_pin_skips_the_pin_check(self):
        repo = make_git_repo(self.tmp / "guidance-skip", tag="guidance-conventions--v0.0.1")
        build_marketplace(repo, "claude-plugin-guidance", [{"name": "guidance-conventions"}])
        result = run_check(repo, "--repo", str(repo), "--no-pin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_upstream_exits_two(self):
        beta = build_marketplace(self.tmp / "beta-command", "beta-core", [
            {"name": "beta-phase", "concept": True,
             "deps": [{"name": "alpha-phase", "marketplace": "alpha-core", "version": "1.0.0"}]},
        ])
        result = run_check(beta, "--no-pin")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("X-resolve", result.stdout)

    def test_compile_writes_the_graph_and_exits_zero(self):
        root = build_marketplace(self.tmp / "compile-command", "acme-core", [
            {"name": "acme-phase", "concept": True, "realizations": ["local"]},
        ])
        result = run_check(root, "--compile", "--no-pin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = load_json(root / "concept-graph.json")
        self.assertEqual(written["graphHash"], graph_hash(written))
        self.assertEqual(written["nodes"][0]["id"], "phase@acme-core")

    def test_compile_with_upstream_directory(self):
        alpha = build_marketplace(self.tmp / "up" / "alpha-core", "alpha-core",
                                  [{"name": "alpha-phase", "concept": True}])
        beta = build_marketplace(self.tmp / "beta-up", "beta-core", [
            {"name": "beta-phase", "concept": True,
             "deps": [{"name": "alpha-phase", "marketplace": "alpha-core", "version": "1.0.0"}]},
        ])
        result = run_check(beta, "--compile", "--no-pin", "--upstreams", str(alpha.parent))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = load_json(beta / "concept-graph.json")
        self.assertEqual(written["upstreams"][0]["graphHash"],
                         compile(Marketplace.load(alpha))["graphHash"])


if __name__ == "__main__":
    unittest.main()
