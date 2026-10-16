"""Checks A1 to A9 and E1 to E5, the mechanical rows, run by guidance_check.py.

Standard library only. run(ctx) returns Finding objects. It never edits a file.
The judgement rows of set A and set D stay with the validate-concept-plugin
skill, and the rows of sets B and C with their own checks.

Scope
    Set E runs on a realization marketplace: one that holds realizations and no
    concept (Marketplace.concepts is empty). Every other marketplace gets set A.
    A realization marketplace holds no Tier 1 and no Tier 2, so set A has
    nothing to say about it, and set E has nothing to say about a published one.

Set A (published marketplace)
    A1  A plugin with a skills/realization-contract/ directory, or with a
        realize-* skill that has no realizes block, has skills/concept/SKILL.md.
    A2  A concept with a realization has skills/realization-contract/SKILL.md.
    A3  A concept with a contract directory or a realization has a schema.json
        that is a JSON object in the guidance JSON Schema subset (block). It
        warns when the schema has no top-level contractVersion, and when the
        contract SKILL.md has no example config block that satisfies it. An
        example config block is a fenced block whose info string is "config".
        Its content is a JSON object, or a YAML mapping in the subset.
    A4  A concept with a contract directory and no realization warns, so the
        contract is looked at as possibly published early.
    A5  A concept with realizations has exactly one realization whose front
        matter says default: true. The marker is that front matter key alone.
    A6  Each realization's schema.json exists, parses, and is in the subset
        (block). It keeps every Tier 2 required field required, with the same
        type (block), when the defining concept's Tier 2 schema is loaded. It
        warns when a property has no description, and when the SKILL.md does
        not state the default status. The statement is a line
        "Default realization: yes" or "Default realization: no", which must
        agree with the front matter.
    A7  A realization whose directory name, minus realize-, repeats the
        concept's bare name, or is one of GENERIC_NAMES, warns.
    A9  A realization's name differs from its directory name minus realize-,
        or two realizations of one plugin share a name. Both warn.

Set E (realization marketplace)
    E1  Each plugin has at least one realize-* skill, and has no
        skills/realization-contract/ directory. A concept cannot appear here,
        because a marketplace with one is not a realization marketplace.
    E2  Each realize-* SKILL.md has a realizes block with a name, a qualified
        concept, and a contractVersion that is a semantic-version range with no
        pre-release suffix. Every skill in one plugin names the same concept.
    E3  The plugin's marketplace entry has a dependency on the concept's
        qualifier. That dependency names a plugin of the loaded upstream whose
        concept name, under the upstream's prefix, is the bare concept name, and
        whose concept has a Tier 2 schema.json. A run that cannot load the
        upstream stops under X-resolve before this check, so the check needs no
        "unverified" outcome.
    E4  Each pair of concept and directory-derived realization name occurs once.
    E5  No realization in the marketplace has default: true.

Public API
----------
run(ctx) -> list[Finding]
GENERIC_NAMES, RANGE, REALIZE_PREFIX
    The constants below. They are part of the mechanical definition, not a judgement.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gc_checks_f import _subset_problems
from gc_model import Concept, Context, Finding, Marketplace, Plugin, Realization, concept_name, normal_dependencies
from gc_parse import YamlSubsetError, load_json, parse_yaml_subset, read_skill, validate_json_schema

REALIZE_PREFIX = "realize-"
GENERIC_NAMES = ("default", "generic", "basic", "common", "standard", "simple", "main")
RANGE = re.compile(r"^(?:\^|~|>=|<=|>|<|=)?\d+\.\d+\.\d+$")
_DEFAULT_STATEMENT = re.compile(r"^Default realization:[ \t]*(yes|no)[ \t]*$", re.M)
_CONFIG_BLOCK = re.compile(r"^```config[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
_READ_ERRORS = (OSError, UnicodeDecodeError, ValueError)


# -- helpers ---------------------------------------------------------------

def _block(out: List[Finding], check: str, file: Optional[str], message: str, fix: str = "") -> None:
    out.append(Finding(check, "block", file, message, fix))


def _warn(out: List[Finding], check: str, file: Optional[str], message: str, fix: str = "") -> None:
    out.append(Finding(check, "warn", file, message, fix))


def _split_ref(ref: Any) -> Optional[Tuple[str, str]]:
    """(concept, marketplace) for a qualified reference, or None when it is not one."""
    if not isinstance(ref, str) or ref.count("@") != 1:
        return None
    name, marketplace = ref.split("@", 1)
    if not name or not marketplace:
        return None
    return name, marketplace


def _dir_name(realization: Realization) -> str:
    return realization.dir.name[len(REALIZE_PREFIX):]


def _block_concept(realization: Realization) -> Any:
    """The concept string of the realizes block, or None when there is no block or no string."""
    if realization.realizes is None:
        return None
    value = realization.realizes.get("concept")
    return value if isinstance(value, str) else None


def _plugin_realizations(mp: Marketplace, plugin: Plugin) -> List[Realization]:
    return [r for r in mp.realizations if r.plugin.name == plugin.name]


def _is_realization_marketplace(mp: Marketplace) -> bool:
    return bool(mp.realizations) and not mp.concepts


def _defining_concept(ctx: Context, concept_ref: Any) -> Optional[Concept]:
    """The concept a qualified reference names, in this marketplace or a loaded upstream."""
    split = _split_ref(concept_ref)
    if split is None:
        return None
    name, marketplace_name = split
    if marketplace_name == ctx.marketplace.name:
        return ctx.marketplace.concepts.get(name)
    upstream = ctx.upstream(marketplace_name)
    return upstream.concepts.get(name) if upstream is not None else None


def _read_schema(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """(schema, problem). The problem is a message when the file is missing, unreadable or not a schema."""
    if not path.is_file():
        return None, "is missing"
    try:
        value = load_json(path)
    except _READ_ERRORS as exc:
        return None, f"does not parse: {exc}"
    if not isinstance(value, dict):
        return None, "is not a JSON object"
    problems = _subset_problems(value, "$", value)
    if problems:
        return None, f"is outside the JSON Schema subset: {problems[0]}"
    return value, None


def _parse_example(text: str) -> Optional[dict]:
    try:
        value: Any = json.loads(text)
    except ValueError:
        try:
            value = parse_yaml_subset(text, source="config block")
        except YamlSubsetError:
            return None
    return value if isinstance(value, dict) else None


def _entry_dependencies(entry: Dict[str, Any], own: str) -> List[Dict[str, Any]]:
    """The dependencies declared on a marketplace entry, as name and marketplace. Entry only, not plugin.json.

    The loader's parser reads them, so a string entry "name@marketplace" counts as the object form does.
    A bare string names a plugin of own, the marketplace this entry belongs to.
    """
    if not isinstance(entry, dict):
        return []
    deps, _ = normal_dependencies(entry.get("dependencies"), own)
    return deps


def _defining_problem(upstream: Marketplace, dep_name: str, bare: str) -> Optional[str]:
    """Why a dependency does not define the concept named bare, or None when it does."""
    if dep_name not in upstream.plugins:
        return f"dependency {dep_name} is not a plugin of marketplace {upstream.name}"
    derived = concept_name(dep_name, upstream.prefix)
    if derived != bare:
        return f"dependency {dep_name} defines concept {derived}, not {bare}"
    concept = upstream.concepts.get(derived)
    if concept is None:
        return f"{dep_name} is not a concept plugin of marketplace {upstream.name}"
    if concept.schema is None:
        return f"{dep_name} has no Tier 2 schema.json, so there is no contract to realize"
    return None


# -- set A -----------------------------------------------------------------

def _a1(mp: Marketplace, out: List[Finding]) -> None:
    for plugin in mp.plugins.values():
        if plugin.dir is None or plugin.has_concept:
            continue
        contract_dir = plugin.dir / "skills" / "realization-contract"
        bare = [r for r in _plugin_realizations(mp, plugin)
                if r.realizes is None and r.realizes_error is None]
        if not contract_dir.is_dir() and not bare:
            continue
        if contract_dir.is_dir():
            what = "has a realization-contract directory"
        else:
            what = f"has realize-* skill {bare[0].dir.name} with no realizes block"
        _block(out, "A1", mp.rel(plugin.dir / "skills"),
               f"plugin {plugin.name} {what} but no skills/concept/SKILL.md",
               "add the Tier 1 concept skill, or move the realization to a realization marketplace")


def _a2(mp: Marketplace, concept: Concept, out: List[Finding]) -> None:
    if concept.realizations and not concept.contract_skill_exists:
        _block(out, "A2", mp.rel(concept.plugin.dir / "skills" / "realization-contract" / "SKILL.md"),
               f"{concept.id} has {len(concept.realizations)} realization(s) but no realization-contract/SKILL.md",
               "add skills/realization-contract/SKILL.md, which defines the operations and the name convention")


def _a3(mp: Marketplace, concept: Concept, out: List[Finding]) -> None:
    contract_dir = concept.plugin.dir / "skills" / "realization-contract"
    if not contract_dir.is_dir() and not concept.realizations:
        return
    path = contract_dir / "schema.json"
    rel = mp.rel(path)
    schema, problem = _read_schema(path)
    if schema is None:
        _block(out, "A3", rel, f"schema.json {problem}", "add a schema.json that is a JSON Schema object in the guidance subset")
        return
    if "contractVersion" not in schema:
        _warn(out, "A3", rel, f"schema.json of {concept.id} has no contractVersion",
              "add a contractVersion field, such as \"1.0.0\"")
    _a3_example(mp, concept, schema, out)


def _a3_example(mp: Marketplace, concept: Concept, schema: dict, out: List[Finding]) -> None:
    skill_path = concept.plugin.dir / "skills" / "realization-contract" / "SKILL.md"
    rel = mp.rel(skill_path)
    if not skill_path.is_file():
        _warn(out, "A3", rel, "the contract has no SKILL.md, so it has no example config block",
              "add skills/realization-contract/SKILL.md with a ```config example")
        return
    blocks = _CONFIG_BLOCK.findall(read_skill(skill_path).body)
    if not blocks:
        _warn(out, "A3", rel, "the contract SKILL.md has no example config block",
              "add a ```config fenced block that satisfies schema.json")
        return
    errors: List[str] = []
    for text in blocks:
        example = _parse_example(text)
        if example is None:
            errors.append("the config block is not a JSON or YAML mapping")
            continue
        problems = validate_json_schema(example, schema)
        if not problems:
            return
        errors.append(problems[0])
    _warn(out, "A3", rel, f"no example config block satisfies schema.json: {errors[0]}",
          "make the example config block satisfy schema.json")


def _a4(mp: Marketplace, concept: Concept, out: List[Finding]) -> None:
    contract_dir = concept.plugin.dir / "skills" / "realization-contract"
    if contract_dir.is_dir() and not concept.realizations:
        _warn(out, "A4", mp.rel(contract_dir),
              f"{concept.id} has a realization contract and no realization; was the contract published early?",
              "confirm the contract is meant to be published before its first realization")


def _a5(concept: Concept, out: List[Finding]) -> None:
    if not concept.realizations:
        return
    defaults = [r for r in concept.realizations if r.default]
    if len(defaults) != 1:
        names = ", ".join(r.dir.name for r in defaults) or "none"
        _block(out, "A5", concept.skill_relpath,
               f"{concept.id} has {len(concept.realizations)} realization(s) and {len(defaults)} marked "
               f"default: true ({names}); exactly one is the default",
               "keep default: true on exactly one realize-* skill of this concept")


def _a6(ctx: Context, r: Realization, out: List[Finding]) -> None:
    mp = ctx.marketplace
    rel = mp.rel(r.dir / "schema.json")
    schema, problem = _read_schema(r.dir / "schema.json")
    if schema is None:
        _block(out, "A6", rel, f"realization {r.dir.name} schema.json {problem}",
               "add schema.json beside SKILL.md, as a superset of the concept's Tier 2 schema")
    else:
        _a6_superset(ctx, r, schema, rel, out)
        own_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for name, spec in sorted(own_props.items()):
            if not isinstance(spec, dict) or not isinstance(spec.get("description"), str) \
                    or not spec["description"].strip():
                _warn(out, "A6", rel, f"property {name} of {r.dir.name} has no description",
                      "add a description to the property")
    _a6_default_statement(r, out)


def _a6_superset(ctx: Context, r: Realization, schema: dict, rel: str, out: List[Finding]) -> None:
    concept = _defining_concept(ctx, r.concept_ref)
    if concept is None or not isinstance(concept.schema, dict):
        # The concept is absent or has no Tier 2 schema. X-placement and A3 own those cases.
        return
    tier2 = concept.schema
    tier2_required = [n for n in (tier2.get("required") or []) if isinstance(n, str)]
    tier2_props = tier2.get("properties") if isinstance(tier2.get("properties"), dict) else {}
    own_required = [n for n in (schema.get("required") or []) if isinstance(n, str)]
    own_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for name in tier2_required:
        if name not in own_required:
            _block(out, "A6", rel, f"Tier 2 of {concept.id} requires {name}; {r.dir.name} does not require it",
                   f"list {name} in the required array of schema.json")
        if name not in own_props:
            _block(out, "A6", rel, f"{r.dir.name} does not define Tier 2 field {name}",
                   f"add the {name} property, with the Tier 2 type")
            continue
        want = tier2_props.get(name, {}).get("type") if isinstance(tier2_props.get(name), dict) else None
        have = own_props[name].get("type") if isinstance(own_props[name], dict) else None
        if want is not None and have != want:
            _block(out, "A6", rel, f"field {name} of {r.dir.name} is {have!r}; Tier 2 has {want!r}",
                   f"give {name} the Tier 2 type {want!r}")


def _a6_default_statement(r: Realization, out: List[Finding]) -> None:
    match = _DEFAULT_STATEMENT.search(r.skill.body)
    if match is None:
        _warn(out, "A6", r.skill_relpath, f"realization {r.dir.name} does not state its default status",
              "add the line 'Default realization: yes' or 'Default realization: no' to the body")
        return
    stated = match.group(1) == "yes"
    if stated != r.default:
        _warn(out, "A6", r.skill_relpath,
              f"the body says Default realization: {match.group(1)}, and the front matter says default is {r.default}",
              "make the body statement and the front matter agree")


def _a7(r: Realization, out: List[Finding]) -> None:
    split = _split_ref(r.concept_ref)
    name = _dir_name(r)
    bare = split[0] if split else None
    if name == bare or name in GENERIC_NAMES:
        _warn(out, "A7", r.skill_relpath,
              f"realization directory {r.dir.name} does not name the provider or technology it implements",
              "name the directory for the provider or technology, such as realize-aws-secrets-manager")


def _a9(mp: Marketplace, out: List[Finding]) -> None:
    seen: Dict[Tuple[str, str], Realization] = {}
    for r in mp.realizations:
        dir_name = _dir_name(r)
        if r.name != dir_name:
            _warn(out, "A9", r.skill_relpath,
                  f"realization name {r.name!r} differs from the directory name {dir_name!r}",
                  f"name the realization {dir_name!r}, or rename the directory")
        key = (r.plugin.name, r.name)
        if key in seen:
            _warn(out, "A9", r.skill_relpath,
                  f"realization name {r.name!r} is already used in plugin {r.plugin.name} at "
                  f"{seen[key].skill_relpath}",
                  "give each realization of a plugin a different name")
        else:
            seen[key] = r


# -- set E -----------------------------------------------------------------

def _e1(mp: Marketplace, out: List[Finding]) -> None:
    for plugin in mp.plugins.values():
        if plugin.dir is None:
            continue
        rel = mp.rel(plugin.dir / "skills")
        if (plugin.dir / "skills" / "realization-contract").is_dir():
            _block(out, "E1", rel,
                   f"plugin {plugin.name} holds a realization contract; a realization marketplace holds none",
                   "remove skills/realization-contract; the contract belongs to the defining marketplace")
        if not _plugin_realizations(mp, plugin):
            _block(out, "E1", rel, f"plugin {plugin.name} has no realize-* skill",
                   "add a realize-* skill, or remove the plugin")


def _e2(mp: Marketplace, out: List[Finding]) -> None:
    for r in mp.realizations:
        file = r.skill_relpath
        if r.realizes is None:
            if r.realizes_error is not None:
                message = f"the realizes block of {r.dir.name} cannot be read: {r.realizes_error}"
            else:
                message = f"realization {r.dir.name} has no realizes block"
            _block(out, "E2", file, message, "add a realizes block with name, concept and contractVersion")
            continue
        block = r.realizes
        name = block.get("name")
        if not isinstance(name, str) or not name:
            _block(out, "E2", file, f"the realizes block of {r.dir.name} has no name", "add name to the realizes block")
        if _split_ref(block.get("concept")) is None:
            _block(out, "E2", file,
                   f"the realizes concept {block.get('concept')!r} is not <concept>@<marketplace>",
                   "write concept as <concept>@<marketplace>, with both parts present")
        version = block.get("contractVersion")
        if not isinstance(version, str):
            _block(out, "E2", file, f"the realizes block of {r.dir.name} has no contractVersion",
                   "add a contractVersion range, such as ^1.0.0")
        elif not RANGE.match(version):
            _block(out, "E2", file,
                   f"contractVersion {version!r} is not a semantic-version range with no pre-release suffix",
                   "write a range such as ^1.0.0, without a pre-release suffix")
    for plugin in mp.plugins.values():
        skills = [r for r in _plugin_realizations(mp, plugin) if r.realizes is not None]
        concepts = {_block_concept(r) for r in skills}
        if len(concepts) > 1:
            _block(out, "E2", skills[0].skill_relpath,
                   f"skills in plugin {plugin.name} name different concepts: "
                   f"{', '.join(sorted(str(c) for c in concepts))}",
                   "make every realize-* skill of a plugin name one concept")


def _e3(ctx: Context, out: List[Finding]) -> None:
    mp = ctx.marketplace
    for r in mp.realizations:
        if r.realizes is None:
            continue  # E2 reports the missing block
        split = _split_ref(r.realizes.get("concept"))
        if split is None:
            continue  # E2 reports the unqualified concept
        bare, qualifier = split
        fix = ("declare the concept plugin as a dependency on the marketplace entry, with its marketplace "
               "and a version range")
        deps = [d for d in _entry_dependencies(r.plugin.entry, mp.name) if d["marketplace"] == qualifier]
        if not deps:
            _block(out, "E3", r.skill_relpath,
                   f"plugin {r.plugin.name} has no entry dependency on marketplace {qualifier}", fix)
            continue
        upstream = ctx.upstream(qualifier)
        if upstream is None:
            continue  # X-resolve stops the run before this check
        problems = [_defining_problem(upstream, d["name"], bare) for d in deps]
        if any(problem is None for problem in problems):
            continue
        _block(out, "E3", r.skill_relpath, problems[0] or "no dependency defines the concept", fix)


def _e4(mp: Marketplace, out: List[Finding]) -> None:
    first: Dict[Tuple[str, str], Realization] = {}
    for r in mp.realizations:
        concept = _block_concept(r)
        if concept is None:
            continue
        key = (concept, _dir_name(r))
        if key in first:
            _block(out, "E4", r.skill_relpath,
                   f"realization {key[1]} of {key[0]} also appears at {first[key].skill_relpath}",
                   "give one of the two realizations a different name, or remove it")
        else:
            first[key] = r


def _e5(mp: Marketplace, out: List[Finding]) -> None:
    for r in mp.realizations:
        if r.default:
            _block(out, "E5", r.skill_relpath,
                   f"realization {r.dir.name} is marked default: true; a realization marketplace marks no default",
                   "remove default: true; the defining marketplace owns the default")


# -- entry point -----------------------------------------------------------

def run(ctx: Context) -> List[Finding]:
    out: List[Finding] = []
    mp = ctx.marketplace
    if _is_realization_marketplace(mp):
        _e1(mp, out)
        _e2(mp, out)
        _e3(ctx, out)
        _e4(mp, out)
        _e5(mp, out)
        return out
    _a1(mp, out)
    for name in sorted(mp.concepts):
        concept = mp.concepts[name]
        _a2(mp, concept, out)
        _a3(mp, concept, out)
        _a4(mp, concept, out)
        _a5(concept, out)
    for r in mp.realizations:
        _a6(ctx, r, out)
        _a7(r, out)
    _a9(mp, out)
    return out
