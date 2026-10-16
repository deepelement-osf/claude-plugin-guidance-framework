"""Checks F-files, F-agree, F-tier2, F-tier3, F-capability, F-binding, F-compiled,
F-schema, F-selection and F-interaction, run by guidance_check.py.

Standard library only. run(ctx) returns Finding objects. It never edits a file.
Loading problems (unreadable JSON, unreadable front matter, a realizes block
that cannot be parsed) belong to the loader and are not repeated here.

F-files
    A concept with a graph role has skills/realization-contract/graph-contract.json
    and schema.json beside its skill. A capability needs only its skill, unless
    it has realizations, and then it needs the same two files.
F-agree
    The "## Graph participation" section has one bullet per declared field,
    except graphSpecVersion, in declaration order. Each value is written as the
    field reference gives it (see _render_value).
F-tier2
    graph-contract.json has graphSpecVersion, and the keys its role needs:
    outcomes for a phase, entry or refinement; frame for a concept that some
    refinement refines; input for a concept that some entry hands off to;
    result for a refinement or observer.
F-tier3
    Each realize-* skill has a graph: block with graphSpecVersion and runs. A
    command is named only when runs is command, and it must exist beside the
    skill. builds_on names another realization of the same concept. effects
    holds only the known effects.
F-capability
    A capability declares no interaction and no edges, and has no
    "## Graph participation" section.
F-binding
    Each realizes block has a qualified concept, a name and a contractVersion.
    Each handoff target has an input contract. Each capability that a concept
    names in backticks is listed in its uses.
F-compiled
    concept-graph.json is present when the marketplace has concepts, and is
    byte-identical to a fresh compile. A compile error is reported under the
    check id the compiler gives it.
F-schema
    Graph declarations, graph contracts, realization declarations, realizes
    blocks, concept-graph.json and .claude-plugin/guidance.json validate against
    the schemas in spec/schemas. frame, input and result stay inside the JSON
    Schema subset. An unsupported graphSpecVersion is a block here. So is a
    metadata.pluginPrefix left in marketplace.json: it is no longer read, and its
    value moves to pluginPrefix in guidance.json.
F-selection
    A phase or entry does not have selection many. fold appears only with
    selection many, and selection many needs fold.
F-interaction
    A node's interaction is autonomous or pause, or absent. conversational
    warns, because the workspace runtime refuses it until the round trip is
    proven. Any other value blocks.

The schemas are read from spec/schemas beside this repository. When that
directory is not present, the copies embedded at the end of this module are
used. A test keeps the copies equal to the spec when the spec is present.

F-official is not emitted here. guidance_check.py owns it.

Public API
----------
run(ctx) -> list[Finding]
schema_documents() -> dict[str, dict]
    The six schema documents in use, keyed by name.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from gc_compile import CompileError, compile, render
from gc_model import (
    COMPILED_FILE,
    GRAPH_SPEC_VERSION,
    GUIDANCE_FILE,
    ROLES,
    graph_spec_version_problem,
    Concept,
    Context,
    Finding,
    Marketplace,
    realization_in_chain,
)
from gc_parse import _IGNORED_KEYWORDS, _SUBSET_KEYWORDS, load_json, validate_json_schema

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC_SCHEMA_DIR = SCRIPT_DIR.parent.parent.parent / "spec" / "schemas"

_SCHEMA_FILES = {
    "concept-declaration": "concept-declaration.schema.json",
    "graph-contract": "graph-contract.schema.json",
    "realization-declaration": "realization-declaration.schema.json",
    "realizes-block": "realizes-block.schema.json",
    "compiled-graph": "compiled-graph.schema.json",
    "guidance-marketplace": "guidance-marketplace.schema.json",
}
MANIFEST_RELPATH = ".claude-plugin/marketplace.json"

EFFECTS = ("push", "pull-request", "deployment", "external-message")
ALLOWED_INTERACTIONS = ("autonomous", "pause")
ROLES_WITH_OUTCOMES = ("phase", "entry", "refinement")
ROLES_WITH_RESULT = ("refinement", "observer")
REALIZATION_BRANCHES = {"agent": "agentRealization", "command": "commandRealization"}
CONTRACT_KEYS_FROM_SCHEMA = ("frame", "input", "result")

_LOCAL_REF = re.compile(r"#/(\$defs)/([^/]+)\Z")
_BACKTICK_REF = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)*(?:@[a-z0-9]+(?:-[a-z0-9]+)*)?)`")
_BINDING_KEYS = ("concept", "name", "contractVersion")
_BINDING_ERROR = re.compile(
    r"^\$\.(concept|name|contractVersion):|missing required property '(concept|name|contractVersion)'")
_MAX_DEPTH = 64

_schemas: Optional[Dict[str, dict]] = None


def schema_documents() -> Dict[str, dict]:
    """The six schema documents, from spec/schemas when present, else the embedded copies."""
    global _schemas
    if _schemas is None:
        documents: Dict[str, dict] = {}
        for name, filename in _SCHEMA_FILES.items():
            path = SPEC_SCHEMA_DIR / filename
            text = path.read_text(encoding="utf-8") if path.is_file() else _EMBEDDED[name]
            documents[name] = json.loads(text)
        _schemas = documents
    return _schemas


# -- small helpers ---------------------------------------------------------

def _block(out: List[Finding], check: str, file: Optional[str], message: str, fix: str = "") -> None:
    out.append(Finding(check, "block", file, message, fix))


def _warn(out: List[Finding], check: str, file: Optional[str], message: str, fix: str = "") -> None:
    out.append(Finding(check, "warn", file, message, fix))


def _own(ctx: Context) -> List[Concept]:
    return [ctx.marketplace.concepts[name] for name in sorted(ctx.marketplace.concepts)]


def _all_marketplaces(ctx: Context) -> List[Marketplace]:
    found = [ctx.marketplace]
    for name in sorted(ctx.upstreams):
        if name != ctx.marketplace.name:
            found.append(ctx.upstreams[name])
    return found


def _kind(concept: Concept) -> str:
    """'capability' (no graph, or a graph with no role), 'role', or 'malformed'."""
    graph = concept.graph
    if graph is None:
        return "capability"
    if isinstance(graph, dict):
        return "role" if "role" in graph else "capability"
    return "malformed"


def _role(concept: Concept) -> Optional[str]:
    """The concept's role when it is a valid one, else None."""
    if _kind(concept) == "role" and concept.graph.get("role") in ROLES:
        return concept.graph["role"]
    return None


def _uses(concept: Concept) -> List[str]:
    graph = concept.graph
    if isinstance(graph, dict) and isinstance(graph.get("uses"), list):
        return [item for item in graph["uses"] if isinstance(item, str)]
    return []


def _qualified(ref: Any) -> bool:
    if not isinstance(ref, str) or ref.count("@") != 1:
        return False
    name, marketplace = ref.split("@", 1)
    return bool(name) and bool(marketplace)


def _resolve(ctx: Context, ref: str) -> Optional[Concept]:
    """The concept a qualified reference names, when its marketplace is loaded."""
    if not _qualified(ref):
        return None
    name, marketplace_name = ref.split("@", 1)
    if marketplace_name == ctx.marketplace.name:
        marketplace: Optional[Marketplace] = ctx.marketplace
    else:
        marketplace = ctx.upstream(marketplace_name)
    if marketplace is None:
        return None
    return marketplace.concepts.get(name)


def _version_problem(node: dict, where: str) -> Optional[str]:
    """F-schema's reading of graphSpecVersion. An unsupported version raises CannotRun (exit 2)."""
    if "graphSpecVersion" not in node:
        return None
    return graph_spec_version_problem(node["graphSpecVersion"], where)


def _subset_problems(node: Any, where: str, root: dict, depth: int = 0) -> List[str]:
    """Problems that keep a JSON Schema document outside the guidance subset."""
    if depth > _MAX_DEPTH:
        return [f"{where}: schema nesting is too deep; a $ref may be cyclic"]
    if isinstance(node, bool):
        return []
    if not isinstance(node, dict):
        return [f"{where}: a schema must be an object"]
    problems = [f"{where}: keyword {key!r} is outside the guidance JSON Schema subset"
                for key in sorted(set(node) - _SUBSET_KEYWORDS - _IGNORED_KEYWORDS)]
    if "$ref" in node:
        ref = node["$ref"]
        match = _LOCAL_REF.match(ref) if isinstance(ref, str) else None
        if match is None:
            problems.append(f"{where}: $ref {ref!r} is not a local '#/$defs/<name>' reference")
        else:
            section = root.get(match.group(1))
            if not isinstance(section, dict) or match.group(2) not in section:
                problems.append(f"{where}: $ref {ref!r} does not resolve")
    for key in ("properties", "$defs"):
        section = node.get(key)
        if isinstance(section, dict):
            for name, sub in section.items():
                problems += _subset_problems(sub, f"{where}.{key}.{name}", root, depth + 1)
    items = node.get("items")
    if isinstance(items, (dict, bool)):
        problems += _subset_problems(items, f"{where}.items", root, depth + 1)
    elif "items" in node:
        problems.append(f"{where}: 'items' must be one schema")
    extra = node.get("additionalProperties")
    if isinstance(extra, dict):
        problems += _subset_problems(extra, f"{where}.additionalProperties", root, depth + 1)
    branches = node.get("oneOf")
    if isinstance(branches, list):
        for index, branch in enumerate(branches):
            problems += _subset_problems(branch, f"{where}.oneOf[{index}]", root, depth + 1)
    return problems


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _render_value(name: str, value: Any) -> str:
    """The text a participation bullet carries for a declared field.

    edges:     "outcome → to", comma-separated.
    when:      "key=value", comma-separated.
    observes:  "key: value" for its role filter, and any other mapping alike.
    lists:     comma-separated.
    """
    if name == "edges" and isinstance(value, list):
        parts = []
        for edge in value:
            if isinstance(edge, dict):
                parts.append(f"{_scalar(edge.get('outcome'))} → {_scalar(edge.get('to'))}")
            else:
                parts.append(_scalar(edge))
        return ", ".join(parts)
    if isinstance(value, dict):
        if name == "when":
            return ", ".join(f"{key}={_scalar(item)}" for key, item in value.items())
        return ", ".join(f"{key}: {_scalar(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_scalar(item) for item in value)
    return _scalar(value)


def _norm(text: str) -> str:
    return " ".join(text.replace("->", "→").split())


# -- F-files ---------------------------------------------------------------

def _f_files(ctx: Context, out: List[Finding]) -> None:
    mp = ctx.marketplace
    for concept in _own(ctx):
        role = _role(concept)
        needs_contract = role is not None or (_kind(concept) == "capability" and bool(concept.realizations))
        if not needs_contract or concept.plugin.dir is None:
            continue
        contract_dir = concept.plugin.dir / "skills" / "realization-contract"
        why = f"the role {role}" if role else "its realizations"
        for filename in ("graph-contract.json", "schema.json"):
            path = contract_dir / filename
            if not path.is_file():
                _block(out, "F-files", mp.rel(path),
                       f"{concept.id} needs {filename} for {why}",
                       f"add skills/realization-contract/{filename} beside the concept skill")


# -- F-agree ---------------------------------------------------------------

def _f_agree(ctx: Context, out: List[Finding]) -> None:
    for concept in _own(ctx):
        if _role(concept) is None:
            continue
        file = concept.skill_relpath
        bullets = concept.participation_bullets
        if bullets is None:
            _block(out, "F-agree", file, f"{concept.id} has no '## Graph participation' section",
                   "add the section, with one bullet for each declared field")
            continue
        graph = concept.graph
        expected = [key for key in graph if key != "graphSpecVersion"]
        actual = [name for name, _ in bullets]
        missing = [key for key in expected if key not in actual]
        extra = [name for name in actual if name not in expected]
        if missing or extra:
            _block(out, "F-agree", file,
                   f"participation bullets differ from the declaration: missing {missing}, extra {extra}",
                   "make the bullets match the graph: frontmatter, one per field")
        elif actual != expected:
            _block(out, "F-agree", file, "participation bullets are not in declaration order",
                   "reorder the bullets to match the graph: frontmatter")
        for name, text in bullets:
            if name not in expected:
                continue
            want = _render_value(name, graph[name])
            if _norm(text) != _norm(want):
                _block(out, "F-agree", file,
                       f"bullet {name} reads {text!r} but the frontmatter gives {want!r}",
                       f"write the bullet as '- **{name}:** {want}'")


# -- F-tier2 ---------------------------------------------------------------

def _targets(ctx: Context) -> Tuple[Set[str], Set[str]]:
    """Qualified concept ids that some refinement refines, and that some entry hands off to."""
    refined: Set[str] = set()
    handed: Set[str] = set()
    for mp in _all_marketplaces(ctx):
        for concept in mp.concepts.values():
            graph = concept.graph
            if not isinstance(graph, dict):
                continue
            if graph.get("role") == "refinement" and isinstance(graph.get("refines"), str):
                refined.add(graph["refines"])
            if graph.get("role") == "entry" and isinstance(graph.get("handoff"), str):
                handed.add(graph["handoff"])
    return refined, handed


def _f_tier2(ctx: Context, out: List[Finding]) -> None:
    refined, handed = _targets(ctx)
    for concept in _own(ctx):
        role = _role(concept)
        contract = concept.contract
        if role is None or not isinstance(contract, dict):
            continue
        file = concept.contract_relpath
        required: List[Tuple[str, str]] = [("graphSpecVersion", "every contract has it")]
        if role in ROLES_WITH_OUTCOMES:
            required.append(("outcomes", "the conclude step produces outcomes"))
        if concept.id in refined:
            required.append(("frame", "a refinement refines this concept"))
        if concept.id in handed:
            required.append(("input", "an entry hands off to this concept"))
        if role in ROLES_WITH_RESULT:
            required.append(("result", f"a {role} returns a result"))
        for key, reason in required:
            if key not in contract:
                _block(out, "F-tier2", file,
                       f"graph-contract.json has no {key!r}; the role {role} needs it, because {reason}",
                       f"add {key} to graph-contract.json")


# -- F-tier3 ---------------------------------------------------------------

def _f_tier3(ctx: Context, out: List[Finding]) -> None:
    mp = ctx.marketplace
    for realization in mp.realizations:
        file = realization.skill_relpath
        graph = realization.graph
        if not isinstance(graph, dict):
            _block(out, "F-tier3", file, f"realization {realization.name} has no graph: block",
                   "add a graph: block with graphSpecVersion and runs to the front matter")
            continue
        if "graphSpecVersion" not in graph:
            _block(out, "F-tier3", file, "the graph: block has no graphSpecVersion",
                   "add graphSpecVersion: \"1.0\"")
        runs = graph.get("runs")
        if runs not in ("agent", "command"):
            _block(out, "F-tier3", file, f"runs is {runs!r}; it must be agent or command",
                   "set runs to agent or command")
        if runs == "command":
            command = graph.get("command")
            if not isinstance(command, str) or not command:
                _block(out, "F-tier3", file, "runs is command, but no command is named",
                       "name the command file, relative to the skill directory")
            elif not (realization.dir / command).is_file():
                _block(out, "F-tier3", file,
                       f"command {command!r} does not exist relative to the skill directory",
                       "create the file or correct the command path")
        elif "command" in graph:
            _block(out, "F-tier3", file, "command appears only when runs is command",
                   "remove the command key, or set runs to command")
        if "builds_on" in graph:
            target = graph["builds_on"]
            if not isinstance(target, str) or not realization_in_chain(
                    target, realization.concept_ref, mp, ctx.upstreams, exclude=realization):
                _block(out, "F-tier3", file,
                       f"builds_on {target!r} does not name another realization of the same concept "
                       "in this marketplace or an upstream it reaches",
                       "name a realization of this concept that this marketplace or an upstream provides, "
                       "or remove builds_on")
        if "effects" in graph:
            effects = graph["effects"]
            if not isinstance(effects, list) or any(item not in EFFECTS for item in effects):
                _block(out, "F-tier3", file,
                       f"effects holds {effects!r}; it may hold only {', '.join(EFFECTS)}, or be empty",
                       "keep only the known effects")


# -- F-capability ----------------------------------------------------------

def _f_capability(ctx: Context, out: List[Finding]) -> None:
    for concept in _own(ctx):
        if _kind(concept) != "capability":
            continue
        file = concept.skill_relpath
        graph = concept.graph
        if isinstance(graph, dict):
            for key in ("interaction", "edges"):
                if key in graph:
                    _block(out, "F-capability", file,
                           f"capability {concept.id} declares {key}; a capability has no role, "
                           "interaction or edges",
                           f"remove the {key} key from its graph: block")
        if concept.participation_bullets is not None:
            _block(out, "F-capability", file,
                   f"capability {concept.id} has a '## Graph participation' section; it has no role",
                   "remove the section")


# -- F-binding -------------------------------------------------------------

def _f_binding(ctx: Context, out: List[Finding]) -> None:
    mp = ctx.marketplace
    for realization in mp.realizations:
        block = realization.realizes
        if block is None:
            continue
        for part in _BINDING_KEYS:
            value = block.get(part)
            if not isinstance(value, str) or not value:
                _block(out, "F-binding", realization.skill_relpath,
                       f"the realizes block has no {part}",
                       f"add {part} to the realizes block")
        concept_ref = block.get("concept")
        if isinstance(concept_ref, str) and concept_ref and not _qualified(concept_ref):
            _block(out, "F-binding", realization.skill_relpath,
                   f"realizes concept {concept_ref!r} is not qualified",
                   "write it as <concept>@<marketplace>")

    capabilities = {concept.id for other in _all_marketplaces(ctx)
                    for concept in other.concepts.values() if _kind(concept) == "capability"}
    for concept in _own(ctx):
        graph = concept.graph
        if isinstance(graph, dict) and isinstance(graph.get("handoff"), str):
            target = _resolve(ctx, graph["handoff"])
            if target is not None and not (isinstance(target.contract, dict) and "input" in target.contract):
                _block(out, "F-binding", concept.skill_relpath,
                       f"handoff target {graph['handoff']} has no input contract",
                       "add input to the target's graph-contract.json")
        uses = _uses(concept)
        seen: Set[str] = set()
        for token in _BACKTICK_REF.findall(concept.skill.body):
            ref = token if "@" in token else f"{token}@{ctx.marketplace.name}"
            if ref == concept.id or ref not in capabilities or ref in seen:
                continue
            seen.add(ref)
            if ref not in uses:
                _block(out, "F-binding", concept.skill_relpath,
                       f"{concept.id} names the capability `{token}` but does not list {ref} in uses",
                       f"add {ref} to uses in the graph: block")


# -- F-compiled ------------------------------------------------------------

def _f_compiled(ctx: Context, out: List[Finding]) -> None:
    mp = ctx.marketplace
    exists = mp.compiled_path.is_file()
    if not exists and mp.concepts:
        _block(out, "F-compiled", COMPILED_FILE, "concept-graph.json is missing at the marketplace root",
               "run guidance_check.py --compile")
    if not exists and not mp.concepts:
        return
    try:
        fresh = render(compile(mp, ctx.upstreams)).encode("utf-8")
    except CompileError as exc:
        _block(out, exc.check, COMPILED_FILE, exc.message,
               "fix the marketplace source so that it compiles; the message names the cause")
        return
    if not exists:
        return
    try:
        committed = mp.compiled_path.read_bytes()
    except OSError:
        return
    if committed != fresh:
        _block(out, "F-compiled", COMPILED_FILE,
               "concept-graph.json is stale: it is not byte-identical to a fresh compile",
               "run guidance_check.py --compile")


# -- F-schema --------------------------------------------------------------

def _schema_declaration(concept: Concept, docs: Dict[str, dict], out: List[Finding]) -> None:
    graph = concept.graph
    if graph is None:
        return
    file = concept.skill_relpath
    if not isinstance(graph, dict):
        _block(out, "F-schema", file, f"{concept.id} has a graph: value that is not a mapping",
               "write graph: as a mapping of declaration fields")
        return
    problem = _version_problem(graph, file)
    if problem:
        _block(out, "F-schema", file, problem, "set graphSpecVersion to \"1.0\"")
        return
    if "role" not in graph:
        branch = "capability"
    elif graph["role"] in ROLES:
        branch = graph["role"]
    else:
        _block(out, "F-schema", file, f"role {graph['role']!r} is not one of {', '.join(ROLES)}",
               "use one of the four roles, or remove the role for a capability")
        return
    for error in validate_json_schema(graph, {"$ref": f"#/$defs/{branch}"}, docs["concept-declaration"]):
        _block(out, "F-schema", file, error, "correct the graph: frontmatter to the declaration schema")


def _schema_contract(concept: Concept, docs: Dict[str, dict], out: List[Finding]) -> None:
    contract = concept.contract
    if not isinstance(contract, dict):
        return
    file = concept.contract_relpath
    problem = _version_problem(contract, file)
    if problem:
        _block(out, "F-schema", file, problem, "set graphSpecVersion to \"1.0\"")
        return
    branch = "selectionMany" if contract.get("selection") == "many" else "selectionOne"
    for error in validate_json_schema(contract, {"$ref": f"#/$defs/{branch}"}, docs["graph-contract"]):
        _block(out, "F-schema", file, error, "correct graph-contract.json to the contract schema")
    for key in CONTRACT_KEYS_FROM_SCHEMA:
        if key not in contract:
            continue
        document = contract[key]
        root = document if isinstance(document, dict) else {}
        for problem in _subset_problems(document, key, root):
            _block(out, "F-schema", file, problem, "use only the guidance JSON Schema subset")


def _schema_realization(realization, docs: Dict[str, dict], out: List[Finding]) -> None:
    file = realization.skill_relpath
    graph = realization.graph
    if isinstance(graph, dict):
        problem = _version_problem(graph, file)
        if problem:
            _block(out, "F-schema", file, problem, "set graphSpecVersion to \"1.0\"")
        else:
            runs = graph.get("runs")
            branch = REALIZATION_BRANCHES.get(runs) if isinstance(runs, str) else None
            schema = {"$ref": f"#/$defs/{branch}"} if branch else docs["realization-declaration"]
            for error in validate_json_schema(graph, schema, docs["realization-declaration"]):
                _block(out, "F-schema", file, error, "correct the realization's graph: frontmatter")
    if realization.realizes is not None:
        for error in validate_json_schema(realization.realizes, docs["realizes-block"], docs["realizes-block"]):
            if _BINDING_ERROR.search(error):
                continue
            _block(out, "F-schema", file, error, "correct the realizes block to the realizes-block schema")


def _guidance_file(mp: Marketplace, docs: Dict[str, dict], out: List[Finding]) -> None:
    """guidance.json, when present, is valid JSON that the guidance marketplace schema accepts.

    The loader reads it only when it is valid, and falls back to the default prefix otherwise,
    so the problems are reported here and nowhere else.
    """
    path = mp.root / GUIDANCE_FILE
    if path.is_file():
        try:
            value = load_json(path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            _block(out, "F-schema", GUIDANCE_FILE, f"file is not valid JSON: {exc}",
                   f"fix the JSON syntax of {GUIDANCE_FILE}, or remove the file")
            return
        for error in validate_json_schema(value, docs["guidance-marketplace"], docs["guidance-marketplace"]):
            _block(out, "F-schema", GUIDANCE_FILE, error,
                   f"fix the value in {GUIDANCE_FILE} to match spec/schemas/guidance-marketplace.schema.json")
    metadata = mp.manifest.get("metadata")
    if isinstance(metadata, dict) and "pluginPrefix" in metadata:
        _block(out, "F-schema", MANIFEST_RELPATH,
               "metadata.pluginPrefix is not read: Claude Code reports it as an unknown field, and "
               "claude plugin validate --strict fails on it",
               f"move the value to pluginPrefix in {GUIDANCE_FILE}, and remove metadata.pluginPrefix")


def _f_schema(ctx: Context, out: List[Finding]) -> None:
    docs = schema_documents()
    mp = ctx.marketplace
    _guidance_file(mp, docs, out)
    for concept in _own(ctx):
        _schema_declaration(concept, docs, out)
        _schema_contract(concept, docs, out)
    for realization in mp.realizations:
        _schema_realization(realization, docs, out)
    if isinstance(mp.compiled, dict):
        problem = _version_problem(mp.compiled, COMPILED_FILE)
        if problem:
            _block(out, "F-schema", COMPILED_FILE, problem, "recompile with guidance_check.py --compile")
            return
        for error in validate_json_schema(mp.compiled, docs["compiled-graph"], docs["compiled-graph"]):
            _block(out, "F-schema", COMPILED_FILE, error, "recompile with guidance_check.py --compile")


# -- F-selection -----------------------------------------------------------

def _f_selection(ctx: Context, out: List[Finding]) -> None:
    for concept in _own(ctx):
        contract = concept.contract
        if not isinstance(contract, dict):
            continue
        file = concept.contract_relpath
        role = _role(concept)
        selection = contract.get("selection", "one")
        if role in ("phase", "entry") and selection == "many":
            _block(out, "F-selection", file,
                   f"the role {role} has selection many; a {role} must have selection one, or none",
                   "set selection to one, or remove it")
        if "fold" in contract and selection != "many":
            _block(out, "F-selection", file, "fold appears only with selection many",
                   "remove fold, or set selection to many")
        if selection == "many" and "fold" not in contract:
            _block(out, "F-selection", file, "selection many needs a fold",
                   "add fold: all, collect or worst-outcome")


# -- F-interaction ---------------------------------------------------------

def _f_interaction(ctx: Context, out: List[Finding]) -> None:
    for concept in _own(ctx):
        graph = concept.graph
        if _role(concept) is None or "interaction" not in graph:
            continue
        value = graph["interaction"]
        file = concept.skill_relpath
        if value == "conversational":
            _warn(out, "F-interaction", file,
                  f"{concept.id} declares interaction conversational; the workspace runtime refuses it "
                  "until the round trip is proven",
                  "use autonomous or pause until the round trip is proven")
        elif value not in ALLOWED_INTERACTIONS:
            _block(out, "F-interaction", file, f"interaction is {value!r}; it must be autonomous, pause or absent",
                   "use autonomous or pause, or remove the key")


# -- entry point -----------------------------------------------------------

def guidance_findings(mp: Marketplace) -> List[Finding]:
    """The F-schema blocks for guidance.json and metadata.pluginPrefix. compile calls this too,
    because compile runs no checks, and the loader falls back to the default prefix silently."""
    out: List[Finding] = []
    _guidance_file(mp, schema_documents(), out)
    return out


def run(ctx: Context) -> List[Finding]:
    out: List[Finding] = []
    _f_files(ctx, out)
    _f_agree(ctx, out)
    _f_tier2(ctx, out)
    _f_tier3(ctx, out)
    _f_capability(ctx, out)
    _f_binding(ctx, out)
    _f_compiled(ctx, out)
    _f_schema(ctx, out)
    _f_selection(ctx, out)
    _f_interaction(ctx, out)
    return out


# Copies of spec/schemas/*.schema.json, used only when the spec directory is absent beside this
# script. tests/test_gc_checks_f.py keeps them equal to the spec when the spec is present.
_EMBEDDED = {
    "concept-declaration": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Concept declaration (the graph: frontmatter of a Tier 1 concept skill)",
  "description": "The value of the single top-level graph: key in the YAML frontmatter of skills/concept/SKILL.md, as parsed to JSON. The key is present on every graph participant, and on a capability only when the capability declares graph fields. Exactly one branch of oneOf matches a valid declaration. The branch is chosen by role: phase, entry, refinement, observer, or no role at all for a capability. Each branch sets additionalProperties to false, so a field that does not apply to the role is rejected. Each branch requires graphSpecVersion. The schema does not check rules that need more than one document or a repository check, such as: each reference resolving, a refines target having a role the parent accepts, an after: cycle, the lifecycle of a deprecated concept, selection one for a phase or entry contract, a hand-off target having an input contract, or the match between this block and the Graph participation section. The compliance script checks those. References are qualified as <concept>@<marketplace>, except that when.node may use the bare concept name. The qualifier workspace is reserved for a consuming workspace's own concepts.",
  "oneOf": [
    { "$ref": "#/$defs/phase" },
    { "$ref": "#/$defs/entry" },
    { "$ref": "#/$defs/refinement" },
    { "$ref": "#/$defs/observer" },
    { "$ref": "#/$defs/capability" }
  ],
  "$defs": {
    "graphSpecVersion": {
      "const": "1.0",
      "description": "The graph spec version this declaration is written to. Required whenever the graph: key is present."
    },
    "role": {
      "enum": ["phase", "entry", "refinement", "observer"]
    },
    "interaction": {
      "enum": ["autonomous", "pause", "conversational"],
      "description": "Nodes only. Omitted means autonomous. Conversational is refused by the compliance script until the round trip is proven."
    },
    "name": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "A bare concept name, or a bare alias, as used in aliases:."
    },
    "qualifiedRef": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*@[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "A concept reference, <concept>@<marketplace>. The marketplace segment may be workspace for a consuming workspace's own concept."
    },
    "nodeRef": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*(@[a-z0-9]+(-[a-z0-9]+)*)?$",
      "description": "The node named in a when: run fact. It may be the bare concept name or a qualified reference."
    },
    "outcome": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "An outcome name, such as passed or failed."
    },
    "edge": {
      "type": "object",
      "description": "One outcome of a phase or entry, and the node the run goes to next. A terminal node omits edges.",
      "properties": {
        "outcome": { "$ref": "#/$defs/outcome" },
        "to": { "$ref": "#/$defs/qualifiedRef" }
      },
      "required": ["outcome", "to"],
      "additionalProperties": false
    },
    "edges": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/edge" }
    },
    "uses": {
      "type": "array",
      "description": "Qualified references to any concept, including a capability, used by name.",
      "items": { "$ref": "#/$defs/qualifiedRef" }
    },
    "aliases": {
      "type": "array",
      "description": "Former names that still resolve, with a warning.",
      "items": { "$ref": "#/$defs/name" }
    },
    "after": {
      "type": "array",
      "description": "Refinements and observers only. Qualified references to nodes this one orders after. A cycle is an error.",
      "items": { "$ref": "#/$defs/qualifiedRef" }
    },
    "optional": {
      "type": "boolean",
      "description": "Refinements and observers only. Default false. A workspace may switch an optional one off."
    },
    "when": {
      "type": "object",
      "description": "Refinements and observers only. Every key must hold. The keys node, path_exists and setting are reserved. Any other key is a call parameter, such as environment. Those keys are open by design, so additionalProperties is a value schema here instead of false. The compliance script checks the key names.",
      "properties": {
        "node": { "$ref": "#/$defs/nodeRef" },
        "path_exists": {
          "type": "string",
          "description": "A path relative to the repository root."
        },
        "setting": {
          "type": "string",
          "description": "A workspace setting key."
        }
      },
      "additionalProperties": { "type": "string" }
    },
    "observes": {
      "description": "Observers only. A phase or entry, all for every node in scope, or a role filter.",
      "oneOf": [
        { "type": "string", "const": "all" },
        { "$ref": "#/$defs/qualifiedRef" },
        {
          "type": "object",
          "properties": {
            "role": { "enum": ["phase", "entry", "refinement"] }
          },
          "required": ["role"],
          "additionalProperties": false
        }
      ]
    },
    "on": {
      "description": "Observers only. Either concluded, or a list of outcomes that the observer fires on.",
      "oneOf": [
        { "type": "string", "const": "concluded" },
        {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/outcome" }
        }
      ]
    },
    "phase": {
      "type": "object",
      "description": "A phase: a node that runs frame, support and conclude. It may have edges.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "role": { "const": "phase" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "edges": { "$ref": "#/$defs/edges" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": {
          "type": "string",
          "description": "The reason. Lifecycle is set by the owning marketplace only."
        },
        "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
        "aliases": { "$ref": "#/$defs/aliases" }
      },
      "required": ["graphSpecVersion", "role"],
      "additionalProperties": false
    },
    "entry": {
      "type": "object",
      "description": "An entry: a phase that starts its own chain. Its last node may hand off, so it may declare handoff:. Otherwise it is the same as a phase.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "role": { "const": "entry" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "edges": { "$ref": "#/$defs/edges" },
        "handoff": { "$ref": "#/$defs/qualifiedRef" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": {
          "type": "string",
          "description": "The reason. Lifecycle is set by the owning marketplace only."
        },
        "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
        "aliases": { "$ref": "#/$defs/aliases" }
      },
      "required": ["graphSpecVersion", "role"],
      "additionalProperties": false
    },
    "refinement": {
      "type": "object",
      "description": "A refinement: a node that adds domain obligations to one parent. It has exactly one refines: target. It may have after, optional and when.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "role": { "const": "refinement" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "refines": { "$ref": "#/$defs/qualifiedRef" },
        "after": { "$ref": "#/$defs/after" },
        "optional": { "$ref": "#/$defs/optional" },
        "when": { "$ref": "#/$defs/when" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": {
          "type": "string",
          "description": "The reason. Lifecycle is set by the owning marketplace only."
        },
        "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
        "aliases": { "$ref": "#/$defs/aliases" }
      },
      "required": ["graphSpecVersion", "role", "refines"],
      "additionalProperties": false
    },
    "observer": {
      "type": "object",
      "description": "An observer: a node that runs after another node concludes and cannot change its outcome. It declares what it observes and the outcomes it fires on.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "role": { "const": "observer" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "observes": { "$ref": "#/$defs/observes" },
        "on": { "$ref": "#/$defs/on" },
        "after": { "$ref": "#/$defs/after" },
        "optional": { "$ref": "#/$defs/optional" },
        "when": { "$ref": "#/$defs/when" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": {
          "type": "string",
          "description": "The reason. Lifecycle is set by the owning marketplace only."
        },
        "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
        "aliases": { "$ref": "#/$defs/aliases" }
      },
      "required": ["graphSpecVersion", "role", "observes", "on"],
      "additionalProperties": false
    },
    "capability": {
      "type": "object",
      "description": "A capability: a concept with no role. It is not in the graph. It is used by name, and it may have no contract. It has no interaction, edges, refines, observes or on. A role key here is rejected by additionalProperties.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": {
          "type": "string",
          "description": "The reason. Lifecycle is set by the owning marketplace only."
        },
        "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
        "aliases": { "$ref": "#/$defs/aliases" }
      },
      "required": ["graphSpecVersion"],
      "additionalProperties": false
    }
  }
}
''',
    "graph-contract": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Graph contract (skills/realization-contract/graph-contract.json)",
  "description": "The Tier 2 graph contract of a concept, in its own file beside schema.json. contractVersion is not in this file. It stays only in schema.json, its one source. Each concept with a role has one. A capability may have one or may be concept-only. The fold key is required if and only if selection is many, and the oneOf below enforces that. The schema cannot check the rules that depend on the concept's role or on the rest of the graph, such as: outcomes being required for phase, entry and refinement; frame being required when the concept accepts refinements; input being required when it accepts hand-offs; result being required for refinement and observer; a phase or entry being selection one; or an output validating against a target's input. The compliance script checks those. The frame, input and result values are JSON Schema documents, and they are checked against the subset in spec/README.md. They are typed only as objects here, so their own keys are not closed by this schema.",
  "oneOf": [
    { "$ref": "#/$defs/selectionOne" },
    { "$ref": "#/$defs/selectionMany" }
  ],
  "$defs": {
    "graphSpecVersion": {
      "const": "1.0"
    },
    "outcome": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"
    },
    "outcomes": {
      "type": "array",
      "description": "Phase, entry and refinement only. The outcomes the conclude step can produce.",
      "minItems": 1,
      "items": { "$ref": "#/$defs/outcome" }
    },
    "jsonSchemaDocument": {
      "type": "object",
      "description": "A JSON Schema document in the guidance subset. Only its top level is typed here."
    },
    "selectionOne": {
      "type": "object",
      "description": "selection one, the default. fold is not allowed.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "selection": { "const": "one" },
        "outcomes": { "$ref": "#/$defs/outcomes" },
        "frame": { "$ref": "#/$defs/jsonSchemaDocument" },
        "input": { "$ref": "#/$defs/jsonSchemaDocument" },
        "result": { "$ref": "#/$defs/jsonSchemaDocument" }
      },
      "required": ["graphSpecVersion"],
      "additionalProperties": false
    },
    "selectionMany": {
      "type": "object",
      "description": "selection many. fold is required. A phase or entry may not be many, which the compliance script checks.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "selection": { "const": "many" },
        "fold": {
          "enum": ["all", "collect", "worst-outcome"]
        },
        "outcomes": { "$ref": "#/$defs/outcomes" },
        "frame": { "$ref": "#/$defs/jsonSchemaDocument" },
        "input": { "$ref": "#/$defs/jsonSchemaDocument" },
        "result": { "$ref": "#/$defs/jsonSchemaDocument" }
      },
      "required": ["graphSpecVersion", "selection", "fold"],
      "additionalProperties": false
    }
  }
}
''',
    "realization-declaration": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Realization declaration (the graph: frontmatter of a realize-* skill)",
  "description": "The value of the graph: key in the YAML frontmatter of a skills/realize-*/SKILL.md file, as parsed to JSON. runs selects how the realization is run. command is required if and only if runs is command, and the oneOf below enforces that. The command path is relative to the realization's own skill directory. builds_on names another realization of the same concept, and the compliance script checks that it exists and is visible. effects lists the effects outside the repository that the realization has, and it defaults to an empty list. The schema cannot check whether a command file exists, whether builds_on resolves, or whether the effects match what the skill does. The compliance script checks those.",
  "oneOf": [
    { "$ref": "#/$defs/agentRealization" },
    { "$ref": "#/$defs/commandRealization" }
  ],
  "$defs": {
    "graphSpecVersion": {
      "const": "1.0"
    },
    "effects": {
      "type": "array",
      "description": "Effects outside the repository. Default is an empty list. Rewind cannot undo these.",
      "items": {
        "enum": ["push", "pull-request", "deployment", "external-message"]
      }
    },
    "builds_on": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "Optional. The name of another realization of the same concept, which the layer loads first."
    },
    "agentRealization": {
      "type": "object",
      "description": "runs agent. The realization is run by a session. No command key is allowed.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "runs": { "const": "agent" },
        "builds_on": { "$ref": "#/$defs/builds_on" },
        "effects": { "$ref": "#/$defs/effects" }
      },
      "required": ["graphSpecVersion", "runs"],
      "additionalProperties": false
    },
    "commandRealization": {
      "type": "object",
      "description": "runs command. The realization runs the command at the given path, and that command is required.",
      "properties": {
        "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
        "runs": { "const": "command" },
        "command": {
          "type": "string",
          "pattern": "^[^/].*$",
          "description": "A path relative to the realization's skill directory. It must not start with a slash."
        },
        "builds_on": { "$ref": "#/$defs/builds_on" },
        "effects": { "$ref": "#/$defs/effects" }
      },
      "required": ["graphSpecVersion", "runs", "command"],
      "additionalProperties": false
    }
  }
}
''',
    "realizes-block": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Realizes block (the realizes fenced block of a realization of an inherited concept)",
  "description": "The parsed value of the realizes block in a realization that realizes a concept defined by an upstream marketplace. All three keys are required. concept is the qualified concept reference. name is the realization's name, and it is required. contractVersion is the range of the Tier 2 contract that the realization satisfies. The schema checks the shape of the range but not its meaning. The compliance script checks that the range is satisfied by the contract it targets, and that the realization is never marked as the default for an inherited concept.",
  "type": "object",
  "properties": {
    "concept": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*@[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "The qualified concept reference, <concept>@<marketplace>."
    },
    "name": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "The realization's name. It must be unique among the realizations of the concept."
    },
    "contractVersion": {
      "type": "string",
      "pattern": "^[~^<>=|0-9.xX* -]+$",
      "description": "A version range, such as ^1.1.0."
    }
  },
  "required": ["concept", "name", "contractVersion"],
  "additionalProperties": false
}
''',
    "compiled-graph": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Compiled graph (concept-graph.json at a marketplace repository root)",
  "description": "The file written by the compliance script with --compile, and nothing else. It is the marketplace's graph composed with the graphs of its direct upstreams, as authored against the recorded versions. Nodes are sorted by id, capabilities by id, realizations by name, and upstreams by marketplace. The file has no timestamps, so the same inputs always write the same bytes. graphHash is the sha256 of the canonical JSON of the whole object without graphHash, and each upstream records the graphHash of its own compiled graph. This schema checks the shape of the file. The compliance script checks that the file is current, that the hashes match, that the versions satisfy their ranges, and that the file equals a fresh compile. The nodes are split by role, and the oneOf in nodes picks the branch for each one. The capability items have no role and no interaction. The contract key holds the graph contract without graphSpecVersion. The script checks the role-dependent rules that the shape cannot hold, such as the order of refinements and the depth limit.",
  "type": "object",
  "properties": {
    "graphSpecVersion": { "$ref": "#/$defs/graphSpecVersion" },
    "marketplace": { "$ref": "#/$defs/name" },
    "upstreams": {
      "type": "array",
      "description": "Each direct upstream marketplace, sorted by marketplace. Empty when the marketplace has no upstreams.",
      "items": { "$ref": "#/$defs/upstream" }
    },
    "nodes": {
      "type": "array",
      "items": {
        "oneOf": [
          { "$ref": "#/$defs/phaseNode" },
          { "$ref": "#/$defs/entryNode" },
          { "$ref": "#/$defs/refinementNode" },
          { "$ref": "#/$defs/observerNode" }
        ]
      }
    },
    "capabilities": {
      "type": "array",
      "items": { "$ref": "#/$defs/capabilityNode" }
    },
    "graphHash": { "$ref": "#/$defs/sha256" }
  },
  "required": ["graphSpecVersion", "marketplace", "upstreams", "nodes", "capabilities", "graphHash"],
  "additionalProperties": false,
  "$defs": {
    "graphSpecVersion": {
      "const": "1.0"
    },
    "name": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"
    },
    "qualifiedRef": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*@[a-z0-9]+(-[a-z0-9]+)*$"
    },
    "nodeRef": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*(@[a-z0-9]+(-[a-z0-9]+)*)?$"
    },
    "outcome": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"
    },
    "version": {
      "type": "string",
      "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?(\\+[0-9A-Za-z.-]+)?$",
      "description": "A semantic version."
    },
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "interaction": {
      "enum": ["autonomous", "pause", "conversational"]
    },
    "edge": {
      "type": "object",
      "properties": {
        "outcome": { "$ref": "#/$defs/outcome" },
        "to": { "$ref": "#/$defs/qualifiedRef" }
      },
      "required": ["outcome", "to"],
      "additionalProperties": false
    },
    "edges": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/edge" }
    },
    "uses": {
      "type": "array",
      "items": { "$ref": "#/$defs/qualifiedRef" }
    },
    "aliases": {
      "type": "array",
      "items": { "$ref": "#/$defs/name" }
    },
    "after": {
      "type": "array",
      "items": { "$ref": "#/$defs/qualifiedRef" }
    },
    "optional": {
      "type": "boolean"
    },
    "when": {
      "type": "object",
      "description": "Call parameter keys are open by design, so additionalProperties is a value schema here instead of false. The keys node, path_exists and setting are reserved.",
      "properties": {
        "node": { "$ref": "#/$defs/nodeRef" },
        "path_exists": { "type": "string" },
        "setting": { "type": "string" }
      },
      "additionalProperties": { "type": "string" }
    },
    "observes": {
      "oneOf": [
        { "type": "string", "const": "all" },
        { "$ref": "#/$defs/qualifiedRef" },
        {
          "type": "object",
          "properties": {
            "role": { "enum": ["phase", "entry", "refinement"] }
          },
          "required": ["role"],
          "additionalProperties": false
        }
      ]
    },
    "on": {
      "oneOf": [
        { "type": "string", "const": "concluded" },
        {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/outcome" }
        }
      ]
    },
    "deprecated": {
      "type": "string"
    },
    "replaced_by": { "$ref": "#/$defs/qualifiedRef" },
    "jsonSchemaDocument": {
      "type": "object",
      "description": "A JSON Schema document in the guidance subset. Only its top level is typed here."
    },
    "contract": {
      "description": "The graph contract of the concept, without graphSpecVersion. It has the same rules as skills/realization-contract/graph-contract.json.",
      "oneOf": [
        {
          "type": "object",
          "properties": {
            "selection": { "const": "one" },
            "outcomes": { "type": "array", "minItems": 1, "items": { "$ref": "#/$defs/outcome" } },
            "frame": { "$ref": "#/$defs/jsonSchemaDocument" },
            "input": { "$ref": "#/$defs/jsonSchemaDocument" },
            "result": { "$ref": "#/$defs/jsonSchemaDocument" }
          },
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "selection": { "const": "many" },
            "fold": { "enum": ["all", "collect", "worst-outcome"] },
            "outcomes": { "type": "array", "minItems": 1, "items": { "$ref": "#/$defs/outcome" } },
            "frame": { "$ref": "#/$defs/jsonSchemaDocument" },
            "input": { "$ref": "#/$defs/jsonSchemaDocument" },
            "result": { "$ref": "#/$defs/jsonSchemaDocument" }
          },
          "required": ["selection", "fold"],
          "additionalProperties": false
        }
      ]
    },
    "realizes": {
      "description": "null for a realization of a concept this marketplace defines. The realizes block otherwise.",
      "oneOf": [
        { "type": "null" },
        { "$ref": "#/$defs/realizesBlock" }
      ]
    },
    "realizesBlock": {
      "type": "object",
      "properties": {
        "concept": { "$ref": "#/$defs/qualifiedRef" },
        "name": { "$ref": "#/$defs/name" },
        "contractVersion": {
          "type": "string",
          "pattern": "^[~^<>=|0-9.xX* -]+$"
        }
      },
      "required": ["concept", "name", "contractVersion"],
      "additionalProperties": false
    },
    "realization": {
      "type": "object",
      "description": "One realization of a concept or capability, as the compiled graph records it.",
      "properties": {
        "name": { "$ref": "#/$defs/name" },
        "runs": { "enum": ["agent", "command"] },
        "builds_on": {
          "description": "The name of the realization this one layers on, or null.",
          "oneOf": [
            { "$ref": "#/$defs/name" },
            { "type": "null" }
          ]
        },
        "effects": {
          "type": "array",
          "items": {
            "enum": ["push", "pull-request", "deployment", "external-message"]
          }
        },
        "default": { "type": "boolean" },
        "realizes": { "$ref": "#/$defs/realizes" }
      },
      "required": ["name", "runs", "builds_on", "effects", "default", "realizes"],
      "additionalProperties": false
    },
    "upstream": {
      "type": "object",
      "properties": {
        "marketplace": { "$ref": "#/$defs/name" },
        "plugins": {
          "type": "object",
          "description": "Plugin name to the version the upstream was authored against. The keys are plugin names, so additionalProperties is a value schema here instead of false.",
          "additionalProperties": { "$ref": "#/$defs/version" }
        },
        "graphHash": { "$ref": "#/$defs/sha256" }
      },
      "required": ["marketplace", "plugins", "graphHash"],
      "additionalProperties": false
    },
    "phaseNode": {
      "type": "object",
      "description": "A phase node. It may declare edges.",
      "properties": {
        "id": { "$ref": "#/$defs/qualifiedRef" },
        "plugin": { "$ref": "#/$defs/name" },
        "version": { "$ref": "#/$defs/version" },
        "role": { "const": "phase" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "edges": { "$ref": "#/$defs/edges" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": { "$ref": "#/$defs/deprecated" },
        "replaced_by": { "$ref": "#/$defs/replaced_by" },
        "aliases": { "$ref": "#/$defs/aliases" },
        "contract": { "$ref": "#/$defs/contract" },
        "realizations": {
          "type": "array",
          "items": { "$ref": "#/$defs/realization" }
        }
      },
      "required": ["id", "plugin", "version", "role", "interaction", "contract", "realizations"],
      "additionalProperties": false
    },
    "entryNode": {
      "type": "object",
      "description": "An entry node. It may declare edges, and its last node may declare handoff.",
      "properties": {
        "id": { "$ref": "#/$defs/qualifiedRef" },
        "plugin": { "$ref": "#/$defs/name" },
        "version": { "$ref": "#/$defs/version" },
        "role": { "const": "entry" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "edges": { "$ref": "#/$defs/edges" },
        "handoff": { "$ref": "#/$defs/qualifiedRef" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": { "$ref": "#/$defs/deprecated" },
        "replaced_by": { "$ref": "#/$defs/replaced_by" },
        "aliases": { "$ref": "#/$defs/aliases" },
        "contract": { "$ref": "#/$defs/contract" },
        "realizations": {
          "type": "array",
          "items": { "$ref": "#/$defs/realization" }
        }
      },
      "required": ["id", "plugin", "version", "role", "interaction", "contract", "realizations"],
      "additionalProperties": false
    },
    "refinementNode": {
      "type": "object",
      "description": "A refinement node. It has exactly one refines target.",
      "properties": {
        "id": { "$ref": "#/$defs/qualifiedRef" },
        "plugin": { "$ref": "#/$defs/name" },
        "version": { "$ref": "#/$defs/version" },
        "role": { "const": "refinement" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "refines": { "$ref": "#/$defs/qualifiedRef" },
        "after": { "$ref": "#/$defs/after" },
        "optional": { "$ref": "#/$defs/optional" },
        "when": { "$ref": "#/$defs/when" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": { "$ref": "#/$defs/deprecated" },
        "replaced_by": { "$ref": "#/$defs/replaced_by" },
        "aliases": { "$ref": "#/$defs/aliases" },
        "contract": { "$ref": "#/$defs/contract" },
        "realizations": {
          "type": "array",
          "items": { "$ref": "#/$defs/realization" }
        }
      },
      "required": ["id", "plugin", "version", "role", "interaction", "refines", "contract", "realizations"],
      "additionalProperties": false
    },
    "observerNode": {
      "type": "object",
      "description": "An observer node. It never changes the outcome of the node it observes.",
      "properties": {
        "id": { "$ref": "#/$defs/qualifiedRef" },
        "plugin": { "$ref": "#/$defs/name" },
        "version": { "$ref": "#/$defs/version" },
        "role": { "const": "observer" },
        "interaction": { "$ref": "#/$defs/interaction" },
        "observes": { "$ref": "#/$defs/observes" },
        "on": { "$ref": "#/$defs/on" },
        "after": { "$ref": "#/$defs/after" },
        "optional": { "$ref": "#/$defs/optional" },
        "when": { "$ref": "#/$defs/when" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": { "$ref": "#/$defs/deprecated" },
        "replaced_by": { "$ref": "#/$defs/replaced_by" },
        "aliases": { "$ref": "#/$defs/aliases" },
        "contract": { "$ref": "#/$defs/contract" },
        "realizations": {
          "type": "array",
          "items": { "$ref": "#/$defs/realization" }
        }
      },
      "required": ["id", "plugin", "version", "role", "interaction", "observes", "on", "contract", "realizations"],
      "additionalProperties": false
    },
    "capabilityNode": {
      "type": "object",
      "description": "A capability in the compiled graph. It has no role, interaction or edges. Its contract is optional, because a capability may be concept-only.",
      "properties": {
        "id": { "$ref": "#/$defs/qualifiedRef" },
        "plugin": { "$ref": "#/$defs/name" },
        "version": { "$ref": "#/$defs/version" },
        "uses": { "$ref": "#/$defs/uses" },
        "deprecated": { "$ref": "#/$defs/deprecated" },
        "replaced_by": { "$ref": "#/$defs/replaced_by" },
        "aliases": { "$ref": "#/$defs/aliases" },
        "contract": { "$ref": "#/$defs/contract" },
        "realizations": {
          "type": "array",
          "items": { "$ref": "#/$defs/realization" }
        }
      },
      "required": ["id", "plugin", "version", "realizations"],
      "additionalProperties": false
    }
  }
}
''',
    "guidance-marketplace": r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Guidance marketplace file (.claude-plugin/guidance.json beside marketplace.json)",
  "description": "The optional file that guidance reads from a marketplace repository's .claude-plugin directory. Claude Code does not read it, and it is kept out of marketplace.json because Claude Code reports an unknown field there as a warning and 'claude plugin validate --strict' fails on the warning. The file may be the empty object. Its one key, pluginPrefix, is the plugin-name prefix that the marketplace's plugins start with, written without a trailing hyphen. When the file is absent, or has no pluginPrefix, the prefix is the first hyphen-delimited segment of the marketplace's name. The schema checks the shape of the value, and the compliance script checks what the prefix does to the names of the plugins and concepts (M2 and AD2). No other key is defined, so an unknown key is rejected.",
  "type": "object",
  "properties": {
    "pluginPrefix": {
      "type": "string",
      "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
      "description": "The plugin-name prefix, lowercase letters and digits with single hyphens between them, written without a trailing hyphen, such as acme-aws."
    }
  },
  "additionalProperties": false
}
''',
}
