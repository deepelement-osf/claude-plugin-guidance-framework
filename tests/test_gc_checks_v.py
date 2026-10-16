"""Tests for the V, A8 and AD3 checks in gc_checks_v. Standard library only.

Each test builds tiny synthetic marketplaces (acme-core, with plugins named
acme-<concept>) in a temporary directory and runs the checks on them. Git
history is created only inside those temporary directories.

Run from the repository root:

    python3 -m unittest tests.test_gc_checks_v -v
"""

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

import gc_checks_v  # noqa: E402
from gc_compile import compile, write_compiled  # noqa: E402
from gc_model import Context, Marketplace, Options  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def phase_graph(edges=True, aliases=None, role="phase", extra=""):
    """YAML front matter text for a graph declaration, ending in a newline."""
    lines = ["graph:", '  graphSpecVersion: "1.0"', f"  role: {role}"]
    if aliases:
        lines.append(f"  aliases: [{', '.join(aliases)}]")
    if edges:
        lines += ["  edges:", "    - outcome: passed", "      to: deliver@acme-core"]
    text = "\n".join(lines) + "\n"
    return text + extra


def build(root, plugins, market_extra=None):
    """Write a marketplace named acme-core. plugins maps a plugin name to a spec dict.

    Spec keys: version (default 1.0.0), graph (YAML text or None for a capability),
    contract (dict, written as graph-contract.json), realizations (dir name -> text),
    manifest_deps and entry_deps (dependency lists), extra_manifest (dict).
    """
    root = Path(root)
    entries = []
    for name, spec in plugins.items():
        entry = {"name": name, "source": f"./plugins/{name}"}
        if spec.get("entry_deps") is not None:
            entry["dependencies"] = spec["entry_deps"]
        entries.append(entry)
        pdir = root / "plugins" / name
        manifest = {"name": name, "version": spec.get("version", "1.0.0")}
        if spec.get("manifest_deps") is not None:
            manifest["dependencies"] = spec["manifest_deps"]
        manifest.update(spec.get("extra_manifest", {}))
        write_json(pdir / ".claude-plugin" / "plugin.json", manifest)
        if spec.get("graph") is not None:
            concept = name[len("acme-"):]
            write(pdir / "skills" / "concept" / "SKILL.md",
                  f"---\nname: {concept}\ndescription: test concept\n{spec['graph']}---\n\n# Concept\n")
        if spec.get("contract") is not None:
            write_json(pdir / "skills" / "realization-contract" / "graph-contract.json", spec["contract"])
        for dirname, text in spec.get("realizations", {}).items():
            write(pdir / "skills" / dirname / "SKILL.md", text)
    market = {"name": "acme-core", "plugins": entries}
    market.update(market_extra or {})
    write_json(root / ".claude-plugin" / "marketplace.json", market)
    return root


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path, value):
    write(path, json.dumps(value, indent=2) + "\n")


def run_v(root, previous=None):
    marketplace = Marketplace.load(root)
    ctx = Context(root=marketplace.root, marketplace=marketplace, upstreams={},
                  previous_graph=previous, options=Options(), guidance_version="test")
    return gc_checks_v.run(ctx)


def compiled(root):
    return compile(Marketplace.load(root), {})


def of(findings, check):
    return [f for f in findings if f.check == check]


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgSign=false", *args],
        cwd=str(cwd), env=env, check=True, capture_output=True, text=True)


def git_release(root, plugins):
    """Init a repository at root, commit everything, and tag each plugin at its version."""
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "release")
    for name, spec in plugins.items():
        git(root, "tag", f"{name}--v{spec.get('version', '1.0.0')}")


BUILD_SPEC = {"graph": phase_graph()}
DELIVER_SPEC = {"graph": phase_graph(edges=False)}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def make(self, name, plugins, market_extra=None):
        return build(self.base / name, plugins, market_extra)


# ---------------------------------------------------------------------------
# V-major, previous graph given with --previous
# ---------------------------------------------------------------------------

class VMajorPreviousTests(Base):
    def previous(self, plugins, market_extra=None):
        self._count = getattr(self, "_count", 0) + 1
        return compiled(self.make(f"previous-{self._count}", plugins, market_extra))

    def test_pass_without_previous_and_without_history(self):
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        self.assertEqual(of(run_v(root), "V-major"), [])

    def test_pass_minor_addition(self):
        prev = self.previous({"acme-build": BUILD_SPEC})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def test_fail_removed_concept_without_bump(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        root = self.make("now", {"acme-build": BUILD_SPEC})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertIn("removes deliver@acme-core", found[0].message)

    def test_pass_removed_concept_with_major_bump(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        # The plugin stays and drops its concept, so its MAJOR version is bumped.
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-deliver": {"version": "2.0.0"}})
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def test_fail_removed_plugin_cannot_bump(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        root = self.make("now", {"acme-build": dict(BUILD_SPEC, version="2.0.0")})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("plugin acme-deliver is no longer in the marketplace", found[0].message)

    def test_pass_rename_with_alias(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        root = self.make("now", {
            "acme-build": BUILD_SPEC,
            "acme-ship": {"graph": phase_graph(edges=False, aliases=["deliver"])},
        })
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def test_fail_rename_without_alias(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        root = self.make("now", {
            "acme-build": BUILD_SPEC,
            "acme-ship": {"graph": phase_graph(edges=False)},
        })
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("removes deliver@acme-core", found[0].message)

    def test_fail_dropped_alias(self):
        prev = self.previous({"acme-build": {"graph": phase_graph(aliases=["old-build"])}})
        root = self.make("now", {"acme-build": BUILD_SPEC})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("drops alias old-build", found[0].message)

    def test_fail_removed_edge(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-deliver": DELIVER_SPEC})
        root = self.make("now", {"acme-build": {"graph": phase_graph(edges=False)},
                                 "acme-deliver": DELIVER_SPEC})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("removes edge build@acme-core passed -> deliver@acme-core", found[0].message)

    def test_fail_selection_many_to_one(self):
        review = {"graph": phase_graph(edges=False, role="refinement", extra="  refines: build@acme-core\n")}
        many = dict(review, contract={"selection": "many", "fold": "all", "outcomes": ["passed"]})
        one = dict(review, contract={"outcomes": ["passed"]})
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-review": many})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-review": one})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("from selection many to one", found[0].message)

    def test_pass_selection_one_to_many(self):
        review = {"graph": phase_graph(edges=False, role="refinement", extra="  refines: build@acme-core\n")}
        many = dict(review, contract={"selection": "many", "fold": "all", "outcomes": ["passed"]})
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-review": review})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-review": many})
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def input_spec(self, schema):
        return dict(BUILD_SPEC, contract={"outcomes": ["passed"], "input": schema})

    def test_fail_input_narrowed_by_required_key(self):
        open_schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        required = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        prev = self.previous({"acme-build": self.input_spec(open_schema)})
        root = self.make("now", {"acme-build": self.input_spec(required)})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("narrows the input contract", found[0].message)
        self.assertIn("requires a", found[0].message)

    def test_pass_input_gains_optional_property(self):
        before = {"type": "object", "properties": {"a": {"type": "string"}}}
        after = {"type": "object", "properties": {"a": {"type": "string"},
                                                  "b": {"type": "integer"}}}
        prev = self.previous({"acme-build": self.input_spec(before)})
        root = self.make("now", {"acme-build": self.input_spec(after)})
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def test_fail_input_closed_to_extra_properties(self):
        before = {"type": "object", "properties": {"a": {"type": "string"}}}
        after = dict(before, additionalProperties=False)
        prev = self.previous({"acme-build": self.input_spec(before)})
        root = self.make("now", {"acme-build": self.input_spec(after)})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("stops allowing extra properties", found[0].message)

    def test_fail_removed_input_contract(self):
        schema = {"type": "object"}
        prev = self.previous({"acme-build": self.input_spec(schema)})
        root = self.make("now", {"acme-build": BUILD_SPEC})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("removes the input contract", found[0].message)

    def test_fail_optional_refinement_made_required(self):
        optional = {"graph": phase_graph(edges=False, role="refinement",
                                         extra="  refines: build@acme-core\n  optional: true\n")}
        required = {"graph": phase_graph(edges=False, role="refinement", extra="  refines: build@acme-core\n")}
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-review": optional})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-review": required})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("makes the optional refinement", found[0].message)

    def test_fail_when_key_added_to_observer(self):
        before = {"graph": phase_graph(edges=False, role="observer",
                                       extra="  observes: build@acme-core\n  when: {path_exists: a}\n")}
        after = {"graph": phase_graph(edges=False, role="observer",
                                      extra="  observes: build@acme-core\n  when: {path_exists: a, setting: x}\n")}
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-watch": before})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-watch": after})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("adds or changes when on watch@acme-core", found[0].message)

    def test_pass_when_key_removed(self):
        before = {"graph": phase_graph(edges=False, role="observer",
                                       extra="  observes: build@acme-core\n  when: {path_exists: a, setting: x}\n")}
        after = {"graph": phase_graph(edges=False, role="observer",
                                      extra="  observes: build@acme-core\n  when: {path_exists: a}\n")}
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-watch": before})
        root = self.make("now", {"acme-build": BUILD_SPEC, "acme-watch": after})
        self.assertEqual(of(run_v(root, prev), "V-major"), [])

    def test_fail_plugin_removed(self):
        prev = self.previous({"acme-build": BUILD_SPEC, "acme-audit": {"graph": phase_graph(edges=False)}})
        root = self.make("now", {"acme-build": BUILD_SPEC})
        found = of(run_v(root, prev), "V-major")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertIn("plugin acme-audit is no longer in the marketplace", found[0].message)


# ---------------------------------------------------------------------------
# V-major, previous graph read from the release tag by git show
# ---------------------------------------------------------------------------

class VMajorGitTests(Base):
    def setUp(self):
        super().setUp()
        self.plugins = {"acme-build": dict(BUILD_SPEC), "acme-deliver": dict(DELIVER_SPEC)}
        self.root = self.make("repo", self.plugins)
        write_compiled(self.root, compiled(self.root))
        git_release(self.root, self.plugins)

    def test_fail_removed_concept_without_bump(self):
        os.remove(self.root / "plugins" / "acme-deliver" / "skills" / "concept" / "SKILL.md")
        found = of(run_v(self.root), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("plugin acme-deliver changes its graph in a MAJOR way", found[0].message)
        self.assertIn("removes deliver@acme-core", found[0].message)

    def test_pass_removed_concept_with_major_bump(self):
        os.remove(self.root / "plugins" / "acme-deliver" / "skills" / "concept" / "SKILL.md")
        write_json(self.root / "plugins" / "acme-deliver" / ".claude-plugin" / "plugin.json",
                   {"name": "acme-deliver", "version": "2.0.0"})
        self.assertEqual(of(run_v(self.root), "V-major"), [])

    def test_fail_major_change_under_minor_bump(self):
        write(self.root / "plugins" / "acme-build" / "skills" / "concept" / "SKILL.md",
              "---\nname: build\ndescription: test concept\n" + phase_graph(edges=False) +
              "---\n\n# Concept\n")
        write_json(self.root / "plugins" / "acme-build" / ".claude-plugin" / "plugin.json",
                   {"name": "acme-build", "version": "1.1.0"})
        found = of(run_v(self.root), "V-major")
        self.assertEqual(len(found), 1)
        self.assertIn("removes edge build@acme-core passed", found[0].message)


# ---------------------------------------------------------------------------
# V-bump
# ---------------------------------------------------------------------------

class VBumpTests(Base):
    def setUp(self):
        super().setUp()
        self.plugins = {"acme-build": dict(BUILD_SPEC), "acme-deliver": dict(DELIVER_SPEC)}
        self.root = self.make("repo", self.plugins)
        git_release(self.root, self.plugins)

    def test_warn_when_changed_since_release_without_bump(self):
        write(self.root / "plugins" / "acme-build" / "skills" / "concept" / "SKILL.md",
              "---\nname: build\ndescription: changed\n" + phase_graph() + "---\n\n# Changed\n")
        found = of(run_v(self.root), "V-bump")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].blocking)
        self.assertEqual(found[0].file, "plugins/acme-build/.claude-plugin/plugin.json")

    def test_pass_after_version_bump(self):
        write(self.root / "plugins" / "acme-build" / "skills" / "concept" / "SKILL.md",
              "---\nname: build\ndescription: changed\n" + phase_graph() + "---\n\n# Changed\n")
        write_json(self.root / "plugins" / "acme-build" / ".claude-plugin" / "plugin.json",
                   {"name": "acme-build", "version": "1.0.1"})
        self.assertEqual(of(run_v(self.root), "V-bump"), [])

    def test_pass_when_unchanged(self):
        self.assertEqual(of(run_v(self.root), "V-bump"), [])

    def test_skipped_without_git_history(self):
        root = self.make("plain", self.plugins)
        write(root / "plugins" / "acme-build" / "skills" / "concept" / "SKILL.md",
              "---\nname: build\ndescription: changed\n" + phase_graph() + "---\n\n# Changed\n")
        self.assertEqual(of(run_v(root), "V-bump"), [])


# ---------------------------------------------------------------------------
# A8 (reversed)
# ---------------------------------------------------------------------------

class A8Tests(Base):
    def test_guidance_marketplace_name_is_read_from_this_repository(self):
        self.assertEqual(gc_checks_v.guidance_marketplace_name(), "claude-plugin-guidance")

    def test_block_plugin_json_dependency_on_guidance_conventions(self):
        root = self.make("a8-manifest", {"acme-build": dict(BUILD_SPEC, manifest_deps=["guidance-conventions"])})
        found = of(run_v(root), "A8")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertEqual(found[0].file, "plugins/acme-build/.claude-plugin/plugin.json")

    def test_block_marketplace_entry_dependency_on_guidance_plugin(self):
        entry = [{"name": "guidance-activation-check", "marketplace": "claude-plugin-guidance"}]
        root = self.make("a8-entry", {"acme-build": dict(BUILD_SPEC, entry_deps=entry)})
        found = of(run_v(root), "A8")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].file, ".claude-plugin/marketplace.json")

    def test_block_allow_list_naming_guidance_marketplace(self):
        root = self.make("a8-allow", {"acme-build": BUILD_SPEC},
                         market_extra={"allowCrossMarketplaceDependenciesOn": ["claude-plugin-guidance"]})
        found = of(run_v(root), "A8")
        self.assertEqual(len(found), 1)
        self.assertIn("allowCrossMarketplaceDependenciesOn lists the guidance marketplace", found[0].message)

    def test_pass_dependency_on_other_marketplace_plugin(self):
        root = self.make("a8-ok", {"acme-build": dict(BUILD_SPEC, manifest_deps=["acme-other"],
                                                      entry_deps=["acme-other"])})
        self.assertEqual(of(run_v(root), "A8"), [])


# ---------------------------------------------------------------------------
# AD3 (amended)
# ---------------------------------------------------------------------------

def realization(default, concept="build@other-up"):
    front = "---\nname: alt\ndescription: test realization\n"
    if default:
        front += "default: true\n"
    body = f"---\n\n# Alt\n\n```realizes\nconcept: {concept}\nname: alt\ncontractVersion: \"^1.0.0\"\n```\n"
    return front + body


class AD3Tests(Base):
    def test_block_inherited_realization_marked_default(self):
        root = self.make("ad3-default", {"acme-alt": {"realizations": {"realize-build-alt": realization(True)}}})
        found = of(run_v(root), "AD3")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertEqual(found[0].file, "plugins/acme-alt/skills/realize-build-alt/SKILL.md")

    def test_pass_inherited_realization_not_default(self):
        root = self.make("ad3-plain", {"acme-alt": {"realizations": {"realize-build-alt": realization(False)}}})
        self.assertEqual(of(run_v(root), "AD3"), [])

    def test_pass_own_realization_marked_default(self):
        root = self.make("ad3-own", {"acme-build": {
            "graph": phase_graph(edges=False),
            "realizations": {"realize-build-next": realization(True, concept="build@acme-core")},
        }})
        self.assertEqual(of(run_v(root), "AD3"), [])


# ---------------------------------------------------------------------------
# The schema subset used by the contract rule
# ---------------------------------------------------------------------------

class SchemaNarrowingTests(unittest.TestCase):
    def narrow(self, p, c):
        return gc_checks_v._narrowing(p, c, p, c)

    def test_equal_schemas_do_not_narrow(self):
        schema = {"type": "string", "minLength": 1, "enum": ["a", "b"]}
        self.assertEqual(self.narrow(schema, dict(schema)), [])

    def test_type_narrowed_from_number_to_integer(self):
        self.assertTrue(self.narrow({"type": "number"}, {"type": "integer"}))

    def test_type_widened_from_integer_to_number_is_not_narrowing(self):
        self.assertEqual(self.narrow({"type": "integer"}, {"type": "number"}), [])

    def test_enum_value_removed(self):
        self.assertTrue(self.narrow({"enum": ["a", "b"]}, {"enum": ["a"]}))

    def test_enum_value_added_is_not_narrowing(self):
        self.assertEqual(self.narrow({"enum": ["a", "b"]}, {"enum": ["a", "b", "c"]}), [])

    def test_number_equality_follows_json_rules(self):
        self.assertEqual(self.narrow({"const": 1}, {"const": 1.0}), [])
        self.assertTrue(self.narrow({"const": True}, {"const": 1}))

    def test_max_items_lowered(self):
        self.assertTrue(self.narrow({"type": "array", "maxItems": 5}, {"type": "array", "maxItems": 3}))

    def test_pattern_changed(self):
        self.assertTrue(self.narrow({"type": "string"}, {"type": "string", "pattern": "^a"}))

    def test_refs_resolve_inside_the_schema(self):
        p = {"$ref": "#/$defs/s", "$defs": {"s": {"type": "string"}}}
        c = {"$ref": "#/$defs/s", "$defs": {"s": {"type": "string", "minLength": 1}}}
        self.assertTrue(self.narrow(p, c))

    def test_recursive_property_narrowing(self):
        p = {"type": "object", "properties": {"n": {"type": "number"}}}
        c = {"type": "object", "properties": {"n": {"type": "integer"}}}
        reasons = self.narrow(p, c)
        self.assertEqual(len(reasons), 1)
        self.assertIn("n", reasons[0])


# ---------------------------------------------------------------------------
# Exported copy: the pre-commit hook runs the checks on an export of the index,
# with --repo pointing at the real repository. V-bump and V-major must still run.
# ---------------------------------------------------------------------------

class ExportedCopyTests(Base):
    def setUp(self):
        super().setUp()
        self.plugins = {"acme-build": dict(BUILD_SPEC), "acme-deliver": dict(DELIVER_SPEC)}
        self.repo = self.make("repo", self.plugins)
        write_compiled(self.repo, compiled(self.repo))
        git_release(self.repo, self.plugins)

    def export(self, name):
        """Stage the working tree, then export the index the way the hook does."""
        git(self.repo, "add", "-A")
        dest = self.base / name
        git(self.repo, "checkout-index", "-a", "--prefix=" + str(dest) + os.sep)
        return dest

    def run_on_export(self, export):
        marketplace = Marketplace.load(export)
        ctx = Context(root=export, marketplace=marketplace, upstreams={}, previous_graph=None,
                      options=Options(repo=str(self.repo)), guidance_version="test")
        return gc_checks_v.run(ctx)

    def test_export_without_change_has_no_v_findings(self):
        findings = self.run_on_export(self.export("clean"))
        self.assertEqual(of(findings, "V-bump"), [])
        self.assertEqual(of(findings, "V-major"), [])

    def test_v_bump_runs_on_export(self):
        write(self.repo / "plugins" / "acme-build" / "skills" / "concept" / "SKILL.md",
              "---\nname: build\ndescription: changed\n" + phase_graph() + "---\n\n# Changed\n")
        found = of(self.run_on_export(self.export("bump")), "V-bump")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].file, "plugins/acme-build/.claude-plugin/plugin.json")

    def test_v_major_runs_on_export(self):
        os.remove(self.repo / "plugins" / "acme-deliver" / "skills" / "concept" / "SKILL.md")
        found = of(self.run_on_export(self.export("major")), "V-major")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertIn("removes deliver@acme-core", found[0].message)


# ---------------------------------------------------------------------------
# A8 (invocation): the activation call, first and written as "if installed"
# ---------------------------------------------------------------------------

CALL = "guidance-activation-check:check-realization-config"


def skill_text(body):
    return ("---\nname: realize-markdown\ndescription: test realization\n"
            "graph:\n  graphSpecVersion: \"1.0\"\n  runs: agent\n---\n\n" + body)


class A8InvocationTests(Base):
    def make_with(self, body):
        return self.make("invocation", {"acme-build": dict(BUILD_SPEC, realizations={
            "realize-markdown": skill_text(body)})})

    def test_block_when_call_is_missing(self):
        found = of(run_v(self.make_with("# Markdown\n\nWrites the file.\n")), "A8")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].blocking)
        self.assertEqual(found[0].file, "plugins/acme-build/skills/realize-markdown/SKILL.md")

    def test_pass_when_call_is_first_and_if_installed(self):
        body = (f"# Markdown\n\nCall `{CALL}`, if installed, before any other step.\n\n"
                "Writes the file.\n")
        self.assertEqual(of(run_v(self.make_with(body)), "A8"), [])

    def test_warn_when_call_is_not_first(self):
        body = f"# Markdown\n\nWrites the file.\n\nCall `{CALL}`, if installed.\n"
        found = of(run_v(self.make_with(body)), "A8")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].blocking)
        self.assertIn("not the first instruction", found[0].message)

    def test_warn_when_call_is_not_written_as_if_installed(self):
        body = f"# Markdown\n\nCall `{CALL}` when it is installed.\n\nWrites the file.\n"
        found = of(run_v(self.make_with(body)), "A8")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].blocking)
        self.assertIn("if installed", found[0].message)

    def test_first_instruction_skips_headings_and_blank_lines(self):
        self.assertEqual(gc_checks_v._first_instruction("\n# Title\n\n  Do it.\n"), "Do it.")
        self.assertIsNone(gc_checks_v._first_instruction("# Only a heading\n"))


if __name__ == "__main__":
    unittest.main()
