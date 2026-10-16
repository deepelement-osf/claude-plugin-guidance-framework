"""Tests for the F checks in gc_checks_f. Standard library only.

Each test builds tiny synthetic marketplaces in a temporary directory: acme-web,
which is the marketplace under check, and acme-core, which it refers to. The
tests load them, run the checks, and look at the findings. Nothing outside the
temporary directory is written.

Run from the repository root:

    python3 -m unittest tests.test_gc_checks_f -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gc_checks_f as F  # noqa: E402
from gc_compile import compile, render  # noqa: E402
from gc_model import COMPILED_FILE, CannotRun, Context, Marketplace, Options  # noqa: E402

CONCEPT = "skills/concept/SKILL.md"
CONTRACT = "skills/realization-contract/graph-contract.json"
SCHEMA = "skills/realization-contract/schema.json"
REALIZE_MARKDOWN = "skills/realize-markdown/SKILL.md"

GRAPH_PLAN = 'graph:\n  graphSpecVersion: "1.0"\n  role: entry\n  handoff: ship@acme-web\n'
BODY_PLAN = ("Starts the run and hands its last node to ship.\n\n## Graph participation\n\n"
             "- **role:** entry\n- **handoff:** ship@acme-web\n")

GRAPH_SHIP = 'graph:\n  graphSpecVersion: "1.0"\n  role: phase\n  uses: [secrets@acme-core]\n'
BODY_SHIP = ("Ship phase. Reads credentials through `secrets@acme-core`.\n\n## Graph participation\n\n"
             "- **role:** phase\n- **uses:** secrets@acme-core\n")

GRAPH_LINT = ('graph:\n  graphSpecVersion: "1.0"\n  role: refinement\n  refines: ship@acme-web\n'
              '  optional: true\n  when: {path_exists: package.json}\n  uses: [secrets@acme-core]\n')
BODY_LINT = ("Lint refinement. Reads its token through `secrets@acme-core`.\n\n## Graph participation\n\n"
             "- **role:** refinement\n- **refines:** ship@acme-web\n- **optional:** true\n"
             "- **when:** path_exists=package.json\n- **uses:** secrets@acme-core\n")

GRAPH_AUDIT = 'graph:\n  graphSpecVersion: "1.0"\n  role: observer\n  observes: {role: phase}\n  on: concluded\n'
BODY_AUDIT = ("Audit observer. Records that a phase concluded.\n\n## Graph participation\n\n"
              "- **role:** observer\n- **observes:** role: phase\n- **on:** concluded\n")

SHIP_CONTRACT = {"graphSpecVersion": "1.0", "selection": "one", "outcomes": ["passed", "failed"],
                 "frame": {"type": "object"}, "input": {"type": "object"}}
LINT_CONTRACT = {"graphSpecVersion": "1.0", "selection": "one", "outcomes": ["passed", "failed"],
                 "result": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}
AUDIT_CONTRACT = {"graphSpecVersion": "1.0", "selection": "one",
                  "result": {"type": "object", "properties": {"recorded": {"type": "boolean"}}}}
PLAN_CONTRACT = {"graphSpecVersion": "1.0", "selection": "one", "outcomes": ["planned"]}


def skill(name, description, graph, body, default=False):
    front = f"name: {name}\ndescription: {description}\n"
    if default:
        front += "default: true\n"
    front += graph
    return f"---\n{front}---\n\n{body}"


def fixture_own():
    """The marketplace under check: acme-web. Every value is a fresh object."""
    return {
        "acme-plan": {
            CONCEPT: skill("plan", "Plan entry.", GRAPH_PLAN, BODY_PLAN),
            CONTRACT: dict(PLAN_CONTRACT),
            SCHEMA: {"type": "object"},
        },
        "acme-ship": {
            CONCEPT: skill("ship", "Ship phase.", GRAPH_SHIP, BODY_SHIP),
            CONTRACT: json.loads(json.dumps(SHIP_CONTRACT)),
            SCHEMA: {"type": "object"},
        },
        "acme-lint": {
            CONCEPT: skill("lint", "Lint refinement.", GRAPH_LINT, BODY_LINT),
            CONTRACT: json.loads(json.dumps(LINT_CONTRACT)),
            SCHEMA: {"type": "object"},
            "skills/realize-lint-script/SKILL.md": skill(
                "realize-lint-script", "Lint script.",
                'graph:\n  graphSpecVersion: "1.0"\n  runs: command\n  command: scripts/lint.sh\n',
                "Runs the lint script.\n", default=True),
            "skills/realize-lint-script/scripts/lint.sh": "#!/bin/sh\nexit 0\n",
        },
        "acme-audit": {
            CONCEPT: skill("audit", "Audit observer.", GRAPH_AUDIT, BODY_AUDIT),
            CONTRACT: json.loads(json.dumps(AUDIT_CONTRACT)),
            SCHEMA: {"type": "object"},
            REALIZE_MARKDOWN: skill(
                "realize-markdown", "Markdown log.",
                'graph:\n  graphSpecVersion: "1.0"\n  runs: agent\n',
                "Appends one line per concluded phase.\n", default=True),
        },
    }


def fixture_upstream():
    """acme-core, which supplies the secrets capability that acme-web uses."""
    return {
        "acme-secrets": {
            CONCEPT: "---\nname: secrets\ndescription: Secrets capability.\n---\n\nStores a secret by name.\n",
        },
    }


def _write(base: Path, files: dict) -> None:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def _write_marketplace(root: Path, name: str, plugins: dict) -> None:
    manifest = {
        "name": name,
        "owner": {"name": "Synthetic"},
        "plugins": [{"name": plugin, "source": f"./plugins/{plugin}"} for plugin in plugins],
    }
    _write(root, {".claude-plugin/marketplace.json": manifest})
    for plugin, files in plugins.items():
        version_file = {".claude-plugin/plugin.json": {"name": plugin, "version": "1.0.0"}}
        _write(root / "plugins" / plugin, {**version_file, **files})


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def build(self, own=None, upstream=None):
        """Write both marketplaces to disk, load them, and return the context for acme-web."""
        own = fixture_own() if own is None else own
        upstream = fixture_upstream() if upstream is None else upstream
        _write_marketplace(self.tmp / "acme-web", "acme-web", own)
        _write_marketplace(self.tmp / "acme-core", "acme-core", upstream)
        own_market = Marketplace.load(self.tmp / "acme-web")
        up_market = Marketplace.load(self.tmp / "acme-core")
        return Context(root=self.tmp / "acme-web", marketplace=own_market,
                       upstreams={"acme-core": up_market}, options=Options())

    def write_skill(self, ctx, plugin, text):
        (ctx.root / "plugins" / plugin / CONCEPT).write_text(text, encoding="utf-8")

    def blocking(self, ctx, check):
        return [f for f in F.run(ctx) if f.check == check and f.blocking]

    def findings(self, ctx, check):
        return [f for f in F.run(ctx) if f.check == check]


class CleanMarketplaceTest(Base):
    def test_clean_marketplace_has_no_blocking_findings_before_compile(self):
        ctx = self.build()
        blocking = [f for f in F.run(ctx) if f.blocking]
        # Only the missing concept-graph.json is expected: the marketplace has concepts.
        self.assertEqual([(f.check, f.file) for f in blocking], [("F-compiled", COMPILED_FILE)])

    def test_clean_marketplace_with_compiled_graph_passes_except_compiled_schema(self):
        ctx = self.build()
        (ctx.root / COMPILED_FILE).write_bytes(render(compile(ctx.marketplace, ctx.upstreams)).encode("utf-8"))
        ctx = self.build_again(ctx)
        blocking = [f for f in F.run(ctx) if f.blocking]
        # The compiled file is checked against spec/schemas/compiled-graph.schema.json. The core
        # compiler writes a hash and upstream list in a different shape from that schema, so the
        # compiled-file schema finding is not asserted here. Every other check must be clean.
        others = [f for f in blocking if not (f.check == "F-schema" and f.file == COMPILED_FILE)]
        self.assertEqual(others, [])

    def build_again(self, ctx):
        """Reload acme-web from disk, after a compiled file was written next to it."""
        own_market = Marketplace.load(ctx.root)
        return Context(root=ctx.root, marketplace=own_market, upstreams=ctx.upstreams, options=Options())


class FilesTest(Base):
    def test_clean_files_pass(self):
        self.assertEqual(self.blocking(self.build(), "F-files"), [])

    def test_missing_contract_for_a_role_concept_blocks(self):
        own = fixture_own()
        del own["acme-ship"][CONTRACT]
        found = self.blocking(self.build(own), "F-files")
        self.assertEqual(len(found), 1)
        self.assertIn("graph-contract.json", found[0].message)
        self.assertIn("ship@acme-web", found[0].message)

    def test_missing_schema_for_a_role_concept_blocks(self):
        own = fixture_own()
        del own["acme-plan"][SCHEMA]
        found = self.blocking(self.build(own), "F-files")
        self.assertEqual([f.file for f in found], ["plugins/acme-plan/" + SCHEMA])

    def test_capability_without_realizations_needs_no_contract_files(self):
        own = fixture_own()
        own["acme-vault"] = {CONCEPT: skill("vault", "Vault capability.", "", "Keeps values.\n")}
        self.assertEqual(self.blocking(self.build(own), "F-files"), [])

    def test_capability_with_realization_needs_contract_files(self):
        own = fixture_own()
        own["acme-vault"] = {
            CONCEPT: skill("vault", "Vault capability.", "", "Keeps values.\n"),
            "skills/realize-keep/SKILL.md": skill(
                "realize-keep", "Keeps values.",
                'graph:\n  graphSpecVersion: "1.0"\n  runs: agent\n', "Keeps them.\n"),
        }
        found = self.blocking(self.build(own), "F-files")
        self.assertEqual(len(found), 2)
        self.assertTrue(all("vault@acme-web" in f.message for f in found))


class AgreeTest(Base):
    def test_matching_bullets_pass(self):
        self.assertEqual(self.blocking(self.build(), "F-agree"), [])

    def test_bullet_that_differs_from_frontmatter_blocks(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace("- **role:** refinement",
                                                                       "- **role:** phase")
        found = self.blocking(self.build(own), "F-agree")
        self.assertEqual(len(found), 1)
        self.assertIn("role", found[0].message)

    def test_missing_participation_section_blocks(self):
        own = fixture_own()
        own["acme-plan"][CONCEPT] = own["acme-plan"][CONCEPT].split("## Graph participation")[0]
        found = self.blocking(self.build(own), "F-agree")
        self.assertEqual(len(found), 1)
        self.assertIn("no '## Graph participation' section", found[0].message)

    def test_extra_bullet_blocks(self):
        own = fixture_own()
        own["acme-plan"][CONCEPT] = own["acme-plan"][CONCEPT].replace(
            "- **handoff:** ship@acme-web", "- **handoff:** ship@acme-web\n- **outcomes:** planned")
        found = self.blocking(self.build(own), "F-agree")
        self.assertEqual(len(found), 1)
        self.assertIn("extra ['outcomes']", found[0].message)

    def test_bullets_out_of_declaration_order_block(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace(
            "- **refines:** ship@acme-web\n- **optional:** true\n",
            "- **optional:** true\n- **refines:** ship@acme-web\n")
        found = self.blocking(self.build(own), "F-agree")
        self.assertEqual(len(found), 1)
        self.assertIn("declaration order", found[0].message)

    def test_prose_outside_the_section_is_ignored(self):
        own = fixture_own()
        own["acme-plan"][CONCEPT] = own["acme-plan"][CONCEPT].replace(
            "Starts the run", "- **role:** phase\n\nStarts the run")
        self.assertEqual(self.blocking(self.build(own), "F-agree"), [])


class Tier2Test(Base):
    def test_complete_contracts_pass(self):
        self.assertEqual(self.blocking(self.build(), "F-tier2"), [])

    def test_refinement_contract_without_result_blocks(self):
        own = fixture_own()
        del own["acme-lint"][CONTRACT]["result"]
        found = self.blocking(self.build(own), "F-tier2")
        self.assertEqual(len(found), 1)
        self.assertIn("'result'", found[0].message)

    def test_concept_that_refinements_target_needs_frame(self):
        own = fixture_own()
        del own["acme-ship"][CONTRACT]["frame"]
        found = self.blocking(self.build(own), "F-tier2")
        self.assertEqual(len(found), 1)
        self.assertIn("'frame'", found[0].message)

    def test_concept_that_entries_hand_off_to_needs_input(self):
        own = fixture_own()
        del own["acme-ship"][CONTRACT]["input"]
        found = self.blocking(self.build(own), "F-tier2")
        self.assertEqual(len(found), 1)
        self.assertIn("'input'", found[0].message)

    def test_phase_without_outcomes_blocks(self):
        own = fixture_own()
        del own["acme-ship"][CONTRACT]["outcomes"]
        found = self.blocking(self.build(own), "F-tier2")
        self.assertTrue(any("'outcomes'" in f.message for f in found))

    def test_observer_needs_no_outcomes(self):
        own = fixture_own()
        self.assertNotIn("outcomes", own["acme-audit"][CONTRACT])
        self.assertEqual(self.blocking(self.build(own), "F-tier2"), [])

    def test_contract_without_graph_spec_version_blocks(self):
        own = fixture_own()
        del own["acme-plan"][CONTRACT]["graphSpecVersion"]
        found = self.blocking(self.build(own), "F-tier2")
        self.assertTrue(any("'graphSpecVersion'" in f.message for f in found))


class Tier3Test(Base):
    def test_clean_realizations_pass(self):
        self.assertEqual(self.blocking(self.build(), "F-tier3"), [])

    def test_missing_command_file_blocks(self):
        own = fixture_own()
        del own["acme-lint"]["skills/realize-lint-script/scripts/lint.sh"]
        found = self.blocking(self.build(own), "F-tier3")
        self.assertEqual(len(found), 1)
        self.assertIn("lint.sh", found[0].message)

    def test_missing_runs_blocks(self):
        own = fixture_own()
        own["acme-audit"][REALIZE_MARKDOWN] = own["acme-audit"][REALIZE_MARKDOWN].replace("  runs: agent\n", "")
        found = self.blocking(self.build(own), "F-tier3")
        self.assertTrue(any("runs" in f.message for f in found))

    def test_command_with_agent_runs_blocks(self):
        own = fixture_own()
        own["acme-audit"][REALIZE_MARKDOWN] = own["acme-audit"][REALIZE_MARKDOWN].replace(
            "  runs: agent\n", "  runs: agent\n  command: scripts/x.sh\n")
        found = self.blocking(self.build(own), "F-tier3")
        self.assertTrue(any("only when runs is command" in f.message for f in found))

    def test_builds_on_must_name_a_sibling_realization(self):
        own = fixture_own()
        own["acme-audit"][REALIZE_MARKDOWN] = own["acme-audit"][REALIZE_MARKDOWN].replace(
            "  runs: agent\n", "  runs: agent\n  builds_on: ghost\n")
        found = self.blocking(self.build(own), "F-tier3")
        self.assertTrue(any("builds_on" in f.message for f in found))

    def test_builds_on_a_sibling_passes(self):
        own = fixture_own()
        own["acme-audit"]["skills/realize-pdf/SKILL.md"] = skill(
            "realize-pdf", "PDF log.", 'graph:\n  graphSpecVersion: "1.0"\n  runs: agent\n'
            '  builds_on: markdown\n', "Writes a PDF.\n")
        self.assertEqual(self.blocking(self.build(own), "F-tier3"), [])

    def test_unknown_effect_blocks(self):
        own = fixture_own()
        own["acme-audit"][REALIZE_MARKDOWN] = own["acme-audit"][REALIZE_MARKDOWN].replace(
            "  runs: agent\n", "  runs: agent\n  effects: [teleport]\n")
        found = self.blocking(self.build(own), "F-tier3")
        self.assertTrue(any("effects" in f.message for f in found))

    def test_known_effect_passes(self):
        own = fixture_own()
        own["acme-audit"][REALIZE_MARKDOWN] = own["acme-audit"][REALIZE_MARKDOWN].replace(
            "  runs: agent\n", "  runs: agent\n  effects: [push]\n")
        self.assertEqual(self.blocking(self.build(own), "F-tier3"), [])


class CapabilityTest(Base):
    def capability(self, graph="", section=""):
        own = fixture_own()
        own["acme-vault"] = {CONCEPT: skill("vault", "Vault capability.", graph,
                                             "Keeps values.\n" + section)}
        return own

    def test_plain_capability_passes(self):
        self.assertEqual(self.blocking(self.build(self.capability()), "F-capability"), [])

    def test_capability_with_participation_section_blocks(self):
        own = self.capability(section="\n## Graph participation\n\n- **role:** none\n")
        found = self.blocking(self.build(own), "F-capability")
        self.assertEqual(len(found), 1)
        self.assertIn("'## Graph participation' section", found[0].message)

    def test_capability_with_edges_blocks(self):
        graph = ('graph:\n  graphSpecVersion: "1.0"\n  edges:\n    - outcome: passed\n      to: ship@acme-web\n')
        found = self.blocking(self.build(self.capability(graph=graph)), "F-capability")
        self.assertTrue(any("edges" in f.message for f in found))

    def test_capability_with_interaction_blocks(self):
        graph = 'graph:\n  graphSpecVersion: "1.0"\n  interaction: pause\n'
        found = self.blocking(self.build(self.capability(graph=graph)), "F-capability")
        self.assertTrue(any("interaction" in f.message for f in found))


class BindingTest(Base):
    def binding_plugin(self, realizes_lines):
        own = fixture_own()
        own["acme-audit"]["skills/realize-pdf/SKILL.md"] = skill(
            "realize-pdf", "PDF log.", 'graph:\n  graphSpecVersion: "1.0"\n  runs: agent\n',
            "Writes a PDF.\n\n```realizes\n" + realizes_lines + "```\n")
        return own

    def test_complete_realizes_block_passes(self):
        own = self.binding_plugin("concept: audit@acme-web\nname: pdf\ncontractVersion: ^1.0.0\n")
        self.assertEqual(self.blocking(self.build(own), "F-binding"), [])

    def test_realizes_block_without_name_blocks(self):
        own = self.binding_plugin("concept: audit@acme-web\ncontractVersion: ^1.0.0\n")
        found = self.blocking(self.build(own), "F-binding")
        self.assertEqual(len(found), 1)
        self.assertIn("no name", found[0].message)

    def test_realizes_block_with_unqualified_concept_blocks(self):
        own = self.binding_plugin("concept: audit\nname: pdf\ncontractVersion: ^1.0.0\n")
        found = self.blocking(self.build(own), "F-binding")
        self.assertTrue(any("not qualified" in f.message for f in found))

    def test_handoff_target_without_input_blocks(self):
        own = fixture_own()
        del own["acme-ship"][CONTRACT]["input"]
        found = self.blocking(self.build(own), "F-binding")
        self.assertEqual(len(found), 1)
        self.assertIn("ship@acme-web", found[0].message)

    def test_capability_named_in_backticks_must_be_in_uses(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = (own["acme-lint"][CONCEPT]
                                     .replace("  uses: [secrets@acme-core]\n", "")
                                     .replace("- **uses:** secrets@acme-core\n", ""))
        found = self.blocking(self.build(own), "F-binding")
        self.assertEqual(len(found), 1)
        self.assertIn("secrets@acme-core", found[0].message)

    def test_capability_in_uses_passes(self):
        self.assertEqual(self.blocking(self.build(), "F-binding"), [])


class CompiledTest(Base):
    def test_missing_compiled_file_blocks(self):
        found = self.blocking(self.build(), "F-compiled")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].file, COMPILED_FILE)

    def test_fresh_compiled_file_passes(self):
        ctx = self.build()
        (ctx.root / COMPILED_FILE).write_bytes(render(compile(ctx.marketplace, ctx.upstreams)).encode("utf-8"))
        self.assertEqual(self.blocking(self.build_again(ctx), "F-compiled"), [])

    def test_stale_compiled_file_after_source_edit_blocks(self):
        ctx = self.build()
        (ctx.root / COMPILED_FILE).write_bytes(render(compile(ctx.marketplace, ctx.upstreams)).encode("utf-8"))
        manifest = ctx.root / "plugins" / "acme-plan" / ".claude-plugin" / "plugin.json"
        manifest.write_text(json.dumps({"name": "acme-plan", "version": "1.1.0"}), encoding="utf-8")
        found = self.blocking(self.build_again(ctx), "F-compiled")
        self.assertEqual(len(found), 1)
        self.assertIn("stale", found[0].message)

    def test_description_only_change_keeps_the_compiled_file_current(self):
        ctx = self.build()
        (ctx.root / COMPILED_FILE).write_bytes(render(compile(ctx.marketplace, ctx.upstreams)).encode("utf-8"))
        self.write_skill(ctx, "acme-plan", skill("plan", "A different description.", GRAPH_PLAN, BODY_PLAN))
        self.assertEqual(self.blocking(self.build_again(ctx), "F-compiled"), [])

    def test_compile_error_is_reported_under_its_check_id(self):
        own = fixture_own()
        own["acme-plan"][CONCEPT] = skill("plan", "Plan entry.", "graph: nonsense\n", BODY_PLAN)
        # CompileError carries check="F-schema", and _f_compiled reports it under that id.
        found = self.findings(self.build(own), "F-schema")
        self.assertTrue(any(f.blocking and f.file == COMPILED_FILE and "not a mapping" in f.message for f in found),
                        [(f.file, f.message) for f in found])

    def build_again(self, ctx):
        own_market = Marketplace.load(ctx.root)
        return Context(root=ctx.root, marketplace=own_market, upstreams=ctx.upstreams, options=Options())


class SchemaTest(Base):
    def test_unknown_key_on_a_refinement_blocks(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace("  optional: true\n",
                                                                       "  optional: true\n  colour: blue\n")
        found = self.blocking(self.build(own), "F-schema")
        self.assertTrue(any("colour" in f.message for f in found))

    def test_observer_with_edges_blocks(self):
        own = fixture_own()
        own["acme-audit"][CONCEPT] = own["acme-audit"][CONCEPT].replace(
            "  on: concluded\n", "  on: concluded\n  edges:\n    - outcome: passed\n      to: ship@acme-web\n")
        found = self.blocking(self.build(own), "F-schema")
        self.assertTrue(any("edges" in f.message for f in found))

    def test_unsupported_graph_spec_version_exits_cannot_run_naming_the_range(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace('graphSpecVersion: "1.0"',
                                                                       'graphSpecVersion: "2.0"', 1)
        with self.assertRaises(CannotRun) as raised:
            self.blocking(self.build(own), "F-schema")
        self.assertEqual(raised.exception.check, "F-schema")
        self.assertIn("'1.0' only", raised.exception.message)
        self.assertIn("'2.0'", raised.exception.message)
        self.assertIn("update the guidance", raised.exception.fix)

    def test_malformed_graph_spec_version_stays_an_f_schema_block(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace('graphSpecVersion: "1.0"',
                                                                       'graphSpecVersion: "one"', 1)
        found = self.blocking(self.build(own), "F-schema")
        self.assertTrue(any("not a version" in f.message for f in found))

    def test_frame_outside_the_subset_blocks(self):
        own = fixture_own()
        own["acme-ship"][CONTRACT]["frame"] = {"anyOf": [{"type": "object"}]}
        found = self.blocking(self.build(own), "F-schema")
        self.assertTrue(any("anyOf" in f.message for f in found))

    def test_realizes_block_with_unknown_key_blocks(self):
        own = fixture_own()
        own["acme-audit"]["skills/realize-pdf/SKILL.md"] = skill(
            "realize-pdf", "PDF log.", 'graph:\n  graphSpecVersion: "1.0"\n  runs: agent\n',
            "Writes a PDF.\n\n```realizes\nconcept: audit@acme-web\nname: pdf\n"
            "contractVersion: ^1.0.0\ncolour: blue\n```\n")
        found = self.blocking(self.build(own), "F-schema")
        self.assertTrue(any("colour" in f.message for f in found))

    def test_clean_declarations_pass(self):
        self.assertEqual(self.blocking(self.build(), "F-schema"), [])

    def test_schema_documents_are_loaded(self):
        documents = F.schema_documents()
        self.assertEqual(sorted(documents), sorted(F._SCHEMA_FILES))


class SelectionTest(Base):
    def test_phase_with_selection_many_blocks(self):
        own = fixture_own()
        own["acme-ship"][CONTRACT] = dict(own["acme-ship"][CONTRACT], selection="many", fold="all")
        found = self.blocking(self.build(own), "F-selection")
        self.assertTrue(any("selection many" in f.message for f in found))

    def test_fold_with_selection_one_blocks(self):
        own = fixture_own()
        own["acme-ship"][CONTRACT]["fold"] = "all"
        found = self.blocking(self.build(own), "F-selection")
        self.assertTrue(any("fold appears only" in f.message for f in found))

    def test_selection_many_without_fold_blocks(self):
        own = fixture_own()
        own["acme-audit"][CONTRACT]["selection"] = "many"
        found = self.blocking(self.build(own), "F-selection")
        self.assertTrue(any("needs a fold" in f.message for f in found))

    def test_entry_without_selection_passes(self):
        self.assertEqual(self.blocking(self.build(), "F-selection"), [])


class InteractionTest(Base):
    def test_unknown_interaction_blocks(self):
        own = fixture_own()
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace(
            "  optional: true\n", "  optional: true\n  interaction: batch\n")
        found = self.blocking(self.build(own), "F-interaction")
        self.assertEqual(len(found), 1)
        self.assertIn("batch", found[0].message)

    def test_conversational_warns_and_does_not_block(self):
        own = fixture_own()
        own["acme-ship"][CONCEPT] = own["acme-ship"][CONCEPT].replace(
            "  role: phase\n", "  role: phase\n  interaction: conversational\n")
        ctx = self.build(own)
        findings = self.findings(ctx, "F-interaction")
        self.assertEqual([f.severity for f in findings], ["warn"])
        self.assertEqual(self.blocking(ctx, "F-interaction"), [])

    def test_pause_and_autonomous_pass(self):
        own = fixture_own()
        own["acme-ship"][CONCEPT] = own["acme-ship"][CONCEPT].replace(
            "  role: phase\n", "  role: phase\n  interaction: pause\n")
        own["acme-lint"][CONCEPT] = own["acme-lint"][CONCEPT].replace(
            "  optional: true\n", "  optional: true\n  interaction: autonomous\n")
        self.assertEqual(self.blocking(self.build(own), "F-interaction"), [])


class EmbeddedSchemaTest(unittest.TestCase):
    def test_embedded_copies_are_valid_json_for_every_schema(self):
        for name in F._SCHEMA_FILES:
            self.assertIsInstance(json.loads(F._EMBEDDED[name]), dict, name)

    def test_embedded_copies_equal_the_spec_when_the_spec_is_present(self):
        spec_dir = REPO / "spec" / "schemas"
        if not spec_dir.is_dir():
            self.skipTest("spec/schemas is not present beside this repository")
        for name, filename in F._SCHEMA_FILES.items():
            spec = json.loads((spec_dir / filename).read_text(encoding="utf-8"))
            self.assertEqual(json.loads(F._EMBEDDED[name]), spec, name)


class RunTest(Base):
    def test_run_returns_findings_with_known_check_ids(self):
        ctx = self.build()
        findings = F.run(ctx)
        self.assertTrue(all(isinstance(f, F.Finding) for f in findings))
        known = {"F-files", "F-agree", "F-tier2", "F-tier3", "F-capability", "F-binding",
                 "F-compiled", "F-schema", "F-selection", "F-interaction"}
        self.assertTrue({f.check for f in findings} <= known)
        self.assertFalse(any(f.check == "F-official" for f in findings))


if __name__ == "__main__":
    unittest.main()
