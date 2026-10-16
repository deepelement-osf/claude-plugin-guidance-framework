"""Tests for the X checks, AD2 and AD3 in gc_checks_x. Standard library only.

Each test builds tiny synthetic marketplaces (acme-core, acme-web and, where a
test needs one, acme-ops) in a temporary directory and runs the checks on them.
The tag listing that X-newer reads is stubbed, so no test reads a real
repository.

Run from the repository root:

    python3 -m unittest tests.test_gc_checks_x -v
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gc_checks_x  # noqa: E402
from gc_compile import compile as compile_graph, graph_hash, write_compiled  # noqa: E402
from gc_model import COMPILED_FILE, Context, Marketplace  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path, value):
    write(path, json.dumps(value, indent=2) + "\n")


def graph_yaml(role=None, extra=""):
    """Front matter text for a graph declaration, ending in a newline."""
    lines = ["graph:", '  graphSpecVersion: "1.0"']
    if role:
        lines.append(f"  role: {role}")
    return "\n".join(lines) + "\n" + extra


EDGES = ("  edges:\n"
         "    - outcome: passed\n      to: deliver@acme-core\n"
         "    - outcome: failed\n      to: deliver@acme-core\n")
STATUS = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
ARTIFACT = {"type": "object", "properties": {"artifact": {"type": "string"}}, "required": ["artifact"]}
TIER2_BUILD = {"contractVersion": "1.2.0", "type": "object",
               "properties": {"status": {"type": "string"}}, "required": ["status"]}


def core_dep():
    return [{"name": "acme-build", "marketplace": "acme-core", "version": "^1.0.0"}]


def write_plugin(root, name, spec):
    pdir = root / "plugins" / name
    write_json(pdir / ".claude-plugin" / "plugin.json",
               {"name": name, "version": spec.get("version", "1.0.0")})
    if spec.get("concept"):
        concept = name[len("acme-"):]
        write(pdir / "skills" / "concept" / "SKILL.md",
              f"---\nname: {concept}\ndescription: test concept\n{spec.get('graph') or ''}---\n\n# Concept\n")
        contract_dir = pdir / "skills" / "realization-contract"
        if spec.get("contract") is not None:
            write_json(contract_dir / "graph-contract.json", spec["contract"])
        if spec.get("schema") is not None:
            write_json(contract_dir / "schema.json", spec["schema"])
    for rname, rspec in spec.get("realizations", {}).items():
        rdir = pdir / "skills" / f"realize-{rname}"
        front = ["---", f"name: realize-{rname}", "description: test realization"]
        if rspec.get("default"):
            front.append("default: true")
        if rspec.get("runs"):
            front += ["graph:", f"  runs: {rspec['runs']}"]
        body = "\n# Realization\n"
        if rspec.get("realizes"):
            body += "\n```realizes\n" + "".join(f"{k}: {v}\n" for k, v in rspec["realizes"].items()) + "```\n"
        write(rdir / "SKILL.md", "\n".join(front) + "\n---\n" + body)
        if rspec.get("schema") is not None:
            write_json(rdir / "schema.json", rspec["schema"])


def write_marketplace(root, name, plugins):
    entries = []
    for pname, spec in plugins.items():
        entry = {"name": pname, "source": f"./plugins/{pname}"}
        if spec.get("deps"):
            entry["dependencies"] = copy.deepcopy(spec["deps"])
        entries.append(entry)
        write_plugin(root, pname, spec)
    write_json(root / ".claude-plugin" / "marketplace.json", {"name": name, "plugins": entries})
    return Marketplace.load(root)


def core_plugins():
    return {
        "acme-build": {
            "concept": True,
            "graph": graph_yaml("phase", EDGES + "  uses: [secrets@acme-core]\n"),
            "contract": {"selection": "one", "outcomes": ["passed", "failed"],
                         "frame": STATUS, "result": STATUS},
            "schema": TIER2_BUILD,
        },
        "acme-deliver": {
            "concept": True,
            "graph": graph_yaml("phase"),
            "contract": {"selection": "one", "outcomes": ["done"], "input": ARTIFACT, "result": ARTIFACT},
        },
        "acme-secrets": {"concept": True},
    }


def refinement_plugin(refines_or_extra):
    return {
        "deps": core_dep(),
        "concept": True,
        "graph": graph_yaml("refinement", refines_or_extra),
        "contract": {"selection": "one", "outcomes": ["passed", "failed"], "result": STATUS},
    }


def web_plugins():
    return {
        "acme-nextjs-build": refinement_plugin("  refines: build@acme-core\n  uses: [secrets@acme-core]\n"),
        "acme-nextjs-lint": refinement_plugin("  refines: build@acme-core\n  after: [nextjs-build@acme-web]\n"),
        "acme-audit": {"deps": core_dep(), "concept": True,
                       "graph": graph_yaml("observer", "  observes: {role: refinement}\n")},
    }


def ops_marketplace(root):
    return write_marketplace(root, "acme-ops", {
        "acme-deploy": {"concept": True, "graph": graph_yaml("phase")},
    })


def compiled(marketplace, upstreams):
    write_compiled(marketplace.root, compile_graph(marketplace, upstreams))
    return Marketplace.load(marketplace.root)


def tamper(marketplace, change):
    """Change the stored compiled graph, recompute its graphHash and reload the marketplace."""
    path = marketplace.root / COMPILED_FILE
    graph = json.loads(path.read_text(encoding="utf-8"))
    change(graph)
    graph["graphHash"] = graph_hash(graph)
    write_compiled(marketplace.root, graph)
    return Marketplace.load(marketplace.root)


def blocking(findings, check):
    return [f for f in findings if f.check == check and f.blocking]


def warnings(findings, check):
    return [f for f in findings if f.check == check and not f.blocking]


class XCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # X-newer reads tags through this function. Stub it so no test touches git.
        patcher = mock.patch.object(gc_checks_x, "_list_tags", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def pair(self, core_specs=None, web_specs=None, extra=None, compile_web=True):
        core = write_marketplace(self.tmp / "acme-core", "acme-core", core_specs or core_plugins())
        web = write_marketplace(self.tmp / "acme-web", "acme-web", web_specs or web_plugins())
        upstreams = {"acme-core": core}
        upstreams.update(extra or {})
        if compile_web:
            web = compiled(web, upstreams)
        return web, upstreams

    def run_checks(self, web, upstreams, previous=None):
        ctx = Context(root=web.root, marketplace=web, upstreams=upstreams, previous_graph=previous)
        return gc_checks_x.run(ctx)

    def assert_blocks(self, findings, check, *fragments):
        hits = blocking(findings, check)
        self.assertTrue(hits, f"expected a blocking {check} finding; got {[f.to_dict() for f in findings]}")
        for fragment in fragments:
            self.assertTrue(any(fragment in f.message for f in hits),
                            f"no blocking {check} message contains {fragment!r}: {[f.message for f in hits]}")

    def assert_no_block(self, findings, check):
        hits = blocking(findings, check)
        self.assertEqual([], [f.message for f in hits], f"unexpected blocking {check} findings")

    def assert_warns(self, findings, check, *fragments):
        hits = warnings(findings, check)
        self.assertTrue(hits, f"expected a {check} warning; got {[f.to_dict() for f in findings]}")
        for fragment in fragments:
            self.assertTrue(any(fragment in f.message for f in hits),
                            f"no {check} warning contains {fragment!r}: {[f.message for f in hits]}")
        self.assertTrue(all(not f.blocking for f in hits), f"{check} must only warn here")


# ---------------------------------------------------------------------------
# The base fixture, and the helpers the checks rely on
# ---------------------------------------------------------------------------

class BaseFixtureTests(XCase):
    def test_base_fixture_has_no_blocking_findings(self):
        web, ups = self.pair()
        findings = self.run_checks(web, ups)
        self.assertEqual([], [f.to_dict() for f in findings if f.blocking])


class SatisfiesTests(unittest.TestCase):
    def test_caret_tilde_and_comparators(self):
        self.assertTrue(gc_checks_x.satisfies("1.2.0", "^1.0.0"))
        self.assertFalse(gc_checks_x.satisfies("2.0.0", "^1.0.0"))
        self.assertTrue(gc_checks_x.satisfies("1.2.9", "~1.2.0"))
        self.assertFalse(gc_checks_x.satisfies("1.3.0", "~1.2.0"))
        self.assertTrue(gc_checks_x.satisfies("1.5.0", ">=1.2.0 <2.0.0"))
        self.assertFalse(gc_checks_x.satisfies("2.0.0", ">=1.2.0 <2.0.0"))
        self.assertTrue(gc_checks_x.satisfies("0.2.9", "^0.2.3"))
        self.assertFalse(gc_checks_x.satisfies("0.3.0", "^0.2.3"))

    def test_alternatives_and_wildcards(self):
        self.assertTrue(gc_checks_x.satisfies("1.0.0", "1.x || 3.0.0"))
        self.assertTrue(gc_checks_x.satisfies("3.0.0", "1.x || 3.0.0"))
        self.assertFalse(gc_checks_x.satisfies("2.0.0", "1.x || 3.0.0"))

    def test_unparseable_range_is_none_and_unparseable_version_is_false(self):
        self.assertIsNone(gc_checks_x.satisfies("1.0.0", "garbage!"))
        self.assertFalse(gc_checks_x.satisfies("1.0.0-beta", "^1.0.0"))


class SchemaAcceptsTests(unittest.TestCase):
    def test_required_field_must_be_produced(self):
        self.assertEqual([], gc_checks_x.schema_accepts(STATUS, STATUS))
        self.assertTrue(gc_checks_x.schema_accepts(STATUS, {"type": "object", "properties": {}, "required": []}))

    def test_type_mismatch_is_an_issue_and_integer_fits_number(self):
        consumer = {"type": "object", "properties": {"n": {"type": "number"}}, "required": ["n"]}
        producer = {"type": "object", "properties": {"n": {"type": "string"}}, "required": ["n"]}
        self.assertTrue(gc_checks_x.schema_accepts(consumer, producer))
        producer["properties"]["n"]["type"] = "integer"
        self.assertEqual([], gc_checks_x.schema_accepts(consumer, producer))

    def test_additional_properties_false_rejects_extra_produced_field(self):
        consumer = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
        producer = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        self.assertTrue(gc_checks_x.schema_accepts(consumer, producer))

    def test_superset_keeps_tier2_fields(self):
        self.assertEqual([], gc_checks_x.superset_problems(TIER2_BUILD, STATUS))
        self.assertTrue(gc_checks_x.superset_problems(TIER2_BUILD, {"type": "object", "properties": {}}))


# ---------------------------------------------------------------------------
# X-versions and X-newer
# ---------------------------------------------------------------------------

class VersionTests(XCase):
    def test_versions_pass_when_recorded_version_is_in_range(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-versions")

    def test_versions_fail_when_recorded_version_is_outside_range(self):
        web, ups = self.pair()

        def bump(graph):
            plugins = graph["upstreams"][0]["plugins"]
            for name in plugins:
                plugins[name] = "2.0.0"

        web = tamper(web, bump)
        self.assert_blocks(self.run_checks(web, ups), "X-versions", "2.0.0", "^1.0.0")

    def test_newer_warns_for_newer_in_range_tag_and_never_blocks(self):
        web, ups = self.pair()
        tags = ["acme-build--v1.0.0", "acme-build--v1.2.0", "acme-build--v2.0.0"]
        with mock.patch.object(gc_checks_x, "_list_tags", return_value=tags):
            findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-newer", "1.2.0")
        self.assertFalse([f for f in findings if f.check == "X-newer" and "2.0.0" in f.message])
        self.assert_no_block(findings, "X-newer")

    def test_newer_says_so_when_tags_cannot_be_listed(self):
        web, ups = self.pair()
        with mock.patch.object(gc_checks_x, "_list_tags", return_value=None):
            findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-newer", "cannot be listed")
        self.assert_no_block(findings, "X-newer")


# ---------------------------------------------------------------------------
# X-resolve, X-placement, X-roles
# ---------------------------------------------------------------------------

class ResolveTests(XCase):
    def test_resolve_passes_for_base_references(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-resolve")

    def test_resolve_fails_for_a_missing_refinement_target(self):
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: format@acme-core\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-resolve", "format@acme-core")

    def test_resolve_fails_for_an_upstream_cycle(self):
        core_specs = core_plugins()
        core_specs["acme-build"]["deps"] = [{"name": "acme-nextjs-build", "marketplace": "acme-web",
                                             "version": "^1.0.0"}]
        core = write_marketplace(self.tmp / "acme-core", "acme-core", core_specs)
        web = write_marketplace(self.tmp / "acme-web", "acme-web", web_plugins())
        findings = self.run_checks(core, {"acme-web": web})
        self.assert_blocks(findings, "X-resolve", "form a cycle")


class PlacementTests(XCase):
    def test_placement_passes_for_a_uses_target_in_an_ancestor(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-placement")

    def test_placement_fails_for_a_refinement_of_a_sibling_marketplace(self):
        ops = ops_marketplace(self.tmp / "acme-ops")
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: deploy@acme-ops\n")
        web, ups = self.pair(web_specs=specs, extra={"acme-ops": ops})
        self.assert_blocks(self.run_checks(web, ups), "X-placement", "acme-ops")

    def test_placement_fails_for_a_workspace_reference(self):
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: build@acme-core\n  uses: [secrets@workspace]\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-placement", "secrets@workspace")


class RolesTests(XCase):
    def test_roles_pass_for_base_observer_and_refinement(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-roles")

    def test_roles_fail_for_an_observer_filter_on_a_capability_role(self):
        specs = web_plugins()
        specs["acme-audit"]["graph"] = graph_yaml("observer", "  observes: {role: capability}\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-roles", "capability")

    def test_roles_fail_for_a_refinement_of_an_observer(self):
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: audit@acme-web\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-roles", "refines targets audit@acme-web")

    def test_roles_fail_for_a_handoff_into_a_capability(self):
        specs = web_plugins()
        specs["acme-nextjs-lint"] = refinement_plugin("  refines: build@acme-core\n  handoff: secrets@acme-core\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-roles", "handoff targets secrets@acme-core")

    def test_roles_warn_for_a_wildcard_observer_whose_default_runs_a_session(self):
        specs = web_plugins()
        specs["acme-audit"] = {"deps": core_dep(), "concept": True,
                               "graph": graph_yaml("observer", "  observes: all\n"),
                               "realizations": {"agent": {"default": True, "runs": "agent"}}}
        web, ups = self.pair(web_specs=specs)
        findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-roles", "runs a session")
        self.assert_no_block(findings, "X-roles")


# ---------------------------------------------------------------------------
# X-contracts, X-order, X-depth
# ---------------------------------------------------------------------------

class ContractTests(XCase):
    def test_contracts_pass_for_base_refinement_result(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-contracts")

    def test_contracts_fail_when_refinement_result_is_not_accepted_by_parent_frame(self):
        specs = web_plugins()
        specs["acme-nextjs-build"]["contract"]["result"] = {
            "type": "object", "properties": {"other": {"type": "string"}}, "required": ["other"]}
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-contracts", "frame of build@acme-core")

    def test_contracts_fail_for_a_handoff_whose_output_misses_the_target_input(self):
        specs = web_plugins()
        specs["acme-intake"] = {
            "deps": core_dep(), "concept": True,
            "graph": graph_yaml("entry", "  handoff: deliver@acme-core\n"),
            "contract": {"selection": "one", "outcomes": ["done"], "result": STATUS},
        }
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-contracts", "input contract")

    def test_contracts_pass_for_a_handoff_whose_output_satisfies_the_target_input(self):
        specs = web_plugins()
        specs["acme-intake"] = {
            "deps": core_dep(), "concept": True,
            "graph": graph_yaml("entry", "  handoff: deliver@acme-core\n"),
            "contract": {"selection": "one", "outcomes": ["done"], "result": ARTIFACT},
        }
        web, ups = self.pair(web_specs=specs)
        self.assert_no_block(self.run_checks(web, ups), "X-contracts")

    def test_realization_contract_version_range_is_satisfied(self):
        specs = web_plugins()
        specs["acme-nextjs-build"]["realizations"] = {
            "agent": {"realizes": {"concept": "build@acme-core", "contractVersion": '"^1.0.0"'},
                      "schema": TIER2_BUILD}}
        web, ups = self.pair(web_specs=specs)
        self.assert_no_block(self.run_checks(web, ups), "X-contracts")

    def test_realization_contract_version_range_not_satisfied_blocks(self):
        specs = web_plugins()
        specs["acme-nextjs-build"]["realizations"] = {
            "agent": {"realizes": {"concept": "build@acme-core", "contractVersion": '"^2.0.0"'}}}
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-contracts", "not satisfied by contractVersion 1.2.0")

    def test_realization_schema_must_keep_tier2_fields(self):
        specs = web_plugins()
        specs["acme-nextjs-build"]["realizations"] = {
            "agent": {"realizes": {"concept": "build@acme-core", "contractVersion": '"^1.0.0"'},
                      "schema": {"type": "object", "properties": {"other": {"type": "string"}}}}}
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-contracts", "not a superset")


class OrderTests(XCase):
    def test_order_passes_for_a_linear_after_chain(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-order")

    def test_order_fails_for_an_after_cycle(self):
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin(
            "  refines: build@acme-core\n  after: [nextjs-lint@acme-web]\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-order", "cycle")


class DepthTests(XCase):
    def chain_specs(self, count):
        specs = web_plugins()
        for i in range(1, count + 1):
            ref = "build@acme-core" if i == 1 else f"r{i - 1}@acme-web"
            specs[f"acme-r{i}"] = refinement_plugin(f"  refines: {ref}\n")
        return specs

    def test_depth_passes_for_a_shallow_chain(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-depth")

    def test_depth_warns_for_a_chain_deeper_than_the_limit(self):
        web, ups = self.pair(web_specs=self.chain_specs(5))
        findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-depth", "r5@acme-web")
        self.assert_no_block(findings, "X-depth")

    def test_depth_blocks_a_refines_loop(self):
        specs = web_plugins()
        specs["acme-loop-a"] = refinement_plugin("  refines: loop-b@acme-web\n")
        specs["acme-loop-b"] = refinement_plugin("  refines: loop-a@acme-web\n")
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-depth", "loops")


# ---------------------------------------------------------------------------
# X-hashes, X-lifecycle, X-additive
# ---------------------------------------------------------------------------

class HashTests(XCase):
    def test_hashes_pass_when_recorded_hash_matches(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-hashes")

    def test_hashes_compare_the_digest_not_the_prefix(self):
        web, ups = self.pair()

        def bare(graph):
            entry = graph["upstreams"][0]
            entry["graphHash"] = entry["graphHash"].replace("sha256:", "", 1)

        web = tamper(web, bare)
        self.assert_no_block(self.run_checks(web, ups), "X-hashes")

    def test_hashes_fail_when_recorded_upstream_hash_is_wrong(self):
        web, ups = self.pair()

        def wrong(graph):
            graph["upstreams"][0]["graphHash"] = "sha256:" + "ab" * 32

        web = tamper(web, wrong)
        self.assert_blocks(self.run_checks(web, ups), "X-hashes", "differs from the resolved upstream")


class LifecycleTests(XCase):
    def test_lifecycle_passes_for_base_references(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-lifecycle")

    def test_lifecycle_warns_for_a_deprecated_upstream_concept(self):
        core_specs = core_plugins()
        core_specs["acme-build"]["graph"] = graph_yaml(
            "phase", EDGES + '  uses: [secrets@acme-core]\n  deprecated: "2026-06"\n  replaced_by: deliver@acme-core\n')
        web, ups = self.pair(core_specs=core_specs)
        findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-lifecycle", "deprecated")
        self.assert_no_block(findings, "X-lifecycle")

    def test_lifecycle_warns_for_an_alias_and_still_resolves(self):
        core_specs = core_plugins()
        core_specs["acme-build"]["graph"] = graph_yaml(
            "phase", EDGES + "  uses: [secrets@acme-core]\n  aliases: [build-old]\n")
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: build-old@acme-core\n")
        web, ups = self.pair(core_specs=core_specs, web_specs=specs)
        findings = self.run_checks(web, ups)
        self.assert_warns(findings, "X-lifecycle", "alias of build@acme-core")
        self.assert_no_block(findings, "X-resolve")

    def test_lifecycle_blocks_a_name_removed_upstream(self):
        specs = web_plugins()
        specs["acme-nextjs-build"] = refinement_plugin("  refines: gone@acme-core\n")
        web, ups = self.pair(web_specs=specs)
        previous = {"graphSpecVersion": "1.0", "nodes": [{"id": "old@acme-web", "refines": "gone@acme-core"}],
                    "capabilities": [], "upstreams": []}
        findings = self.run_checks(web, ups, previous=previous)
        self.assert_blocks(findings, "X-lifecycle", "removed upstream")
        self.assert_no_block(findings, "X-resolve")


class AdditiveTests(XCase):
    def test_additive_passes_for_the_base_fixture(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "X-additive")

    def test_additive_fails_for_a_phase_added_outside_an_entry_chain(self):
        specs = web_plugins()
        specs["acme-extra"] = {"deps": core_dep(), "concept": True, "graph": graph_yaml("phase")}
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "X-additive", "extra@acme-web")

    def test_additive_fails_when_a_stored_node_drops_an_upstream_edge(self):
        web, ups = self.pair()
        core_nodes = compile_graph(ups["acme-core"], {})["nodes"]
        build = copy.deepcopy(next(n for n in core_nodes if n["id"] == "build@acme-core"))
        build["edges"] = build["edges"][1:]
        web = tamper(web, lambda graph: graph["nodes"].append(build))
        self.assert_blocks(self.run_checks(web, ups), "X-additive", "edges of build@acme-core")


# ---------------------------------------------------------------------------
# AD2 and AD3
# ---------------------------------------------------------------------------

class Ad2Tests(XCase):
    def test_ad2_passes_when_no_name_repeats_an_upstream(self):
        web, ups = self.pair()
        self.assert_no_block(self.run_checks(web, ups), "AD2")

    def test_ad2_fails_when_a_plugin_repeats_an_upstream_plugin(self):
        specs = web_plugins()
        specs["acme-build"] = {"version": "1.0.0"}
        web, ups = self.pair(web_specs=specs)
        self.assert_blocks(self.run_checks(web, ups), "AD2", "acme-build")

    def test_ad3_is_not_emitted_here(self):
        # AD3 belongs to gc_checks_v; this module must not report it too.
        specs = web_plugins()
        specs["acme-nextjs-build"]["realizations"] = {
            "agent": {"default": True, "realizes": {"concept": "build@acme-core"}}}
        web, ups = self.pair(web_specs=specs)
        findings = self.run_checks(web, ups)
        self.assertEqual([], [f.to_dict() for f in findings if f.check == "AD3"])


if __name__ == "__main__":
    unittest.main()
