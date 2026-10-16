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
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gc_compile  # noqa: E402
import gc_model  # noqa: E402
import guidance_check  # noqa: E402
from gc_compile import CompileError, compile, graph_hash, render, write_compiled  # noqa: E402
from gc_model import (  # noqa: E402
    CannotRun,
    Finding,
    Marketplace,
    MarketplaceError,
    concept_name,
    declared_references,
    dependency_closure,
)
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
GUIDANCE_NAME = "claude-plugin-guidance"
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


def build_marketplace(root: Path, name: str, plugins, order=None, metadata=None) -> Path:
    """Write a marketplace. plugins: dicts with name, version, concept (bool),
    realizations (list of str), capability (bool), deps (list of dicts).
    order, when given, lists plugin names in the order the manifest uses.
    metadata, when given, is written as the manifest's metadata object."""
    by_name = {p["name"]: p for p in plugins}
    names = order or [p["name"] for p in plugins]
    entries = []
    declared = (metadata or {}).get("pluginPrefix")
    prefix = declared if isinstance(declared, str) and declared else name.split("-", 1)[0]
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
    manifest = {"name": name, "owner": {"name": "Test"}, "plugins": entries}
    if metadata is not None:
        manifest["metadata"] = metadata
    write_json(root / ".claude-plugin" / "marketplace.json", manifest)
    return root


def write_settings(repo: Path, ref=None, marketplace=GUIDANCE_NAME) -> None:
    """Write the committed settings that pin guidance. ref=None omits the ref."""
    source = {"source": "github", "repo": "acme/claude-plugin-guidance"}
    if ref is not None:
        source["ref"] = ref
    write_json(repo / ".claude" / "settings.json",
               {"extraKnownMarketplaces": {marketplace: {"source": source}}})


def run_check(directory, *args):
    home = tempfile.mkdtemp(prefix="gc-home-")
    env = _clean_env(HOME=home, CLAUDE_PLUGIN_DATA=home)
    return subprocess.run(
        [sys.executable, "-B", str(CHECK_SCRIPT), str(directory), "--no-official", *args],
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

    def test_concept_name_strips_a_multi_word_prefix(self):
        self.assertEqual(concept_name("acme-web-nextjs-build", "acme-web"), "nextjs-build")
        self.assertEqual(concept_name("acme-web-nextjs-build", "acme"), "web-nextjs-build")
        self.assertEqual(concept_name("acme-phase", "acme-web"), "acme-phase")

    def test_declared_plugin_prefix_names_the_concepts(self):
        with tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
            root = build_marketplace(Path(tmp) / "core", "acme-core", [
                {"name": "acme-core-build", "concept": True},
                {"name": "acme-core-deliver", "concept": True},
            ], metadata={"pluginPrefix": "acme-core"})
            marketplace = Marketplace.load(root)
        self.assertEqual(sorted(marketplace.concepts), ["build", "deliver"])
        self.assertEqual(marketplace.concepts["build"].id, "build@acme-core")
        self.assertEqual(marketplace.prefix, "acme-core")
        self.assertEqual(marketplace.findings, [])

    def test_default_prefix_is_the_first_segment_when_undeclared(self):
        with tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
            root = build_marketplace(Path(tmp) / "web", "acme-web", [
                {"name": "acme-nextjs-build", "concept": True},
            ])
            marketplace = Marketplace.load(root)
        self.assertEqual(marketplace.prefix, "acme")
        self.assertEqual(marketplace.concepts["nextjs-build"].id, "nextjs-build@acme-web")
        self.assertEqual(marketplace.findings, [])

    def test_plugin_without_the_declared_prefix_keeps_its_full_name_and_no_loader_finding(self):
        # M2 is reported by gc_checks_m, not by the loader; the loader only names the concept.
        with tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
            root = build_marketplace(Path(tmp) / "core", "acme-core", [
                {"name": "acme-phase", "concept": True},
            ], metadata={"pluginPrefix": "acme-core"})
            marketplace = Marketplace.load(root)
        self.assertEqual(marketplace.findings, [])
        self.assertEqual(marketplace.concepts["acme-phase"].id, "acme-phase@acme-core")

    def test_invalid_declared_prefix_falls_back_to_the_first_segment_for_every_concept_name(self):
        # F-schema blocks the value; the graph and every concept name still use the default prefix.
        with tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
            root = build_marketplace(Path(tmp) / "web", "acme-web", [
                {"name": "acme-nextjs-build", "concept": True},
            ], metadata={"pluginPrefix": "-acme"})
            marketplace = Marketplace.load(root)
        self.assertEqual(marketplace.prefix, "acme")
        self.assertEqual([(f.check, f.severity) for f in marketplace.findings], [("F-schema", "block")])
        self.assertEqual(sorted(marketplace.concepts), ["nextjs-build"])
        self.assertEqual(marketplace.concepts["nextjs-build"].id, "nextjs-build@acme-web")

    def test_string_dependency_is_parsed_into_name_and_marketplace(self):
        with tempfile.TemporaryDirectory(prefix="gc-deps-") as tmp:
            root = build_marketplace(Path(tmp) / "web", "acme-web", [
                {"name": "acme-nextjs-build", "concept": True,
                 "deps": ["acme-build@acme-core", "acme-lint"]},
            ])
            marketplace = Marketplace.load(root)
        deps = marketplace.plugins["acme-nextjs-build"].dependencies
        self.assertEqual(deps, [
            {"name": "acme-build", "marketplace": "acme-core", "version": None},
            {"name": "acme-lint", "marketplace": "acme-web", "version": None},
        ])
        self.assertEqual(marketplace.direct_upstreams(), ["acme-core"])

    def test_string_dependency_takes_part_in_the_upstream_closure(self):
        with tempfile.TemporaryDirectory(prefix="gc-deps-") as tmp:
            core = build_marketplace(Path(tmp) / "core", "acme-core", [
                {"name": "acme-build", "concept": True},
            ])
            web = build_marketplace(Path(tmp) / "web", "acme-web", [
                {"name": "acme-nextjs-build", "concept": True, "deps": ["acme-build@acme-core"]},
            ])
            upstreams = {"acme-core": Marketplace.load(core)}
            marketplace = Marketplace.load(web)
        self.assertEqual(dependency_closure(marketplace, upstreams), {"acme-core"})

    def test_missing_plugin_directory_is_not_a_loader_finding(self):
        # M1 reports the missing directory. The loader loads the plugin with no files and lists it.
        with tempfile.TemporaryDirectory(prefix="gc-missing-") as tmp:
            root = build_marketplace(Path(tmp) / "web", "acme-web", [
                {"name": "acme-nextjs-build", "concept": True},
            ])
            manifest = load_json(root / ".claude-plugin" / "marketplace.json")
            manifest["plugins"].append({"name": "acme-gone", "source": "./plugins/acme-gone"})
            write_json(root / ".claude-plugin" / "marketplace.json", manifest)
            marketplace = Marketplace.load(root)
        self.assertEqual(marketplace.findings, [])
        self.assertIsNone(marketplace.plugins["acme-gone"].dir)
        self.assertEqual(marketplace.missing_sources, [("acme-gone", "./plugins/acme-gone")])
        self.assertEqual(sorted(marketplace.concepts), ["nextjs-build"])

    def test_valid_plugin_prefixes_are_accepted(self):
        for prefix in ("acme", "acme-web", "a1-b2", "x"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
                root = build_marketplace(Path(tmp) / "m", "acme-core", [
                    {"name": f"{prefix}-build", "concept": True},
                ], metadata={"pluginPrefix": prefix})
                blocking = [f for f in Marketplace.load(root).findings if f.blocking]
                self.assertEqual(blocking, [])

    def test_invalid_plugin_prefix_is_an_f_schema_block(self):
        for value in ("-acme", "acme-", "Acme", "acme--web", "", "acme web", 3, ["acme"]):
            with self.subTest(value=value), tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
                root = build_marketplace(Path(tmp) / "m", "acme-core", [
                    {"name": "acme-core-build", "concept": True},
                ], metadata={"pluginPrefix": value})
                findings = Marketplace.load(root).findings
                self.assertEqual([(f.check, f.severity) for f in findings], [("F-schema", "block")])

    def test_metadata_that_is_not_an_object_is_an_f_schema_block(self):
        with tempfile.TemporaryDirectory(prefix="gc-prefix-") as tmp:
            root = build_marketplace(Path(tmp) / "m", "acme-core", [
                {"name": "acme-core-build", "concept": True},
            ])
            manifest = load_json(root / ".claude-plugin" / "marketplace.json")
            manifest["metadata"] = "acme-core"
            write_json(root / ".claude-plugin" / "marketplace.json", manifest)
            findings = Marketplace.load(root).findings
        self.assertEqual([(f.check, f.severity) for f in findings], [("F-schema", "block")])

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

    def test_guidance_dependency_is_not_an_upstream_for_compile(self):
        root = build_marketplace(self.tmp / "guidance-dep", "acme-web", [
            {"name": "acme-audit", "concept": True, "deps": [
                {"name": "guidance-activation-check", "marketplace": GUIDANCE_NAME, "version": "^2.0.0"}]},
        ])
        marketplace = Marketplace.load(root)
        self.assertEqual(marketplace.direct_upstreams(), [])
        self.assertEqual(compile(marketplace)["upstreams"], [])


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

    def pinned_repo(self, name, ref=None, marketplace=GUIDANCE_NAME):
        """A marketplace repository, named name, whose settings pin ref (or pin nothing when ref is None)."""
        repo = self.tmp / name
        build_marketplace(repo, GUIDANCE_NAME, [{"name": "guidance-conventions"}],
                          metadata={"pluginPrefix": "guidance"})
        write(repo / "LICENSE", "Synthetic license text for a unit test.\n")
        write(repo / "README.md", "# guidance\n\nSynthetic marketplace for a unit test.\n\n"
                                  "## License\n\nIt is licensed under the terms in the LICENSE file.\n")
        if ref is not None or marketplace != GUIDANCE_NAME:
            write_settings(repo, ref, marketplace=marketplace)
        return repo

    def test_pin_mismatch_exits_two_and_names_both_commands(self):
        repo = self.pinned_repo("guidance-pinned", "guidance-conventions--v0.0.1")
        result = run_check(repo)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("0.0.1", result.stdout)
        self.assertIn(f"claude plugin marketplace update {GUIDANCE_NAME}", result.stdout)
        self.assertIn(f"claude plugin update guidance-conventions@{GUIDANCE_NAME}", result.stdout)

    def test_pin_match_exits_zero(self):
        version = guidance_check.guidance_plugin_version()
        repo = self.pinned_repo("guidance-match", f"guidance-conventions--v{version}")
        result = run_check(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("PIN", result.stdout)

    def test_missing_pin_warns_and_exits_zero(self):
        repo = self.pinned_repo("guidance-unpinned")
        result = run_check(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)
        self.assertIn("PIN", result.stdout)
        self.assertIn("results can differ between authors", result.stdout)

    def test_unreadable_settings_exits_two(self):
        repo = self.pinned_repo("guidance-bad-settings")
        write(repo / ".claude" / "settings.json", "{not json")
        result = run_check(repo)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("PIN", result.stdout)

    def test_pin_defaults_to_the_checked_directory_and_repo_overrides_it(self):
        version = guidance_check.guidance_plugin_version()
        checked = self.pinned_repo("guidance-checked", "guidance-conventions--v0.0.1")
        pinned = self.pinned_repo("guidance-elsewhere", f"guidance-conventions--v{version}")
        self.assertEqual(run_check(checked).returncode, 2)
        result = run_check(checked, "--repo", str(pinned))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_pin_skips_the_pin_check(self):
        repo = self.pinned_repo("guidance-skip", "guidance-conventions--v0.0.1")
        result = run_check(repo, "--no-pin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guidance_dependency_is_reported_by_a8_only(self):
        root = build_marketplace(self.tmp / "acme-web-guidance-dep", "acme-web", [
            {"name": "acme-audit", "concept": True, "deps": [
                {"name": "guidance-activation-check", "marketplace": GUIDANCE_NAME, "version": "^2.0.0"}]},
        ])
        result = run_check(root, "--no-pin")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("A8", result.stdout)
        self.assertNotIn("X-resolve", result.stdout)
        compiled = run_check(root, "--compile", "--no-pin")
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        self.assertEqual(load_json(root / "concept-graph.json")["upstreams"], [])

    def test_invalid_plugin_prefix_blocks_before_compile(self):
        root = build_marketplace(self.tmp / "bad-prefix-command", "acme-core",
                                 [{"name": "acme-core-build", "concept": True}],
                                 metadata={"pluginPrefix": "-acme"})
        result = run_check(root, "--compile", "--no-pin")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("F-schema", result.stdout)
        self.assertFalse((root / "concept-graph.json").exists())

    def test_missing_plugin_directory_blocks_compile_with_m1(self):
        # The loader no longer reports the missing directory, so compile must refuse on its own.
        root = build_marketplace(self.tmp / "missing-dir-command", "acme-core",
                                 [{"name": "acme-core-build", "concept": True}])
        manifest = load_json(root / ".claude-plugin" / "marketplace.json")
        manifest["plugins"].append({"name": "acme-core-gone", "source": "./plugins/acme-core-gone"})
        write_json(root / ".claude-plugin" / "marketplace.json", manifest)
        result = run_check(root, "--compile", "--no-pin")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("M1", result.stdout)
        self.assertNotIn("F-files", result.stdout)
        self.assertFalse((root / "concept-graph.json").exists())

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


class OfficialTests(unittest.TestCase):
    """The official validation runs claude plugin validate --strict, bounded in time, with no stdin."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-official-")
        self.tmp = Path(self._tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.root = self.tmp / "marketplace"
        self.root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def fake_claude(self, body: str) -> None:
        script = self.bin / "claude"
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)

    def run_official(self):
        findings: list = []
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            guidance_check.official_findings(self.root, gc_model.Options(), findings)
        return findings

    def test_validate_is_run_with_strict_and_the_root_as_separate_arguments(self):
        record = self.tmp / "argv.txt"
        self.fake_claude(f'printf "%s\\n" "$@" > "{record}"\nexit 0\n')
        self.assertEqual(self.run_official(), [])
        self.assertEqual(record.read_text(encoding="utf-8").splitlines(),
                         ["plugin", "validate", "--strict", str(self.root)])

    def test_validator_failure_is_a_block_that_quotes_its_last_line(self):
        self.fake_claude('echo "first line" >&2\necho "schema is wrong" >&2\nexit 1\n')
        findings = self.run_official()
        self.assertEqual([(f.check, f.severity) for f in findings], [("F-official", "block")])
        self.assertIn("--strict", findings[0].message)
        self.assertIn("schema is wrong", findings[0].message)

    def test_validator_that_does_not_finish_is_a_could_not_run_after_the_bound(self):
        self.fake_claude("exec /bin/sleep 30\n")
        with mock.patch.object(guidance_check, "OFFICIAL_TIMEOUT_SECONDS", 1):
            with self.assertRaises(CannotRun) as raised:
                self.run_official()
        self.assertEqual(raised.exception.check, "F-official")
        self.assertIn("1 seconds", raised.exception.message)

    def test_missing_claude_is_a_could_not_run(self):
        with self.assertRaises(CannotRun) as raised:
            self.run_official()
        self.assertEqual(raised.exception.check, "F-official")

    def test_no_official_skips_the_validator(self):
        findings: list = []
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            guidance_check.official_findings(self.root, gc_model.Options(no_official=True), findings)
        self.assertEqual(findings, [])


class PinTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gc-pin-")
        self.repo = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_pin_returns_the_version_in_the_guidance_ref(self):
        write_settings(self.repo, "guidance-conventions--v1.2.3")
        self.assertEqual(guidance_check.read_pin(self.repo), "1.2.3")

    def test_read_pin_is_none_without_a_guidance_conventions_tag(self):
        self.assertIsNone(guidance_check.read_pin(self.repo))
        for ref in (None, "v1.2.3", "guidance-conventions--v", "other--v1.0.0"):
            with self.subTest(ref=ref):
                write_settings(self.repo, ref)
                self.assertIsNone(guidance_check.read_pin(self.repo))
        write_settings(self.repo, "guidance-conventions--v1.0.0", marketplace="another-marketplace")
        self.assertIsNone(guidance_check.read_pin(self.repo))

    def test_malformed_settings_is_cannot_run(self):
        write(self.repo / ".claude" / "settings.json", "{not json")
        with self.assertRaises(guidance_check.CannotRun) as ctx:
            guidance_check.read_pin(self.repo)
        self.assertEqual(ctx.exception.check, "PIN")

    def test_check_pin_matching_version_adds_no_finding(self):
        write_settings(self.repo, "guidance-conventions--v2.0.0")
        findings = []
        guidance_check.check_pin(self.repo, "2.0.0", findings)
        self.assertEqual(findings, [])

    def test_check_pin_without_a_pin_warns_and_does_not_block(self):
        findings = []
        guidance_check.check_pin(self.repo, "2.0.0", findings)
        self.assertEqual([(f.check, f.severity) for f in findings], [("PIN", "warn")])
        self.assertFalse(findings[0].blocking)
        self.assertIn("results can differ between authors", findings[0].message)

    def test_check_pin_mismatch_is_cannot_run_naming_the_pin_and_both_commands(self):
        write_settings(self.repo, "guidance-conventions--v1.0.0")
        with self.assertRaises(guidance_check.CannotRun) as ctx:
            guidance_check.check_pin(self.repo, "2.0.0", [])
        self.assertEqual(ctx.exception.check, "PIN")
        self.assertIn("1.0.0", ctx.exception.message)
        self.assertIn(f"claude plugin marketplace update {GUIDANCE_NAME}", ctx.exception.fix)
        self.assertIn(f"claude plugin update guidance-conventions@{GUIDANCE_NAME}", ctx.exception.fix)

    def test_check_pin_without_a_repository_does_nothing(self):
        findings = []
        guidance_check.check_pin(None, "2.0.0", findings)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
