"""Tests for the A and E checks in gc_checks_a. Standard library only.

Each test writes a small synthetic marketplace into a temporary directory, loads it,
runs gc_checks_a.run, and looks at the findings. A published marketplace exercises
set A. A realization marketplace, with acme-core as its upstream, exercises set E.
Nothing outside the temporary directory is written.

Run from the repository root:

    python3 -m unittest tests.test_gc_checks_a -v
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

import gc_checks_a as A  # noqa: E402
from gc_model import Context, Marketplace, Options  # noqa: E402

SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
OWNER = {"name": "Synthetic", "email": "maintainers@acme.example"}

PUB = "plugins/acme-secrets/"
CONCEPT_SKILL = PUB + "skills/concept/SKILL.md"
CONTRACT_SKILL = PUB + "skills/realization-contract/SKILL.md"
CONTRACT_SCHEMA = PUB + "skills/realization-contract/schema.json"
REALIZE_SKILL = PUB + "skills/realize-env-file/SKILL.md"
REALIZE_SCHEMA = PUB + "skills/realize-env-file/schema.json"

TIER2 = {
    "$schema": SCHEMA_URI,
    "contractVersion": "1.0.0",
    "type": "object",
    "required": ["scope"],
    "properties": {"scope": {"type": "string", "description": "Namespace the secret names belong to."}},
}
REALIZATION_SCHEMA = {
    "$schema": SCHEMA_URI,
    "type": "object",
    "required": ["scope"],
    "properties": {
        "scope": {"type": "string", "description": "Namespace the secret names belong to."},
        "env_prefix": {"type": "string", "description": "Prefix added to a name.", "default": "ACME_"},
    },
}

REAL = "plugins/acme-realize-build/"
BUILD_SKILL = REAL + "skills/realize-build-script/SKILL.md"
BUILD_SCHEMA = REAL + "skills/realize-build-script/schema.json"
BUILD_TIER2_SCHEMA = {"$schema": SCHEMA_URI, "contractVersion": "1.0.0", "type": "object",
                      "required": ["scope"],
                      "properties": {"scope": {"type": "string", "description": "Scope the build belongs to."}}}
BUILD_SCHEMA_BODY = {"$schema": SCHEMA_URI, "type": "object", "required": ["scope"],
                     "properties": {"scope": {"type": "string", "description": "Scope the build belongs to."}}}


def concept_text(name: str, description: str) -> str:
    return (f"---\nname: {name}\ndescription: {description}\ngraph:\n  graphSpecVersion: \"1.0\"\n---\n\n"
            f"# {name.capitalize()}\n\n{description}\n\n## Operations\n\n- Store a value under a name.\n")


def contract_text(example='{"scope": "acme-vault"}') -> str:
    body = ("---\nname: realization-contract\ndescription: Realization contract for the secrets capability.\n"
            "---\n\n# Secrets realization contract\n\n"
            "A realization of secrets must store and retrieve values by name.\n")
    if example is not None:
        body += f"\n## Example config\n\n```config\n{example}\n```\n"
    return body


def realize_text(name: str = "realize-env-file", default: bool = True, statement: str = "auto",
                 realizes: str = "") -> str:
    """A realization SKILL.md. statement 'auto' writes the line that matches default; '' writes none."""
    head = f"---\nname: {name}\ndescription: Environment-file secrets realization.\n"
    if default:
        head += "default: true\n"
    head += "---\n\n"
    if statement == "auto":
        statement = f"Default realization: {'yes' if default else 'no'}"
    lines = [f"# {name}", ""]
    if statement:
        lines += [statement, ""]
    return head + "\n".join(lines) + "\n" + realizes + "Looks up a secret name and reports the value.\n"


def realizes_block(concept: str = "build@acme-core", name: str = "build-script",
                   version: str = "^1.0.0", include_version: bool = True) -> str:
    lines = ["```realizes", f"concept: {concept}", f"name: {name}"]
    if include_version:
        lines.append(f"contractVersion: \"{version}\"")
    lines += ["```", ""]
    return "\n".join(lines) + "\n"


def published_files() -> dict:
    """A published marketplace with one concept plugin: Tier 1, a contract, and one default realization."""
    return {
        ".claude-plugin/marketplace.json": {
            "name": "acme-vault", "owner": OWNER,
            "plugins": [{"name": "acme-secrets", "source": "./plugins/acme-secrets",
                         "description": "The secrets capability."}],
        },
        PUB + ".claude-plugin/plugin.json": {"name": "acme-secrets", "version": "1.0.0"},
        CONCEPT_SKILL: concept_text("secrets", "Secrets capability. Stores and retrieves a secret by name."),
        CONTRACT_SKILL: contract_text(),
        CONTRACT_SCHEMA: TIER2,
        REALIZE_SKILL: realize_text(),
        REALIZE_SCHEMA: REALIZATION_SCHEMA,
    }


def realization_files() -> dict:
    """A realization marketplace with one realization of build@acme-core."""
    entry = {"name": "acme-realize-build", "source": "./plugins/acme-realize-build",
             "description": "Script realization of build.",
             "dependencies": [{"name": "acme-build", "marketplace": "acme-core", "version": "^1.0.0"}]}
    return {
        ".claude-plugin/marketplace.json": {
            "name": "acme-build-realizations", "owner": OWNER,
            "allowCrossMarketplaceDependenciesOn": ["acme-core"], "plugins": [entry],
        },
        REAL + ".claude-plugin/plugin.json": {"name": "acme-realize-build", "version": "1.0.0"},
        BUILD_SKILL: realize_text("realize-build-script", default=False, realizes=realizes_block()),
        BUILD_SCHEMA: BUILD_SCHEMA_BODY,
    }


def upstream_files() -> dict:
    """acme-core: one concept plugin, acme-build, whose Tier 2 schema is the contract."""
    return {
        ".claude-plugin/marketplace.json": {
            "name": "acme-core", "owner": OWNER,
            "plugins": [{"name": "acme-build", "source": "./plugins/acme-build",
                         "description": "The build capability."}],
        },
        "plugins/acme-build/.claude-plugin/plugin.json": {"name": "acme-build", "version": "1.0.0"},
        "plugins/acme-build/skills/concept/SKILL.md": concept_text("build", "Build capability."),
        "plugins/acme-build/skills/realization-contract/SKILL.md": contract_text('{"scope": "ci"}'),
        "plugins/acme-build/skills/realization-contract/schema.json": BUILD_TIER2_SCHEMA,
    }


def _write_tree(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def published(self, files=None) -> Context:
        files = published_files() if files is None else files
        root = self.tmp / "acme-vault"
        _write_tree(root, files)
        return Context(root=root, marketplace=Marketplace.load(root), upstreams={}, options=Options())

    def realization(self, files=None, upstream=None) -> Context:
        files = realization_files() if files is None else files
        upstream = upstream_files() if upstream is None else upstream
        root = self.tmp / "acme-build-realizations"
        up_root = self.tmp / "acme-core"
        _write_tree(root, files)
        _write_tree(up_root, upstream)
        return Context(root=root, marketplace=Marketplace.load(root),
                       upstreams={"acme-core": Marketplace.load(up_root)}, options=Options())

    def found(self, ctx, check):
        return [f for f in A.run(ctx) if f.check == check]

    def blocking(self, ctx, check):
        return [f for f in self.found(ctx, check) if f.blocking]

    def warnings(self, ctx, check):
        return [f for f in self.found(ctx, check) if not f.blocking]


class PublishedTest(Base):
    def test_clean_marketplace_has_no_findings(self):
        self.assertEqual(A.run(self.published()), [])

    def test_contract_without_concept_blocks_a1(self):
        # acme-secrets keeps its concept, so the marketplace is published. acme-cache has a contract only.
        files = published_files()
        files[".claude-plugin/marketplace.json"]["plugins"].append(
            {"name": "acme-cache", "source": "./plugins/acme-cache", "description": "A cache."})
        files["plugins/acme-cache/.claude-plugin/plugin.json"] = {"name": "acme-cache", "version": "1.0.0"}
        files["plugins/acme-cache/skills/realization-contract/SKILL.md"] = contract_text()
        files["plugins/acme-cache/skills/realization-contract/schema.json"] = TIER2
        found = self.blocking(self.published(files), "A1")
        self.assertEqual(len(found), 1)
        self.assertIn("acme-cache", found[0].message)

    def test_realization_without_contract_skill_blocks_a2(self):
        files = published_files()
        del files[CONTRACT_SKILL]
        found = self.blocking(self.published(files), "A2")
        self.assertEqual(len(found), 1)
        self.assertIn("realization-contract/SKILL.md", found[0].file)

    def test_unparseable_contract_schema_blocks_a3(self):
        files = published_files()
        files[CONTRACT_SCHEMA] = '{ "type": "object"\n'
        found = self.blocking(self.published(files), "A3")
        self.assertEqual(len(found), 1)
        self.assertIn("does not parse", found[0].message)

    def test_contract_schema_without_contract_version_warns_a3(self):
        files = published_files()
        files[CONTRACT_SCHEMA] = {k: v for k, v in TIER2.items() if k != "contractVersion"}
        ctx = self.published(files)
        self.assertEqual(self.blocking(ctx, "A3"), [])
        found = self.warnings(ctx, "A3")
        self.assertEqual(len(found), 1)
        self.assertIn("contractVersion", found[0].message)

    def test_missing_config_example_warns_a3(self):
        files = published_files()
        files[CONTRACT_SKILL] = contract_text(example=None)
        found = self.warnings(self.published(files), "A3")
        self.assertEqual(len(found), 1)
        self.assertIn("no example config block", found[0].message)

    def test_config_example_that_violates_schema_warns_a3(self):
        files = published_files()
        files[CONTRACT_SKILL] = contract_text(example='{"scope": 3}')
        found = self.warnings(self.published(files), "A3")
        self.assertEqual(len(found), 1)
        self.assertIn("no example config block satisfies", found[0].message)

    def test_two_default_realizations_block_a5(self):
        files = published_files()
        files[PUB + "skills/realize-vault-kv/SKILL.md"] = realize_text("realize-vault-kv", default=True)
        files[PUB + "skills/realize-vault-kv/schema.json"] = REALIZATION_SCHEMA
        found = self.blocking(self.published(files), "A5")
        self.assertEqual(len(found), 1)
        self.assertIn("2 marked", found[0].message)

    def test_no_default_realization_blocks_a5(self):
        files = published_files()
        files[REALIZE_SKILL] = realize_text(default=False)
        found = self.blocking(self.published(files), "A5")
        self.assertEqual(len(found), 1)
        self.assertIn("0 marked", found[0].message)

    def test_missing_realization_schema_blocks_a6(self):
        files = published_files()
        del files[REALIZE_SCHEMA]
        found = self.blocking(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("is missing", found[0].message)

    def test_realization_schema_dropping_a_required_field_blocks_a6(self):
        files = published_files()
        files[REALIZE_SCHEMA] = {k: v for k, v in REALIZATION_SCHEMA.items() if k != "required"}
        found = self.blocking(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("requires scope", found[0].message)

    def test_realization_schema_with_another_type_blocks_a6(self):
        files = published_files()
        schema = json.loads(json.dumps(REALIZATION_SCHEMA))
        schema["properties"]["scope"]["type"] = "integer"
        files[REALIZE_SCHEMA] = schema
        found = self.blocking(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("Tier 2 has 'string'", found[0].message)

    def test_property_without_description_warns_a6(self):
        files = published_files()
        schema = json.loads(json.dumps(REALIZATION_SCHEMA))
        del schema["properties"]["env_prefix"]["description"]
        files[REALIZE_SCHEMA] = schema
        found = self.warnings(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("env_prefix", found[0].message)

    def test_skill_without_default_statement_warns_a6(self):
        files = published_files()
        files[REALIZE_SKILL] = realize_text(statement="")
        found = self.warnings(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("does not state its default status", found[0].message)

    def test_default_statement_that_disagrees_with_front_matter_warns_a6(self):
        files = published_files()
        files[REALIZE_SKILL] = realize_text(default=True, statement="Default realization: no")
        found = self.warnings(self.published(files), "A6")
        self.assertEqual(len(found), 1)
        self.assertIn("front matter", found[0].message)

    def test_generic_realization_name_warns_a7(self):
        files = published_files()
        del files[REALIZE_SKILL]
        del files[REALIZE_SCHEMA]
        files[PUB + "skills/realize-default/SKILL.md"] = realize_text("realize-default", default=True)
        files[PUB + "skills/realize-default/schema.json"] = REALIZATION_SCHEMA
        found = self.warnings(self.published(files), "A7")
        self.assertEqual(len(found), 1)
        self.assertIn("realize-default", found[0].message)

    def test_realizes_name_that_differs_from_directory_warns_a9(self):
        # The realizes block sets the name; the directory says env-file.
        files = published_files()
        files[REALIZE_SKILL] = realize_text(
            default=True, realizes=realizes_block(concept="secrets@acme-vault", name="vault-kv", version="^1.0.0"))
        found = self.warnings(self.published(files), "A9")
        self.assertEqual(len(found), 1)
        self.assertIn("'vault-kv'", found[0].message)
        self.assertIn("'env-file'", found[0].message)

    def test_contract_without_realization_warns_a4(self):
        files = published_files()
        del files[REALIZE_SKILL]
        del files[REALIZE_SCHEMA]
        found = self.warnings(self.published(files), "A4")
        self.assertEqual(len(found), 1)
        self.assertIn("published early", found[0].message)


class RealizationMarketplaceTest(Base):
    def test_clean_realization_marketplace_has_no_findings(self):
        self.assertEqual(A.run(self.realization()), [])

    def test_plugin_holding_a_contract_blocks_e1(self):
        files = realization_files()
        files[REAL + "skills/realization-contract/SKILL.md"] = contract_text()
        found = self.blocking(self.realization(files), "E1")
        self.assertEqual(len(found), 1)
        self.assertIn("holds a realization contract", found[0].message)

    def test_plugin_without_realize_skill_blocks_e1(self):
        # acme-empty has no realize-* skill; the build realization keeps the marketplace a realization one.
        files = realization_files()
        files[".claude-plugin/marketplace.json"]["plugins"].append(
            {"name": "acme-empty", "source": "./plugins/acme-empty", "description": "Nothing yet."})
        files["plugins/acme-empty/.claude-plugin/plugin.json"] = {"name": "acme-empty", "version": "1.0.0"}
        found = self.blocking(self.realization(files), "E1")
        self.assertEqual(len(found), 1)
        self.assertIn("plugin acme-empty has no realize-* skill", found[0].message)

    def test_realization_without_realizes_block_blocks_e2(self):
        files = realization_files()
        files[BUILD_SKILL] = realize_text("realize-build-script", default=False, realizes="")
        found = self.blocking(self.realization(files), "E2")
        self.assertEqual(len(found), 1)
        self.assertIn("has no realizes block", found[0].message)

    def test_unqualified_concept_blocks_e2(self):
        files = realization_files()
        files[BUILD_SKILL] = realize_text("realize-build-script", default=False,
                                          realizes=realizes_block(concept="build"))
        found = self.blocking(self.realization(files), "E2")
        self.assertEqual(len(found), 1)
        self.assertIn("<concept>@<marketplace>", found[0].message)

    def test_missing_contract_version_blocks_e2(self):
        files = realization_files()
        files[BUILD_SKILL] = realize_text("realize-build-script", default=False,
                                          realizes=realizes_block(include_version=False))
        found = self.blocking(self.realization(files), "E2")
        self.assertEqual(len(found), 1)
        self.assertIn("has no contractVersion", found[0].message)

    def test_pre_release_contract_version_blocks_e2(self):
        files = realization_files()
        files[BUILD_SKILL] = realize_text("realize-build-script", default=False,
                                          realizes=realizes_block(version="^1.0.0-beta.1"))
        found = self.blocking(self.realization(files), "E2")
        self.assertEqual(len(found), 1)
        self.assertIn("pre-release", found[0].message)

    def test_skills_in_one_plugin_naming_different_concepts_block_e2(self):
        files = realization_files()
        files[REAL + "skills/realize-build-alt/SKILL.md"] = realize_text(
            "realize-build-alt", default=False, realizes=realizes_block(concept="deploy@acme-core"))
        files[REAL + "skills/realize-build-alt/schema.json"] = BUILD_SCHEMA_BODY
        found = self.blocking(self.realization(files), "E2")
        self.assertTrue(any("different concepts" in f.message for f in found))

    def test_no_entry_dependency_blocks_e3(self):
        files = realization_files()
        manifest = files[".claude-plugin/marketplace.json"]
        manifest["plugins"][0].pop("dependencies")
        found = self.blocking(self.realization(files), "E3")
        self.assertEqual(len(found), 1)
        self.assertIn("no entry dependency on marketplace acme-core", found[0].message)

    def test_dependency_naming_a_missing_plugin_blocks_e3(self):
        files = realization_files()
        files[".claude-plugin/marketplace.json"]["plugins"][0]["dependencies"][0]["name"] = "acme-deploy"
        found = self.blocking(self.realization(files), "E3")
        self.assertEqual(len(found), 1)
        self.assertIn("is not a plugin of marketplace acme-core", found[0].message)

    def test_upstream_concept_without_tier2_schema_blocks_e3(self):
        upstream = upstream_files()
        del upstream["plugins/acme-build/skills/realization-contract/schema.json"]
        found = self.blocking(self.realization(upstream=upstream), "E3")
        self.assertEqual(len(found), 1)
        self.assertIn("no Tier 2 schema.json", found[0].message)

    def test_same_concept_and_name_in_two_plugins_blocks_e4(self):
        files = realization_files()
        files[".claude-plugin/marketplace.json"]["plugins"].append({
            "name": "acme-realize-build-alt", "source": "./plugins/acme-realize-build-alt",
            "description": "A second script realization of build.",
            "dependencies": [{"name": "acme-build", "marketplace": "acme-core", "version": "^1.0.0"}],
        })
        files["plugins/acme-realize-build-alt/.claude-plugin/plugin.json"] = {"name": "acme-realize-build-alt",
                                                                            "version": "1.0.0"}
        files["plugins/acme-realize-build-alt/skills/realize-build-script/SKILL.md"] = realize_text(
            "realize-build-script", default=False, realizes=realizes_block())
        files["plugins/acme-realize-build-alt/skills/realize-build-script/schema.json"] = BUILD_SCHEMA_BODY
        found = self.blocking(self.realization(files), "E4")
        self.assertEqual(len(found), 1)
        self.assertIn("build-script of build@acme-core", found[0].message)

    def test_default_marked_realization_blocks_e5(self):
        files = realization_files()
        files[BUILD_SKILL] = realize_text("realize-build-script", default=True, realizes=realizes_block())
        found = self.blocking(self.realization(files), "E5")
        self.assertEqual(len(found), 1)
        self.assertIn("default: true", found[0].message)


if __name__ == "__main__":
    unittest.main()
