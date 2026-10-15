"""Set X, the upstream chain, plus AD2, which runs with every upstream resolved.

Standard library only. run(ctx) returns the findings of these checks:

    X-versions    each recorded upstream version satisfies the declared range,
                  for this marketplace and for every marketplace in its chain
    X-newer       warns when a newer in-range upstream tag exists; says so when
                  the tags cannot be listed
    X-resolve     every reference names a concept, and the upstream chain has no
                  cycle; a name removed upstream is also an X-lifecycle block
    X-placement   refines, observes, handoff, realizes, builds_on and after stay
                  in this marketplace or an ancestor reached through a declared
                  dependency; uses may name a sibling; a downstream target and a
                  workspace concept are refused
    X-roles       a refinement's target, an observer's target and a hand-off's
                  target have the roles the spec allows; a wildcard observer whose
                  default realization runs a session warns
    X-contracts   a contractVersion range is satisfied; a realization's schema is
                  a superset of the upstream Tier 2 schema; a refinement's result
                  is accepted by its parent's frame; a hand-off's output is
                  accepted by the target's input
    X-additive    the composed graph, less what this marketplace contributes,
                  equals the union of the upstream compiled graphs
    X-order       the after: relations across the chain have no cycle
    X-depth       a refinement chain deeper than 4 warns
    X-hashes      the recorded upstream graphHash values equal the resolved ones
    X-lifecycle   a deprecated concept or an alias warns; a name removed upstream
                  blocks
    AD2           a plugin or concept name does not repeat one of an upstream

AD3 (no inherited realization marked as the default) is owned by gc_checks_v.

Schema acceptance is a conservative subset check (type, required, properties,
enum, const, items, additionalProperties false). It reports a difference only
when it can show one, so a schema it cannot read is never a block.

Upstream graphHash values are compared without their "sha256:" prefix, because
the compiler and the compiled-graph schema write it differently.
"""

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple

from gc_compile import CompileError, canonical_json, compile
from gc_model import (
    COMPILED_FILE,
    WORKSPACE_QUALIFIER,
    Concept,
    Context,
    Finding,
    Marketplace,
    Realization,
    declared_references,
    qualifier,
)

DEPTH_LIMIT = 4
REFINES_TARGET_ROLES = (None, "phase", "entry", "refinement")
OBSERVE_TARGET_ROLES = ("phase", "entry")
OBSERVE_FILTER_ROLES = ("phase", "entry", "refinement")
PLACED_FIELDS = ("refines", "observes", "handoff", "realizes", "builds_on", "after")
_MISSING = object()


# -- version ranges ---------------------------------------------------------

_FULL_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_COMPARATOR = re.compile(r"^(\^|~|>=|<=|>|<|=)?v?([0-9xX*.]+)$")


def parse_version(text: Any) -> Optional[Tuple[int, int, int]]:
    """A plain major.minor.patch version, or None. Pre-release text is not a version here."""
    if not isinstance(text, str):
        return None
    match = _FULL_VERSION.match(text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _bump(numbers: List[int], index: int) -> Tuple[int, int, int]:
    padded = list(numbers) + [0] * (3 - len(numbers))
    result = [0, 0, 0]
    for i in range(index):
        result[i] = padded[i]
    result[index] = padded[index] + 1
    return tuple(result)


def _comparators(token: str) -> Optional[List[Tuple[str, Tuple[int, int, int]]]]:
    """The (operator, bound) pairs one comparator token stands for, or None if not understood."""
    match = _COMPARATOR.match(token)
    if not match:
        return None
    op = match.group(1) or ""
    parts = match.group(2).split(".")
    if len(parts) > 3 or "" in parts:
        return None
    numbers: List[int] = []
    for part in parts:
        if part in ("x", "X", "*"):
            break
        if not part.isdigit():
            return None
        numbers.append(int(part))
    if not numbers:
        return [(">=", (0, 0, 0))] if op in ("", "=") else None
    full = len(numbers) == 3 and len(parts) == 3
    lower = tuple(numbers + [0] * (3 - len(numbers)))
    last = len(numbers) - 1
    if op in ("", "="):
        if full:
            return [(">=", lower), ("<=", lower)]
        return [(">=", lower), ("<", _bump(numbers, last))]
    if op == "^":
        nonzero = [i for i, n in enumerate(numbers) if n != 0]
        index = nonzero[0] if nonzero else last
        return [(">=", lower), ("<", _bump(numbers, index))]
    if op == "~":
        index = 1 if len(numbers) >= 2 else 0
        return [(">=", lower), ("<", _bump(numbers, index))]
    if op == ">=":
        return [(">=", lower)]
    if op == "<":
        return [("<", lower)]
    if op == ">":
        return [(">", lower)] if full else [(">=", _bump(numbers, last))]
    if op == "<=":
        return [("<=", lower)] if full else [("<", _bump(numbers, last))]
    return None


def parse_range(text: Any) -> Optional[List[List[Tuple[str, Tuple[int, int, int]]]]]:
    """Alternatives (joined by ||) of conditions (joined by spaces), or None if not understood."""
    if not isinstance(text, str):
        return None
    if not text.strip():
        return [[(">=", (0, 0, 0))]]
    alternatives = []
    for part in text.split("||"):
        conditions = []
        tokens = part.split()
        if not tokens:
            return None
        for token in tokens:
            found = _comparators(token)
            if found is None:
                return None
            conditions.extend(found)
        alternatives.append(conditions)
    return alternatives


def _holds(version: Tuple[int, int, int], op: str, bound: Tuple[int, int, int]) -> bool:
    if op == ">=":
        return version >= bound
    if op == "<=":
        return version <= bound
    if op == ">":
        return version > bound
    if op == "<":
        return version < bound
    return version == bound


def satisfies(version: Any, range_text: Any) -> Optional[bool]:
    """True or False for a version against a range; None when the range is not understood."""
    alternatives = parse_range(range_text)
    if alternatives is None:
        return None
    parsed = parse_version(version)
    if parsed is None:
        return False
    return any(all(_holds(parsed, op, bound) for op, bound in conditions)
               for conditions in alternatives)


# -- schema checks ----------------------------------------------------------

def _show(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _types_within(produced: Any, wanted: Any) -> bool:
    produced_set = set(produced) if isinstance(produced, list) else {produced}
    wanted_set = set(wanted) if isinstance(wanted, list) else {wanted}
    for name in produced_set:
        if name in wanted_set:
            continue
        if name == "integer" and "number" in wanted_set:
            continue
        return False
    return True


def schema_accepts(consumer: Any, producer: Any, path: str = "$") -> List[str]:
    """Reasons a value matching producer may fail consumer. An empty list means accepted."""
    if not isinstance(consumer, dict) or not isinstance(producer, dict):
        return []
    issues: List[str] = []
    wanted_type = consumer.get("type")
    if wanted_type is not None:
        produced_type = producer.get("type")
        if produced_type is None:
            issues.append(f"{path}: the producer does not state a type, and the consumer requires {_show(wanted_type)}")
        elif not _types_within(produced_type, wanted_type):
            issues.append(f"{path}: type {_show(produced_type)} is not {_show(wanted_type)}")
    if isinstance(consumer.get("enum"), list):
        produced_enum = producer.get("enum")
        if not isinstance(produced_enum, list) or any(v not in consumer["enum"] for v in produced_enum):
            issues.append(f"{path}: the producer's values are not all within the consumer's enum")
    if "const" in consumer and producer.get("const", _MISSING) != consumer["const"]:
        issues.append(f"{path}: the consumer requires the constant {_show(consumer['const'])}")
    consumer_required = consumer.get("required") if isinstance(consumer.get("required"), list) else []
    producer_required = producer.get("required") if isinstance(producer.get("required"), list) else []
    consumer_props = consumer.get("properties") if isinstance(consumer.get("properties"), dict) else {}
    producer_props = producer.get("properties") if isinstance(producer.get("properties"), dict) else {}
    for key in consumer_required:
        if key not in producer_required:
            issues.append(f"{path}.{key}: the consumer requires it, and the producer does not")
    for key, sub in consumer_props.items():
        if key in producer_props:
            issues.extend(schema_accepts(sub, producer_props[key], f"{path}.{key}"))
    if consumer.get("additionalProperties") is False:
        for key in producer_props:
            if key not in consumer_props:
                issues.append(f"{path}.{key}: the consumer allows no such property")
    if isinstance(consumer.get("items"), dict) and isinstance(producer.get("items"), dict):
        issues.extend(schema_accepts(consumer["items"], producer["items"], f"{path}[]"))
    elif isinstance(consumer.get("items"), dict) and "items" not in producer:
        issues.append(f"{path}: the consumer requires items, and the producer states none")
    return issues


def superset_problems(tier2: Dict[str, Any], realization: Dict[str, Any]) -> List[str]:
    """Where a realization's schema fails to keep every Tier 2 required field and property."""
    problems: List[str] = []
    realization_required = realization.get("required") if isinstance(realization.get("required"), list) else []
    realization_props = realization.get("properties") if isinstance(realization.get("properties"), dict) else {}
    tier2_required = tier2.get("required") if isinstance(tier2.get("required"), list) else []
    tier2_props = tier2.get("properties") if isinstance(tier2.get("properties"), dict) else {}
    for key in tier2_required:
        if key not in realization_required:
            problems.append(f"the Tier 2 required field {key} is not required")
    for key, spec in tier2_props.items():
        found = realization_props.get(key)
        if found is None:
            problems.append(f"the Tier 2 property {key} is missing")
        elif isinstance(spec, dict) and isinstance(found, dict) and "type" in spec \
                and found.get("type") != spec.get("type"):
            problems.append(f"the Tier 2 property {key} has type {_show(spec.get('type'))}, "
                            f"and the realization has {_show(found.get('type'))}")
    return problems


# -- the run ----------------------------------------------------------------

def _graph(concept: Concept) -> Optional[Dict[str, Any]]:
    return concept.graph if isinstance(concept.graph, dict) else None


def _aliases(concept: Concept) -> List[str]:
    graph = _graph(concept)
    if graph is None or not isinstance(graph.get("aliases"), list):
        return []
    return [a for a in graph["aliases"] if isinstance(a, str)]


def _has_input(concept: Concept) -> bool:
    return isinstance(concept.contract, dict) and "input" in concept.contract


def _recorded_version(entry: Dict[str, Any], plugin: str) -> Optional[str]:
    plugins = entry.get("plugins")
    if isinstance(plugins, dict):
        value = plugins.get(plugin)
        return value if isinstance(value, str) else None
    if isinstance(plugins, list):
        for item in plugins:
            if isinstance(item, dict) and item.get("name") == plugin and isinstance(item.get("version"), str):
                return item["version"]
    return None


def _hex(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("sha256:"):
        return value[len("sha256:"):]
    return value


def _clean_git_env() -> Dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _list_tags(directory, pattern: str) -> Optional[List[str]]:
    """Tags matching pattern in the checkout, or None when git cannot list them."""
    try:
        result = subprocess.run(["git", "tag", "--list", pattern], cwd=str(directory),
                                env=_clean_git_env(), capture_output=True, text=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class _Run:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.m: Marketplace = ctx.marketplace
        self.ups: Dict[str, Marketplace] = ctx.upstreams
        self.previous = ctx.previous_graph
        self.findings: List[Finding] = []
        self._compiled: Dict[str, Tuple[Optional[dict], Optional[str]]] = {}
        self.ancestors: Set[str] = self._closure(self.m) - {self.m.name}
        self.removed_names: Set[str] = self._previous_upstream_names()

    # -- helpers ---------------------------------------------------------

    def add(self, check: str, severity: str, file: Optional[str], message: str, fix: str = "") -> None:
        self.findings.append(Finding(check, severity, file, message, fix))

    def _closure(self, start: Marketplace) -> Set[str]:
        names: Set[str] = set()
        seen = {start.name}
        stack = [start]
        while stack:
            current = stack.pop()
            for plugin in current.plugins.values():
                for dep in plugin.dependencies:
                    target = dep.get("marketplace")
                    if not target:
                        continue
                    names.add(target)
                    if target not in seen:
                        seen.add(target)
                        upstream = self.ups.get(target)
                        if upstream is not None:
                            stack.append(upstream)
        return names

    def chain(self) -> List[Marketplace]:
        found = [self.m]
        for name in sorted(self.ancestors):
            if name in self.ups:
                found.append(self.ups[name])
        return found

    def marketplace_named(self, name: str) -> Optional[Marketplace]:
        return self.m if name == self.m.name else self.ups.get(name)

    def _lookup(self, marketplace: Marketplace, name: str) -> Tuple[str, Optional[Concept]]:
        concept = marketplace.concepts.get(name)
        if concept is not None:
            return "ok", concept
        for candidate in sorted(marketplace.concepts.values(), key=lambda c: c.name):
            if name in _aliases(candidate):
                return "alias", candidate
        return "missing", None

    def _resolve_quiet(self, ref: Any) -> Optional[Concept]:
        q = qualifier(ref)
        if q is None or q == WORKSPACE_QUALIFIER:
            return None
        marketplace = self.marketplace_named(q)
        if marketplace is None:
            return None
        status, concept = self._lookup(marketplace, ref[:-(len(q) + 1)])
        return concept if status in ("ok", "alias") else None

    def _previous_upstream_names(self) -> Set[str]:
        """Every qualified name the previous compiled graph used that is not this marketplace's own."""
        names: Set[str] = set()
        if not isinstance(self.previous, dict):
            return names
        nodes = []
        for key in ("nodes", "capabilities"):
            if isinstance(self.previous.get(key), list):
                nodes.extend(n for n in self.previous[key] if isinstance(n, dict))
        for node in nodes:
            for _, ref in declared_references(node):
                if qualifier(ref) not in (None, self.m.name, WORKSPACE_QUALIFIER):
                    names.add(ref)
            for realization in node.get("realizations") or []:
                realizes = realization.get("realizes") if isinstance(realization, dict) else None
                concept = realizes.get("concept") if isinstance(realizes, dict) else None
                if isinstance(concept, str) and qualifier(concept) not in (None, self.m.name, WORKSPACE_QUALIFIER):
                    names.add(concept)
        return names

    def _placement_problem(self, q: str, field: str) -> Optional[str]:
        if q == self.m.name or q in self.ancestors:
            return None
        if field == "uses":
            upstream = self.ups.get(q)
            if upstream is not None and self.m.name in self._closure(upstream):
                return f"{q} is downstream of this marketplace, and a uses: target may not be downstream"
            return None
        return (f"{q} is a sibling or downstream marketplace; {field} may name only this marketplace "
                f"or an ancestor reached through a declared dependency")

    def _compiled_of(self, marketplace: Marketplace) -> Tuple[Optional[dict], Optional[str]]:
        if marketplace.name not in self._compiled:
            try:
                self._compiled[marketplace.name] = (compile(marketplace, self.ups), None)
            except CompileError as exc:
                self._compiled[marketplace.name] = (None, exc.message)
        return self._compiled[marketplace.name]

    # -- references, placement, lifecycle, roles -------------------------

    def reference(self, file: str, field: str, ref: Any) -> Optional[Concept]:
        """Check one qualified reference and return the concept it resolves to, if any."""
        q = qualifier(ref)
        if q is None:
            return None
        name = ref[:-(len(q) + 1)]
        if q == WORKSPACE_QUALIFIER:
            self.add("X-placement", "block", file,
                     f"{field} names {ref}, a workspace concept, and a marketplace may not refer to one",
                     "remove the reference, or move the concept into the marketplace that owns it")
            return None
        marketplace = self.marketplace_named(q)
        if marketplace is None:
            self.add("X-resolve", "block", file, f"{field} names {ref}, and {q} is not loaded for this run",
                     f"check {q} out beside this marketplace and pass its directory with --upstreams")
            return None
        if field in PLACED_FIELDS or field == "uses":
            problem = self._placement_problem(q, field)
            if problem is not None:
                self.add("X-placement", "block", file, f"{field} names {ref}: {problem}",
                         "point the reference at this marketplace or at an ancestor it depends on")
        status, concept = self._lookup(marketplace, name)
        if status == "missing":
            if ref in self.removed_names:
                self.add("X-lifecycle", "block", file,
                         f"{field} names {ref}, which the previous compiled graph used and which is removed upstream",
                         "point the reference at the concept that replaced it, or restore the name")
            else:
                self.add("X-resolve", "block", file, f"{field} names {ref}, which does not resolve to a concept",
                         f"name a concept that {q} defines, or an alias of one")
            return None
        if status == "alias":
            self.add("X-lifecycle", "warn", file,
                     f"{field} names {ref}, an alias of {concept.id}",
                     f"use {concept.name}@{concept.marketplace} instead")
        graph = _graph(concept)
        if graph is not None and "deprecated" in graph:
            replaced = graph.get("replaced_by")
            hint = f"; replaced_by {replaced}" if isinstance(replaced, str) else ""
            fix = f"move the reference to {replaced}" if isinstance(replaced, str) else \
                "move the reference to the concept that replaces it"
            self.add("X-lifecycle", "warn", file,
                     f"{field} names {concept.id}, which is deprecated ({graph.get('deprecated')}){hint}", fix)
        return concept

    def check_concepts(self) -> None:
        for concept in sorted(self.m.concepts.values(), key=lambda c: c.id):
            graph = _graph(concept)
            if graph is None:
                continue
            file = concept.skill_relpath
            for field, ref in declared_references(graph):
                if field == "replaced_by":
                    continue
                target = self.reference(file, field, ref)
                if target is not None:
                    self._roles(file, concept, field, target)
            observes = graph.get("observes")
            if isinstance(observes, dict):
                role = observes.get("role")
                if role not in OBSERVE_FILTER_ROLES:
                    self.add("X-roles", "block", file,
                             f"observes filters on role {role!r}, which an observer may not observe",
                             "filter on phase, entry or refinement")
            if observes == "all":
                self._wildcard_session(file, concept)

    def _roles(self, file: str, concept: Concept, field: str, target: Concept) -> None:
        role = target.role
        if field == "refines" and role not in REFINES_TARGET_ROLES:
            self.add("X-roles", "block", file,
                     f"refines targets {target.id}, a {role or 'capability'}, which is not a phase, entry, "
                     f"refinement or capability", "refine a phase, entry, refinement or capability")
        elif field == "observes" and role not in OBSERVE_TARGET_ROLES:
            self.add("X-roles", "block", file,
                     f"observes targets {target.id}, a {role or 'capability'}, which is not a phase or entry",
                     "observe a phase, an entry, all, or a role filter naming phase, entry or refinement")
        elif field == "handoff" and (role != "phase" or not _has_input(target)):
            self.add("X-roles", "block", file,
                     f"handoff targets {target.id}, which must be a phase with an input contract",
                     "hand off into a phase that declares an input contract")

    def _wildcard_session(self, file: str, concept: Concept) -> None:
        for realization in concept.realizations:
            graph = realization.graph if isinstance(realization.graph, dict) else {}
            if realization.default and graph.get("runs") == "agent":
                self.add("X-roles", "warn", file,
                         f"observer {concept.id} observes every node in scope, and its default realization "
                         f"{realization.name} runs a session at each of them",
                         "make the observer's default realization a command, or narrow the observer's scope")

    def check_realizations(self) -> None:
        for realization in sorted(self.m.realizations, key=lambda r: (r.plugin.name, r.name)):
            file = realization.skill_relpath
            if realization.concept_ref:
                self.reference(file, "realizes", realization.concept_ref)
            builds_on = realization.graph.get("builds_on") if isinstance(realization.graph, dict) else None
            if isinstance(builds_on, str):
                self._builds_on(realization, builds_on)

    def _builds_on(self, realization: Realization, name: str) -> None:
        for marketplace in self.chain():
            for other in marketplace.realizations:
                if other.name == name and other.concept_ref == realization.concept_ref:
                    return
        self.add("X-resolve", "block", realization.skill_relpath,
                 f"builds_on names {name}, which is no realization of {realization.concept_ref} "
                 f"in this marketplace or an ancestor",
                 "name a realization of the same concept that this marketplace or an ancestor provides")

    # -- contracts -------------------------------------------------------

    def check_contracts(self) -> None:
        for concept in sorted(self.m.concepts.values(), key=lambda c: c.id):
            graph = _graph(concept)
            if graph is None:
                continue
            file = concept.skill_relpath
            if graph.get("role") == "refinement" and isinstance(graph.get("refines"), str):
                parent = self._resolve_quiet(graph["refines"])
                if parent is not None and isinstance(parent.contract, dict) \
                        and isinstance(concept.contract, dict):
                    frame = parent.contract.get("frame")
                    result = concept.contract.get("result")
                    for issue in schema_accepts(frame, result):
                        self.add("X-contracts", "block", file,
                                 f"the result of {concept.id} is not accepted by the frame of {parent.id}: {issue}",
                                 "make the result accept what the parent's frame requires, or change the frame")
            if isinstance(graph.get("handoff"), str) and isinstance(concept.contract, dict):
                target = self._resolve_quiet(graph["handoff"])
                if target is not None and _has_input(target):
                    for issue in schema_accepts(target.contract.get("input"), concept.contract.get("result")):
                        self.add("X-contracts", "block", file,
                                 f"the hand-off from {concept.id} to {target.id} fails its input contract: {issue}",
                                 "make the hand-off's output accept the target's input contract")
        for realization in sorted(self.m.realizations, key=lambda r: (r.plugin.name, r.name)):
            self._realization_contract(realization)

    def _realization_contract(self, realization: Realization) -> None:
        if not isinstance(realization.realizes, dict) or not realization.concept_ref:
            return
        target = self._resolve_quiet(realization.concept_ref)
        if target is None:
            return
        wanted = realization.realizes.get("contractVersion")
        if isinstance(wanted, str):
            actual = target.schema.get("contractVersion") if isinstance(target.schema, dict) else None
            if not isinstance(actual, str):
                self.add("X-contracts", "block", target.schema_relpath,
                         f"{target.id} states no contractVersion, so the range {wanted} of "
                         f"{realization.name} cannot be satisfied",
                         "state the contractVersion of the Tier 2 contract in its schema.json")
            else:
                verdict = satisfies(actual, wanted)
                if verdict is None:
                    self.add("X-contracts", "warn", realization.skill_relpath,
                             f"contractVersion {wanted} of {realization.name} is not a range the check understands",
                             "use a caret, tilde or comparator range")
                elif verdict is False:
                    self.add("X-contracts", "block", realization.skill_relpath,
                             f"contractVersion {wanted} of {realization.name} is not satisfied by "
                             f"contractVersion {actual} of {target.id}",
                             "widen the range to the contract's version, or realize the contract it names")
        if qualifier(realization.concept_ref) not in (None, self.m.name) \
                and isinstance(target.schema, dict) and isinstance(realization.schema, dict):
            for problem in superset_problems(target.schema, realization.schema):
                self.add("X-contracts", "block", realization.schema_relpath,
                         f"the schema of {realization.name} is not a superset of the Tier 2 schema of "
                         f"{target.id}: {problem}",
                         "keep every Tier 2 required field and property in the realization's schema")

    # -- the chain: depth, order, cycles ---------------------------------

    def _refinement_depth(self, concept: Concept, stack: Tuple[str, ...]) -> Optional[int]:
        if concept.id in stack:
            return None
        graph = _graph(concept)
        if graph is None or graph.get("role") != "refinement":
            return 0
        if not isinstance(graph.get("refines"), str):
            return 1
        parent = self._resolve_quiet(graph["refines"])
        if parent is None:
            return 1
        below = self._refinement_depth(parent, stack + (concept.id,))
        return None if below is None else 1 + below

    def check_depth(self) -> None:
        for concept in sorted(self.m.concepts.values(), key=lambda c: c.id):
            graph = _graph(concept)
            if graph is None or graph.get("role") != "refinement":
                continue
            depth = self._refinement_depth(concept, ())
            if depth is None:
                self.add("X-depth", "block", concept.skill_relpath,
                         f"the refines chain of {concept.id} loops",
                         "make each refinement refine a concept nearer the phase it extends")
            elif depth > DEPTH_LIMIT:
                self.add("X-depth", "warn", concept.skill_relpath,
                         f"the refinement chain of {concept.id} is {depth} deep; the limit is {DEPTH_LIMIT}",
                         "flatten the chain, or move shared behavior into a capability")

    def check_order(self) -> None:
        nodes: Dict[str, Concept] = {}
        edges: Dict[str, List[str]] = {}
        for marketplace in [self.m] + [self.ups[n] for n in sorted(self.ups)]:
            for concept in marketplace.concepts.values():
                nodes[concept.id] = concept
        for concept_id, concept in sorted(nodes.items()):
            graph = _graph(concept)
            if graph is None or not isinstance(graph.get("after"), list):
                continue
            edges[concept_id] = [ref for ref in graph["after"]
                                 if isinstance(ref, str) and qualifier(ref) not in (None, WORKSPACE_QUALIFIER)]
        for component in _cycles(nodes.keys(), edges):
            local = [i for i in component if i in self.m.concepts or i.endswith("@" + self.m.name)]
            file = nodes[sorted(local)[0]].skill_relpath if local else None
            self.add("X-order", "block", file,
                     "the after: relations form a cycle: " + ", ".join(sorted(component)),
                     "remove one after: entry so the refinements have a single order")

    # -- upstream versions, tags and hashes ------------------------------

    def _dependencies(self, marketplace: Marketplace):
        seen = set()
        for plugin in marketplace.plugins.values():
            for dep in plugin.dependencies:
                target = dep.get("marketplace")
                name = dep.get("name")
                version = dep.get("version")
                if not target or not isinstance(name, str) or not isinstance(version, str):
                    continue
                key = (target, name, version)
                if key in seen:
                    continue
                seen.add(key)
                yield target, name, version

    def check_resolve(self) -> None:
        state: Dict[str, int] = {}
        path: List[str] = []

        def visit(name: str) -> None:
            if state.get(name) == 2:
                return
            if state.get(name) == 1:
                cycle = path[path.index(name):] + [name]
                self.add("X-resolve", "block", None,
                         "upstream marketplaces form a cycle: " + " -> ".join(cycle),
                         "remove the dependency that closes the cycle")
                return
            state[name] = 1
            path.append(name)
            marketplace = self.marketplace_named(name)
            if marketplace is not None:
                for dep in marketplace.direct_upstreams():
                    if dep in self.ups or dep == self.m.name:
                        visit(dep)
            path.pop()
            state[name] = 2

        visit(self.m.name)

    def check_versions(self) -> None:
        for marketplace in self.chain():
            if not isinstance(marketplace.compiled, dict):
                continue
            entries = marketplace.compiled.get("upstreams")
            entries = entries if isinstance(entries, list) else []
            file = COMPILED_FILE if marketplace is self.m else None
            for target, name, version in self._dependencies(marketplace):
                entry = next((e for e in entries if isinstance(e, dict) and e.get("marketplace") == target), None)
                if entry is None:
                    continue
                recorded = _recorded_version(entry, name)
                if recorded is None:
                    self.add("X-versions", "block", file,
                             f"{marketplace.name} records no version of {name} from {target}",
                             "recompile with guidance_check.py --compile")
                    continue
                verdict = satisfies(recorded, version)
                if verdict is None:
                    self.add("X-versions", "warn", file,
                             f"the range {version} of {name} from {target} is not understood",
                             "use a caret, tilde or comparator range")
                elif verdict is False:
                    self.add("X-versions", "block", file,
                             f"{marketplace.name} recorded {name} {recorded} from {target}, "
                             f"which lies outside its range {version}",
                             "recompile against a version inside the range, or widen the range")

    def check_newer(self) -> None:
        unlisted: Set[str] = set()
        for marketplace in self.chain():
            if not isinstance(marketplace.compiled, dict):
                continue
            entries = marketplace.compiled.get("upstreams")
            entries = entries if isinstance(entries, list) else []
            file = COMPILED_FILE if marketplace is self.m else None
            for target, name, version in self._dependencies(marketplace):
                upstream = self.ups.get(target)
                entry = next((e for e in entries if isinstance(e, dict) and e.get("marketplace") == target), None)
                if upstream is None or entry is None:
                    continue
                recorded = parse_version(_recorded_version(entry, name))
                if recorded is None or parse_range(version) is None:
                    continue
                tags = _list_tags(upstream.root, f"{name}--v*")
                if tags is None:
                    if target not in unlisted:
                        unlisted.add(target)
                        self.add("X-newer", "warn", None,
                                 f"the tags of {target} cannot be listed, so newer versions are not checked",
                                 "run the check in a checkout of the upstream with its tags fetched")
                    continue
                newest = None
                for tag in tags:
                    if not tag.startswith(f"{name}--v"):
                        continue
                    candidate = tag[len(f"{name}--v"):]
                    parsed = parse_version(candidate)
                    if parsed is None or parsed <= recorded or satisfies(candidate, version) is not True:
                        continue
                    if newest is None or parsed > newest[0]:
                        newest = (parsed, candidate)
                if newest is not None:
                    self.add("X-newer", "warn", file,
                             f"{name} {newest[1]} from {target} is newer than the recorded version and "
                             f"satisfies {version}; recompiling would pick it up",
                             "recompile to adopt the newer version, if it suits this marketplace")

    def check_hashes(self) -> None:
        if not isinstance(self.m.compiled, dict):
            return
        entries = self.m.compiled.get("upstreams")
        entries = entries if isinstance(entries, list) else []
        recorded = {e["marketplace"]: e for e in entries
                    if isinstance(e, dict) and isinstance(e.get("marketplace"), str)}
        for name in self.m.direct_upstreams():
            if name not in recorded and name in self.ups:
                self.add("X-hashes", "block", COMPILED_FILE,
                         f"concept-graph.json records no graphHash for the upstream {name}",
                         "recompile with guidance_check.py --compile")
        for name in sorted(recorded):
            upstream = self.ups.get(name)
            if upstream is None:
                continue
            graph, error = self._compiled_of(upstream)
            if graph is None:
                self.add("X-hashes", "block", COMPILED_FILE,
                         f"the upstream {name} cannot be compiled, so its graphHash cannot be checked: {error}",
                         "fix the upstream so that it compiles, then recompile this marketplace")
                continue
            if _hex(recorded[name].get("graphHash")) != _hex(graph.get("graphHash")):
                self.add("X-hashes", "block", COMPILED_FILE,
                         f"the recorded graphHash of {name} differs from the resolved upstream",
                         "check that the upstream changed with a version change, then recompile")

    # -- the additive rule -----------------------------------------------

    def check_additive(self) -> None:
        stored = self.m.compiled
        if not isinstance(stored, dict) or not isinstance(stored.get("nodes"), list):
            return
        if not self.ancestors:
            # A root marketplace defines the base phases; there is no upstream to add to.
            return
        union: Dict[str, dict] = {}
        for name in sorted(self.ancestors):
            upstream = self.ups.get(name)
            if upstream is None:
                continue
            graph, error = self._compiled_of(upstream)
            if graph is None:
                self.add("X-additive", "block", COMPILED_FILE,
                         f"the upstream {name} cannot be compiled, so the additive rule cannot be checked: {error}",
                         "fix the upstream so that it compiles")
                return
            for node in graph.get("nodes", []):
                if isinstance(node, dict) and isinstance(node.get("id"), str):
                    union[node["id"]] = node
        composed = dict(union)
        for node in stored["nodes"]:
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                composed[node["id"]] = node

        own = self.m.name
        contributed = {i for i, n in composed.items()
                       if qualifier(i) == own and n.get("role") in ("refinement", "observer", "entry")}
        entries = [i for i in contributed if composed[i].get("role") == "entry"]
        chain_phases: Set[str] = set()
        frontier = list(entries)
        while frontier:
            current = frontier.pop()
            for edge in composed.get(current, {}).get("edges") or []:
                target = edge.get("to") if isinstance(edge, dict) else None
                if isinstance(target, str) and qualifier(target) == own and target not in chain_phases \
                        and composed.get(target, {}).get("role") == "phase":
                    chain_phases.add(target)
                    frontier.append(target)
        handoff_targets = {n.get("handoff") for n in composed.values()
                           if qualifier(n.get("id")) == own and isinstance(n.get("handoff"), str)}
        removed = contributed | (chain_phases - handoff_targets)
        remainder = {i: n for i, n in composed.items() if i not in removed}

        for extra in sorted(set(remainder) - set(union)):
            self.add("X-additive", "block", COMPILED_FILE,
                     f"{extra} is in the composed graph but in no upstream: a phase may be added only inside "
                     f"an entry chain",
                     "move the phase into an entry chain, or remove it")
        for missing in sorted(set(union) - set(remainder)):
            self.add("X-additive", "block", COMPILED_FILE,
                     f"the upstream node {missing} is missing from the composed graph",
                     "restore the upstream node; a marketplace may not remove an inherited node")
        for node_id in sorted(set(union) & set(remainder)):
            self._node_diff(node_id, union[node_id], remainder[node_id])

    def _node_diff(self, node_id: str, upstream: dict, composed: dict) -> None:
        if upstream.get("role") != composed.get("role"):
            self.add("X-additive", "block", COMPILED_FILE,
                     f"the role of {node_id} is {composed.get('role')} here and {upstream.get('role')} upstream",
                     "restore the upstream role; additions go in refinements, observers and entry chains")
        if (upstream.get("interaction") or "autonomous") != (composed.get("interaction") or "autonomous"):
            self.add("X-additive", "block", COMPILED_FILE,
                     f"the interaction of {node_id} differs from the upstream value",
                     "restore the upstream interaction value")
        up_edges = {canonical_json(e): e for e in upstream.get("edges") or []}
        here_edges = {canonical_json(e): e for e in composed.get("edges") or []}
        gone = sorted(set(up_edges) - set(here_edges))
        added = sorted(set(here_edges) - set(up_edges))
        if gone or added:
            detail = []
            if gone:
                detail.append("removed " + ", ".join(canonical_json(up_edges[k]) for k in gone))
            if added:
                detail.append("added " + ", ".join(canonical_json(here_edges[k]) for k in added))
            self.add("X-additive", "block", COMPILED_FILE,
                     f"the edges of {node_id} differ from the upstream node: {'; '.join(detail)}",
                     "restore the upstream edges; an inheriter never removes or redirects an edge")
        up_input = (upstream.get("contract") or {}).get("input") if isinstance(upstream.get("contract"), dict) else None
        here_input = (composed.get("contract") or {}).get("input") if isinstance(composed.get("contract"), dict) else None
        if canonical_json(up_input) != canonical_json(here_input):
            self.add("X-additive", "block", COMPILED_FILE,
                     f"the input contract of {node_id} differs from the upstream node",
                     "restore the upstream input contract")

    def check_ad2(self) -> None:
        plugin_names: Dict[str, str] = {}
        concept_names: Dict[str, str] = {}
        for name in sorted(self.ups):
            upstream = self.ups[name]
            for plugin_name in upstream.plugins:
                plugin_names.setdefault(plugin_name, name)
            for concept_name in upstream.concepts:
                concept_names.setdefault(concept_name, name)
        for plugin_name in sorted(self.m.plugins):
            if plugin_name in plugin_names:
                plugin = self.m.plugins[plugin_name]
                file = self.m.rel(plugin.dir / ".claude-plugin" / "plugin.json") if plugin.dir else None
                self.add("AD2", "block", file,
                         f"plugin {plugin_name} has the same name as a plugin of {plugin_names[plugin_name]}",
                         "rename the plugin under this marketplace's own prefix")
        for concept_name in sorted(self.m.concepts):
            if concept_name in concept_names:
                concept = self.m.concepts[concept_name]
                self.add("AD2", "block", concept.skill_relpath,
                         f"concept {concept_name} has the same name as a concept of {concept_names[concept_name]}",
                         "rename the concept's plugin under this marketplace's own prefix")

    def run(self) -> List[Finding]:
        self.check_resolve()
        self.check_concepts()
        self.check_realizations()
        self.check_contracts()
        self.check_depth()
        self.check_order()
        self.check_ad2()
        self.check_versions()
        self.check_newer()
        self.check_hashes()
        self.check_additive()
        return self.findings


def _cycles(nodes, edges: Dict[str, List[str]]) -> List[List[str]]:
    """Strongly connected components that form a cycle (more than one node, or a self-loop)."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    found: List[List[str]] = []
    counter = [0]

    def connect(node: str) -> None:
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for target in edges.get(node, []):
            if target not in index:
                connect(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in edges.get(node, []):
                found.append(sorted(component))

    for node in sorted(nodes):
        if node not in index:
            connect(node)
    return found


def run(ctx: Context) -> List[Finding]:
    """The findings of set X and AD2 for one marketplace run."""
    return _Run(ctx).run()
