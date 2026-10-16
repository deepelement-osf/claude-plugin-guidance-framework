"""Compile a loaded marketplace into concept-graph.json (graph spec 1.0).

Standard library only. The compiled graph is deterministic: the same marketplace
contents give the same bytes, whatever order the plugins were listed in.

Public API
----------
CompileError(message, check="F-compiled")
    Raised when a graph cannot be compiled or written. check is the check id
    that the report shows.
canonical_json(obj) -> str
    json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).
graph_hash(obj) -> str
    "sha256:" plus the lowercase hex sha256 of canonical_json of obj without its
    top-level "graphHash" key, encoded as UTF-8.
render(graph) -> str
    The file body: json.dumps(graph, sort_keys=True, indent=2,
    ensure_ascii=False) followed by one newline.
compile(marketplace, upstreams=None) -> dict
    Build the graph. upstreams maps a marketplace name to its loaded
    Marketplace. Each direct upstream is compiled to get its graphHash, so the
    result depends on the upstream contents and not on any stored file.
write_compiled(root, graph) -> Path
    Check that graph["graphHash"] matches graph_hash(graph), then write
    root/concept-graph.json as UTF-8 bytes.

Compiled shape (the field reference of the graph spec, and compiled-graph.schema.json)
--------------------------------------------------------------------------------------
{
  "graphSpecVersion": "1.0",
  "marketplace":  "<name>",
  "upstreams":    [ {"marketplace", "plugins": {"<plugin>": "<version>"} (the upstream plugins this marketplace depends on or references), "graphHash"} sorted by marketplace ],
  "nodes":        [ node sorted by id ],
  "capabilities": [ capability sorted by id ],
  "graphHash":    "sha256:<hex>"
}

A node is id, plugin, version, every declared graph field except graphSpecVersion
(role and interaction included, interaction defaulting to "autonomous"), contract
(the graph contract without graphSpecVersion) and realizations. A capability has
the same shape without role, interaction and edges, and its contract is present
only when the concept has one. A realization is {name, runs, builds_on, effects
(default []), default, realizes}, sorted by name.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gc_model import (
    COMPILED_FILE,
    GRAPH_SPEC_VERSION,
    INTERACTIONS,
    ROLES,
    Marketplace,
    graph_spec_version_problem,
    qualifier,
)

HASH_PREFIX = "sha256:"


class CompileError(Exception):
    def __init__(self, message: str, check: str = "F-compiled"):
        super().__init__(message)
        self.message = message
        self.check = check


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def graph_hash(obj: Dict[str, Any]) -> str:
    body = {k: v for k, v in obj.items() if k != "graphHash"}
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return HASH_PREFIX + digest


def render(graph: Dict[str, Any]) -> str:
    return json.dumps(graph, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_compiled(root, graph: Dict[str, Any]) -> Path:
    if graph.get("graphHash") != graph_hash(graph):
        raise CompileError("graphHash does not match the graph contents", check="X-hashes")
    path = Path(root) / COMPILED_FILE
    path.write_bytes(render(graph).encode("utf-8"))
    return path


def _read_spec_versions(marketplace: Marketplace) -> None:
    """Compile reads graphSpecVersion from every declaration it composes.

    An unsupported version raises CannotRun (exit 2) from graph_spec_version_problem. A malformed
    value is not decided here: it is left for F-schema to block, so the return value is ignored.
    """
    for concept in marketplace.concepts.values():
        for node, where in ((concept.graph, concept.skill_relpath), (concept.contract, concept.contract_relpath)):
            if isinstance(node, dict) and "graphSpecVersion" in node:
                graph_spec_version_problem(node["graphSpecVersion"], where)
    for realization in marketplace.realizations:
        graph = realization.graph
        if isinstance(graph, dict) and "graphSpecVersion" in graph:
            graph_spec_version_problem(graph["graphSpecVersion"], realization.skill_relpath)


def compile(marketplace: Marketplace, upstreams: Optional[Dict[str, Marketplace]] = None,
            _stack: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """Compile marketplace. Raises CompileError for anything that cannot be compiled."""
    _read_spec_versions(marketplace)
    upstreams = upstreams or {}
    name = marketplace.name
    if name in _stack:
        raise CompileError(f"upstream cycle through {name!r}", check="X-resolve")
    stack = _stack + (name,)

    ups = []
    for up_name in marketplace.direct_upstreams():
        up = upstreams.get(up_name)
        if up is None:
            raise CompileError(f"upstream marketplace {up_name!r} is not available", check="X-resolve")
        up_graph = compile(up, upstreams, stack)
        ups.append({
            "marketplace": up_name,
            "plugins": _recorded_plugins(marketplace, up),
            "graphHash": up_graph["graphHash"],
        })
    ups.sort(key=lambda item: item["marketplace"])

    nodes: List[Dict[str, Any]] = []
    capabilities: List[Dict[str, Any]] = []
    for concept in sorted(marketplace.concepts.values(), key=lambda c: c.id):
        common = {
            "id": concept.id,
            "plugin": concept.plugin.name,
            "version": concept.plugin.version,
        }
        declared = _declared_fields(concept)
        if declared is None:
            capability = _capability_fields(concept)
            capability.update(common)
            contract = _contract(concept)
            if contract is not None:
                capability["contract"] = contract
            capability["realizations"] = _realizations(concept)
            capabilities.append(capability)
            continue
        role = declared.get("role")
        if role not in ROLES:
            raise CompileError(
                f"concept {concept.id!r} has role {role!r}; expected one of {', '.join(ROLES)}",
                check="F-schema")
        interaction = declared.get("interaction", "autonomous")
        if interaction not in INTERACTIONS:
            raise CompileError(
                f"concept {concept.id!r} has interaction {interaction!r}; expected one of "
                f"{', '.join(INTERACTIONS)}", check="F-schema")
        node = dict(declared)
        node["interaction"] = interaction
        node.update(common)
        node["contract"] = _contract(concept)
        node["realizations"] = _realizations(concept)
        nodes.append(node)

    graph = {
        "graphSpecVersion": GRAPH_SPEC_VERSION,
        "marketplace": name,
        "upstreams": ups,
        "nodes": nodes,
        "capabilities": capabilities,
    }
    graph["graphHash"] = graph_hash(graph)
    return graph


def _recorded_plugins(marketplace: Marketplace, up: Marketplace) -> Dict[str, str]:
    """The upstream plugins this marketplace was authored against, with their versions.

    That is each plugin of the upstream that this marketplace declares a
    dependency on, and each plugin that defines a concept it references by
    name. X-versions checks these versions against the declared ranges.
    """
    names = set()
    for plugin in marketplace.plugins.values():
        for dep in plugin.dependencies:
            if dep.get("marketplace") == up.name and dep.get("name") in up.plugins:
                names.add(dep["name"])
    for concept in marketplace.concepts.values():
        for _, ref in concept.references():
            if qualifier(ref) != up.name:
                continue
            target = up.concepts.get(ref[:-(len(up.name) + 1)])
            if target is not None:
                names.add(target.plugin.name)
    return {n: up.plugins[n].version for n in sorted(names)}


def _declared_fields(concept) -> Optional[Dict[str, Any]]:
    """Every declared graph field except graphSpecVersion, or None for a capability.

    A concept with no graph block, or a graph block with no role key, is a
    capability (field reference, item 1). A graph block that is not a mapping
    cannot be read at all, so it is refused here with F-schema.
    """
    graph = concept.graph
    if graph is None:
        return None
    if not isinstance(graph, dict):
        raise CompileError(
            f"concept {concept.id!r} has a graph: value that is not a mapping", check="F-schema")
    if "role" not in graph:
        return None
    return {k: v for k, v in graph.items() if k != "graphSpecVersion"}


def _capability_fields(concept) -> Dict[str, Any]:
    graph = concept.graph if isinstance(concept.graph, dict) else {}
    return {k: v for k, v in graph.items() if k != "graphSpecVersion"}


def _contract(concept) -> Optional[Dict[str, Any]]:
    if not isinstance(concept.contract, dict):
        return None
    return {k: v for k, v in concept.contract.items() if k != "graphSpecVersion"}


def _realizations(concept) -> list:
    items = []
    for realization in sorted(concept.realizations, key=lambda r: r.name):
        graph = realization.graph if isinstance(realization.graph, dict) else {}
        items.append({
            "name": realization.name,
            "runs": graph.get("runs"),
            "builds_on": graph.get("builds_on"),
            "effects": graph.get("effects", []),
            "default": realization.default,
            "realizes": realization.realizes,
        })
    return items
