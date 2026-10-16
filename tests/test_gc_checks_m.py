"""Tests for the mechanical parts of sets M and U and of AD1 and AD2 in gc_checks_m. Standard library only.

Each test writes tiny synthetic marketplaces into a temporary directory: acme-web, the
marketplace under check, and acme-core, the upstream it may refer to. The tests load
them, run the checks and look at the findings. Nothing outside the temporary directory
is written.

Run from the repository root:

    python3 -m unittest tests.test_gc_checks_m -v
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

import gc_checks_m as M  # noqa: E402
from gc_model import Context, Marketplace  # noqa: E402

NONE = object()
README = "# acme-web\n\nLicensed under the MIT license in the LICENSE file.\n"
CONCEPT = "skills/concept/SKILL.md"


def section(*rows, header=None):
    """A Required marketplaces section in the template's form, with the given table rows."""
    head = header or ["Marketplace name", "Registration source", "Plugins used (range)", "Why"]
    lines = ["## Required marketplaces", "",
             "| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def write_market(root: Path, name, plugins=(), *, allowlist=NONE, prefix=None, readme=README,
                 license=True):
    """Write a marketplace. Each plugin is a dict: name, and optionally source, deps (entry
    dependencies), plugin_deps (plugin.json dependencies), concept (bool), missing (bool)."""
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in plugins:
        entry = {"name": spec["name"], "source": spec.get("source", f"./plugins/{spec['name']}")}
        if "deps" in spec:
            entry["dependencies"] = spec["deps"]
        entries.append(entry)
        if spec.get("missing"):
            continue
        plugin_dir = root / entry["source"]
        manifest = {"name": spec["name"], "version": "1.0.0"}
        if "plugin_deps" in spec:
            manifest["dependencies"] = spec["plugin_deps"]
        (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        if spec.get("concept"):
            concept = plugin_dir / CONCEPT
            concept.parent.mkdir(parents=True, exist_ok=True)
            concept.write_text(f"---\nname: {spec['name']}\ndescription: Concept.\n---\n\nBody.\n",
                               encoding="utf-8")
    manifest = {"name": name, "owner": {"name": "Synthetic"}, "plugins": entries}
    if allowlist is not NONE:
        manifest[M.ALLOWLIST_KEY] = allowlist
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(manifest), encoding="utf-8")
    if prefix is not None:
        (root / ".claude-plugin" / "guidance.json").write_text(json.dumps({"pluginPrefix": prefix}),
                                                               encoding="utf-8")
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    if license:
        (root / "LICENSE").write_text("MIT\n", encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def ctx(self, own_plugins=(), upstream_plugins=None, *, upstream_prefix=None, **own_kwargs):
        """Write acme-web (and acme-core when upstream_plugins is given) and return the context."""
        own_root = self.tmp / "acme-web"
        write_market(own_root, "acme-web", own_plugins, **own_kwargs)
        upstreams = {}
        if upstream_plugins is not None:
            up_root = self.tmp / "acme-core"
            write_market(up_root, "acme-core", upstream_plugins, prefix=upstream_prefix)
            upstreams["acme-core"] = Marketplace.load(up_root)
        return Context(root=own_root, marketplace=Marketplace.load(own_root), upstreams=upstreams)

    def run_check(self, ctx, check, severity=None):
        found = [f for f in M.run(ctx) if f.check == check]
        return [f for f in found if severity is None or f.severity == severity]

    def rewrite_manifest(self, ctx, edit):
        path = ctx.root / ".claude-plugin" / "marketplace.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        edit(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        return Context(root=ctx.root, marketplace=Marketplace.load(ctx.root), upstreams=ctx.upstreams)


class M1Test(Base):
    def test_missing_source_directory_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "missing": True}])
        self.assertEqual(len(self.run_check(ctx, "M1", "block")), 1)

    def test_present_directory_passes(self):
        ctx = self.ctx([{"name": "acme-x"}])
        self.assertEqual(self.run_check(ctx, "M1"), [])

    def test_source_outside_repository_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "source": "../elsewhere"}])
        self.assertEqual(len(self.run_check(ctx, "M1", "block")), 1)

    def test_object_source_is_not_checked(self):
        ctx = self.rewrite_manifest(self.ctx([{"name": "acme-x"}]),
                                    lambda d: d["plugins"][0].update(source={"source": "github", "repo": "a/b"}))
        self.assertEqual(self.run_check(ctx, "M1"), [])


class M2Test(Base):
    def test_unprefixed_plugin_warns(self):
        ctx = self.ctx([{"name": "secrets"}])
        self.assertEqual(len(self.run_check(ctx, "M2", "warn")), 1)

    def test_declared_prefix_removes_the_warning(self):
        ctx = self.ctx([{"name": "web-secrets"}], prefix="web")
        self.assertEqual(self.run_check(ctx, "M2"), [])

    def test_bare_prefix_name_warns(self):
        ctx = self.ctx([{"name": "acme-"}])
        self.assertEqual(len(self.run_check(ctx, "M2", "warn")), 1)

    def test_guidance_prefix_on_another_marketplace_warns(self):
        ctx = self.ctx([{"name": "acme-guidance-x"}])
        self.assertEqual(self.run_check(ctx, "M2"), [])
        ctx = self.ctx([{"name": "guidance-x"}])
        self.assertEqual(len(self.run_check(ctx, "M2", "warn")), 1)

    def test_m2_never_blocks(self):
        ctx = self.ctx([{"name": "secrets"}])
        self.assertEqual(self.run_check(ctx, "M2", "block"), [])

    def test_m2_is_reported_once_per_plugin(self):
        # The loader used to report M2 as well; the check module is the only source now.
        ctx = self.ctx([{"name": "secrets"}, {"name": "guidance-x"}])
        self.assertEqual(len(self.run_check(ctx, "M2")), 2)

    def test_shared_prefix_fix_declares_a_different_prefix_and_not_the_shared_name(self):
        # acme-core uses the same prefix, so "acme-<concept>" would trigger AD2. The fix must not suggest it.
        ctx = self.ctx([{"name": "secrets"}], upstream_plugins=[])
        findings = self.run_check(ctx, "M2", "warn")
        self.assertEqual(len(findings), 1)
        fix = findings[0].fix
        self.assertIn("pluginPrefix in .claude-plugin/guidance.json", fix)
        self.assertNotIn("metadata", fix)
        self.assertIn("other than 'acme'", fix)
        self.assertIn("acme-core", fix)
        self.assertIn("do not rename it acme-<concept>", fix)
        self.assertNotIn("name the plugin acme-<concept>", fix)

    def test_unshared_prefix_fix_names_the_plugin_under_the_prefix(self):
        ctx = self.ctx([{"name": "secrets"}], upstream_plugins=[], upstream_prefix="beta")
        findings = self.run_check(ctx, "M2", "warn")
        self.assertEqual(len(findings), 1)
        self.assertIn("name the plugin acme-<concept>, or declare pluginPrefix in .claude-plugin/guidance.json",
                      findings[0].fix)

    def test_guidance_name_fix_uses_this_marketplaces_prefix(self):
        ctx = self.ctx([{"name": "guidance-x"}])
        findings = self.run_check(ctx, "M2", "warn")
        self.assertEqual(findings[0].fix, "rename the plugin under this marketplace's prefix, acme-<concept>")


class M3Test(Base):
    def test_missing_license_blocks(self):
        ctx = self.ctx([], license=False)
        self.assertEqual(len(self.run_check(ctx, "M3", "block")), 1)

    def test_missing_readme_blocks(self):
        ctx = self.ctx([], readme=None)
        self.assertEqual(len(self.run_check(ctx, "M3", "block")), 1)

    def test_readme_without_license_reference_blocks(self):
        ctx = self.ctx([], readme="# acme-web\n\nAn ordinary readme.\n")
        self.assertEqual(len(self.run_check(ctx, "M3", "block")), 1)

    def test_license_reference_is_case_sensitive(self):
        ctx = self.ctx([], readme="# acme-web\n\nSee the license file.\n")
        self.assertEqual(len(self.run_check(ctx, "M3", "block")), 1)

    def test_complete_root_passes(self):
        self.assertEqual(self.run_check(self.ctx([]), "M3"), [])


class U1Test(Base):
    def test_dependency_in_plugin_json_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "concept": True,
                         "plugin_deps": [{"name": "acme-core-build", "marketplace": "acme-core",
                                          "version": "^1.0.0"}]}])
        self.assertEqual(len(self.run_check(ctx, "U1", "block")), 1)

    def test_dependency_in_entry_passes(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [{"name": "acme-build", "marketplace": "acme-core",
                                                    "version": "^1.0.0"}]}],
                       allowlist=["acme-core"], upstream_plugins=[{"name": "acme-build"}],
                       readme=README + section(["`acme-core`", "`acme/acme-core` (GitHub)",
                                                "`acme-build` `^1.0.0`", "Builds"]))
        self.assertEqual(self.run_check(ctx, "U1"), [])

    def test_guidance_dependency_in_plugin_json_is_not_u1(self):
        ctx = self.ctx([{"name": "acme-x", "plugin_deps": [{"name": "guidance-x",
                                                           "marketplace": "claude-plugin-guidance",
                                                           "version": "^1.0.0"}]}])
        self.assertEqual(self.run_check(ctx, "U1"), [])


class U2Test(Base):
    def dep(self, **fields):
        return {"name": "acme-build", "marketplace": "acme-core", **fields}

    def test_string_form_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "deps": ["acme-build@acme-core"]}])
        self.assertEqual(len(self.run_check(ctx, "U2", "block")), 1)

    def test_object_without_version_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.dep()]}])
        self.assertEqual(len(self.run_check(ctx, "U2", "block")), 1)

    def test_non_string_version_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.dep(version=1)]}])
        self.assertEqual(len(self.run_check(ctx, "U2", "block")), 1)

    def test_bounded_range_passes(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.dep(version="^1.0.0")]}])
        self.assertEqual(self.run_check(ctx, "U2"), [])

    def test_open_ended_range_warns(self):
        for version in ("*", "latest", "", ">="):
            with self.subTest(version=version):
                ctx = self.ctx([{"name": "acme-x", "deps": [self.dep(version=version)]}])
                self.assertEqual(len(self.run_check(ctx, "U2", "warn")), 1)

    def test_bounded_lower_and_upper_range_passes(self):
        for version in (">=1.0.0 <2", ">=1.0.0"):
            with self.subTest(version=version):
                ctx = self.ctx([{"name": "acme-x", "deps": [self.dep(version=version)]}])
                self.assertEqual(self.run_check(ctx, "U2"), [])


class U3Test(Base):
    def entry_dep(self):
        return {"name": "acme-build", "marketplace": "acme-core", "version": "^1.0.0"}

    def test_missing_allowlist_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.entry_dep()]}])
        self.assertEqual(len(self.run_check(ctx, "U3", "block")), 1)

    def test_marketplace_not_in_allowlist_blocks(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.entry_dep()]}], allowlist=["other"])
        self.assertEqual(len(self.run_check(ctx, "U3", "block")), 1)

    def test_marketplace_in_allowlist_passes(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [self.entry_dep()]}], allowlist=["acme-core"])
        self.assertEqual(self.run_check(ctx, "U3"), [])

    def test_guidance_marketplace_is_never_named(self):
        ctx = self.ctx([{"name": "acme-x", "deps": [{"name": "guidance-x",
                                                    "marketplace": "claude-plugin-guidance",
                                                    "version": "^1.0.0"}]}])
        self.assertEqual(self.run_check(ctx, "U3"), [])


class U4Test(Base):
    def entry(self):
        return {"name": "acme-build", "marketplace": "acme-core", "version": "^1.0.0"}

    def ctx_with(self, readme, deps=None, allowlist=("acme-core",)):
        deps = [self.entry()] if deps is None else deps
        return self.ctx([{"name": "acme-x", "deps": deps}], allowlist=list(allowlist), readme=readme)

    def row(self, plugins="`acme-build` `^1.0.0`", source="`acme/acme-core` (GitHub)"):
        return section(["`acme-core`", source, plugins, "Builds"])

    def test_complete_section_passes(self):
        self.assertEqual(self.run_check(self.ctx_with(README + self.row()), "U4"), [])

    def test_no_dependencies_and_no_allowlist_passes_without_section(self):
        ctx = self.ctx([{"name": "acme-x"}], readme=README)
        self.assertEqual(self.run_check(ctx, "U4"), [])

    def test_dependencies_without_section_block(self):
        self.assertEqual(len(self.run_check(self.ctx_with(README), "U4", "block")), 1)

    def test_allowlist_without_section_blocks(self):
        ctx = self.ctx([{"name": "acme-x"}], allowlist=["acme-core"], readme=README)
        self.assertEqual(len(self.run_check(ctx, "U4", "block")), 1)

    def test_wrong_column_order_blocks(self):
        readme = README + section(["`acme-core`", "`acme/acme-core` (GitHub)", "`acme-build` `^1.0.0`", "Builds"],
                                  header=["Marketplace name", "Plugins used (range)", "Registration source", "Why"])
        self.assertEqual(len(self.run_check(self.ctx_with(readme), "U4", "block")), 1)

    def test_missing_row_blocks(self):
        readme = README + section(["`other`", "`x/y` (GitHub)", "`z` `^1.0.0`", "Other"])
        self.assertEqual(len(self.run_check(self.ctx_with(readme), "U4", "block")), 1)

    def test_empty_registration_source_blocks(self):
        readme = README + self.row(source="")
        self.assertEqual(len(self.run_check(self.ctx_with(readme), "U4", "block")), 1)

    def test_plugin_name_mismatch_blocks(self):
        readme = README + self.row(plugins="`acme-deliver` `^1.0.0`")
        self.assertEqual(len(self.run_check(self.ctx_with(readme), "U4", "block")), 1)

    def test_range_text_differing_from_entry_warns(self):
        readme = README + self.row(plugins="`acme-build` `^2.0.0`")
        self.assertEqual(len(self.run_check(self.ctx_with(readme), "U4", "warn")), 1)
        self.assertEqual(self.run_check(self.ctx_with(readme), "U4", "block"), [])


class ADTest(Base):
    def test_colliding_concept_names_block(self):
        # With prefix acme, acme-secrets defines concept secrets; the unprefixed plugin
        # secrets also defines concept secrets.
        ctx = self.ctx([{"name": "acme-secrets", "concept": True}, {"name": "secrets", "concept": True}])
        self.assertEqual(len(self.run_check(ctx, "AD1", "block")), 1)

    def test_distinct_concept_names_pass(self):
        ctx = self.ctx([{"name": "acme-secrets", "concept": True}, {"name": "acme-build", "concept": True}])
        self.assertEqual(self.run_check(ctx, "AD1"), [])

    def test_plugin_name_equal_to_upstream_blocks(self):
        ctx = self.ctx([{"name": "web-build"}, {"name": "acme-build"}],
                       upstream_plugins=[{"name": "acme-build"}], prefix="web")
        found = self.run_check(ctx, "AD2", "block")
        self.assertTrue(any("acme-build" in f.message for f in found))

    def test_concept_name_equal_to_upstream_blocks(self):
        ctx = self.ctx([{"name": "web-build", "concept": True}],
                       upstream_plugins=[{"name": "acme-build", "concept": True}], prefix="web")
        found = self.run_check(ctx, "AD2", "block")
        self.assertTrue(any("concept name build" in f.message for f in found))

    def test_prefix_equal_to_upstream_prefix_blocks(self):
        ctx = self.ctx([{"name": "acme-x"}], upstream_plugins=[{"name": "acme-build"}])
        found = self.run_check(ctx, "AD2", "block")
        self.assertTrue(any("prefix acme" in f.message for f in found))

    def test_distinct_prefixes_and_names_pass(self):
        ctx = self.ctx([{"name": "web-secrets", "concept": True}],
                       upstream_plugins=[{"name": "acme-build", "concept": True}], prefix="web")
        self.assertEqual(self.run_check(ctx, "AD2"), [])

    def test_upstream_prefix_declared_separately(self):
        ctx = self.ctx([{"name": "web-secrets", "concept": True}],
                       upstream_plugins=[{"name": "core-build", "concept": True}],
                       upstream_prefix="core", prefix="web")
        self.assertEqual(self.run_check(ctx, "AD2"), [])


class RunTest(Base):
    def test_run_returns_list_of_findings(self):
        ctx = self.ctx([{"name": "secrets"}])
        found = M.run(ctx)
        self.assertIsInstance(found, list)
        self.assertTrue(all(f.check in {"M1", "M2", "M3", "U1", "U2", "U3", "U4", "AD1", "AD2"} for f in found))


if __name__ == "__main__":
    unittest.main()
