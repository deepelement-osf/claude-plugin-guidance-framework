"""builds_on resolves through the whole upstream chain, by one shared helper.

Three marketplaces: acme-core (root), acme-mid (depends on acme-core) and acme-web
(depends on acme-mid). A realization in acme-web may build on a realization of
build@acme-core, which it reaches only through acme-mid. F-tier3 and X-resolve both
use gc_model.realization_in_chain, so this file tests the helper through F-tier3,
which is the check that decides builds_on in the marketplace's own shape.

Standard library only. Run from the repository root:
    python3 -m unittest tests.test_builds_on_chain -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "guidance-conventions" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gc_checks_f as F  # noqa: E402
from gc_model import Context, Marketplace, Options, realization_in_chain  # noqa: E402


def realization_text(name, concept, builds_on=None):
    lines = ["---", f"name: realize-{name}", "description: test realization", "graph:",
             '  graphSpecVersion: "1.0"', "  runs: agent"]
    if builds_on is not None:
        lines.append(f"  builds_on: {builds_on}")
    lines += ["---", "", f"# {name}", "", "```realizes", f"concept: {concept}", f"name: {name}",
              'contractVersion: "^1.0.0"', "```", "", "Body.", ""]
    return "\n".join(lines)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_marketplace(root, name, plugins, deps):
    """plugins maps plugin name to {relative skill path: text}; deps maps plugin name to marketplaces."""
    entries = []
    for plugin in plugins:
        entry = {"name": plugin, "source": f"./plugins/{plugin}"}
        entry["dependencies"] = [{"name": "acme-build", "marketplace": m, "version": "^1.0.0"}
                                 for m in deps.get(plugin, [])]
        entries.append(entry)
    manifest = {"name": name, "owner": {"name": "Synthetic"}, "plugins": entries,
                "allowCrossMarketplaceDependenciesOn": sorted({m for ms in deps.values() for m in ms})}
    write(root / ".claude-plugin" / "marketplace.json", json.dumps(manifest, indent=2) + "\n")
    for plugin, files in plugins.items():
        write(root / "plugins" / plugin / ".claude-plugin" / "plugin.json",
              json.dumps({"name": plugin, "version": "1.0.0"}) + "\n")
        for rel, text in files.items():
            write(root / "plugins" / plugin / rel, text)


CORE_REALIZATIONS = {
    "skills/realize-markdown/SKILL.md": realization_text("markdown", "build@acme-core"),
    "skills/realize-lint/SKILL.md": realization_text("lint", "lint@acme-core"),
}


class BuildsOnChainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        write_marketplace(self.tmp / "acme-core", "acme-core",
                          {"acme-build": CORE_REALIZATIONS}, {})
        write_marketplace(self.tmp / "acme-mid", "acme-mid",
                          {"acme-mid-build": {"skills/realize-mid/SKILL.md":
                                              realization_text("mid", "build@acme-core")}},
                          {"acme-mid-build": ["acme-core"]})

    def web(self, builds_on, extra_deps=None, extra_plugins=None):
        plugins = {"acme-web-build": {"skills/realize-web/SKILL.md":
                                      realization_text("web", "build@acme-core", builds_on)}}
        deps = {"acme-web-build": ["acme-mid"]}
        if extra_deps:
            deps.update(extra_deps)
        if extra_plugins:
            plugins.update(extra_plugins)
        write_marketplace(self.tmp / "acme-web", "acme-web", plugins, deps)
        return self.load_context()

    def load_context(self):
        web = Marketplace.load(self.tmp / "acme-web")
        upstreams = {name: Marketplace.load(self.tmp / name) for name in ("acme-core", "acme-mid")}
        return Context(root=self.tmp / "acme-web", marketplace=web, upstreams=upstreams, options=Options())

    def tier3_blocks(self, ctx):
        return [f for f in F.run(ctx) if f.check == "F-tier3" and f.blocking]

    def test_builds_on_a_realization_two_levels_up_passes(self):
        self.assertEqual(self.tier3_blocks(self.web("markdown")), [])

    def test_builds_on_a_realization_of_another_concept_blocks(self):
        self.assertEqual(len(self.tier3_blocks(self.web("lint"))), 1)

    def test_builds_on_a_missing_name_blocks(self):
        self.assertEqual(len(self.tier3_blocks(self.web("no-such-realization"))), 1)

    def test_builds_on_its_own_name_blocks(self):
        self.assertEqual(len(self.tier3_blocks(self.web("web"))), 1)

    def test_builds_on_a_realization_of_an_unreached_marketplace_blocks(self):
        write_marketplace(self.tmp / "acme-other", "acme-other",
                          {"acme-other-build": {"skills/realize-other/SKILL.md":
                                                realization_text("other", "build@acme-core")}}, {})
        ctx = self.web("other")
        self.assertEqual(len(self.tier3_blocks(ctx)), 1)

    def test_helper_follows_dependencies_to_the_root(self):
        ctx = self.web("markdown")
        self.assertTrue(realization_in_chain("markdown", "build@acme-core", ctx.marketplace, ctx.upstreams))
        self.assertFalse(realization_in_chain("markdown", None, ctx.marketplace, ctx.upstreams))


if __name__ == "__main__":
    unittest.main()
