"""Checks V-major, V-bump, A8 and AD3, run by guidance_check.py.

Standard library only. run(ctx) returns Finding objects. It never edits a file.

V-major (graph semver, plan 3 and 6.3)
    Compares each plugin's part of the compiled graph with the previous
    release. A plugin's part is its nodes and capabilities, with their edges,
    contracts and declarations. The previous release is ctx.previous_graph when
    --previous is given. Otherwise it is concept-graph.json at the plugin's
    baseline tag, <plugin>--v<version>, read with git show in ctx.repo. The
    baseline is the newest such tag whose version is not above the current one.
    No baseline passes. A MAJOR change blocks unless the plugin's MAJOR version
    went up.

    The MAJOR changes, as the plan lists them:
      - a node or capability is removed, or renamed with no alias that resolves;
      - an alias is dropped;
      - an edge is removed;
      - a frame, input or result schema narrows (see _narrowing), or is removed;
      - a contract goes from selection many to selection one;
      - an optional refinement or observer becomes required;
      - a when key is added to, or a value changed in, a refinement or observer.

    Where the plan leaves a judgement open, the check takes the stricter reading.
    A pattern that changes counts as narrowing, and so does any changed
    oneOf, anyOf, allOf or not. A changed when value counts as narrowing.

V-bump (warn)
    A plugin whose current version has a release tag, and whose directory has
    changed since that tag, has not been bumped. Skipped when git history is
    unavailable. It never blocks.

A8 (reversed, decision 21)
    Blocks when a plugin declares a dependency on guidance-conventions or
    guidance-activation-check, or on any plugin of the guidance marketplace. It
    also blocks when allowCrossMarketplaceDependenciesOn lists the guidance
    marketplace. The guidance marketplace name comes from this plugin's own
    marketplace, three levels above this directory, and falls back to
    GUIDANCE_FALLBACK.

AD3 (amended, decision 19)
    A realization whose realizes block names a concept of another marketplace
    is allowed. It blocks only when it is marked default.

Public API
----------
run(ctx) -> list[Finding]
guidance_marketplace_name() -> str
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gc_compile import CompileError, compile
from gc_model import COMPILED_FILE, Context, Finding, qualifier
from gc_parse import load_json

SCRIPT_DIR = Path(__file__).resolve().parent
GUIDANCE_FALLBACK = "claude-plugin-guidance"
GUIDANCE_PLUGIN_NAMES = ("guidance-conventions", "guidance-activation-check")

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_ANNOTATIONS = frozenset({
    "$schema", "$id", "$comment", "title", "description", "examples", "default",
    "readOnly", "writeOnly", "$defs", "definitions",
})
_MAX_DEPTH = 16


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def guidance_marketplace_name() -> str:
    """The guidance marketplace name, read from this plugin's own marketplace."""
    try:
        path = SCRIPT_DIR.parents[2] / ".claude-plugin" / "marketplace.json"
    except IndexError:
        return GUIDANCE_FALLBACK
    try:
        data = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return GUIDANCE_FALLBACK
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else GUIDANCE_FALLBACK


def _git_env() -> Dict[str, str]:
    drop = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
    return {k: v for k, v in os.environ.items() if k not in drop}


def _git(repo: Path, *args: str) -> Optional[str]:
    """Run git in repo. None when git cannot run or the command fails."""
    try:
        result = subprocess.run(["git", *args], cwd=str(repo), env=_git_env(),
                                capture_output=True, text=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _history(repo: Path) -> bool:
    out = _git(repo, "rev-parse", "--is-inside-work-tree")
    return out is not None and out.strip() == "true"


def _repo_relpath(path: Path, repo: Path) -> Optional[str]:
    """Path relative to repo, in POSIX form, or None when it lies outside repo."""
    rel = os.path.relpath(os.path.realpath(str(path)), os.path.realpath(str(repo)))
    if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def _parse_version(text: Any) -> Optional[Tuple[int, int, int, bool, str]]:
    """A sort key for MAJOR.MINOR.PATCH[-pre], or None. Index 0 is the MAJOR."""
    if not isinstance(text, str):
        return None
    match = _SEMVER.match(text.strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), pre is None, pre or "")


def _strings(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _dicts(value: Any) -> List[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _eq(a: Any, b: Any) -> bool:
    """JSON equality: 1 equals 1.0, and true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_num(a) and _is_num(b):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _plugin_items(graph: Any) -> Dict[str, Dict[str, dict]]:
    """Plugin name -> {id: node} for every node and capability of a compiled graph."""
    grouped: Dict[str, Dict[str, dict]] = {}
    if not isinstance(graph, dict):
        return grouped
    for key in ("nodes", "capabilities"):
        for node in _dicts(graph.get(key)):
            if isinstance(node.get("id"), str) and isinstance(node.get("plugin"), str):
                grouped.setdefault(node["plugin"], {})[node["id"]] = node
    return grouped


def _version_of(items: Dict[str, dict]) -> Optional[str]:
    for node in items.values():
        version = node.get("version")
        return version if isinstance(version, str) else None
    return None


def _selection(contract: dict) -> str:
    value = contract.get("selection", "one")
    return value if value in ("one", "many") else "one"


def _edge_pairs(node: dict, resolve) -> set:
    pairs = set()
    for edge in _dicts(node.get("edges")):
        outcome, target = edge.get("outcome"), resolve(edge.get("to"))
        if isinstance(outcome, str) and isinstance(target, str):
            pairs.add((outcome, target))
    return pairs


# ---------------------------------------------------------------------------
# Schema narrowing (the MAJOR rule for frame, input and result contracts)
# ---------------------------------------------------------------------------

def _constrains(schema: Any) -> bool:
    if schema is True:
        return False
    if schema is False:
        return True
    return isinstance(schema, dict) and any(k not in _ANNOTATIONS for k in schema)


def _pointer(root: Any, ref: str) -> Any:
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _deref(schema: Any, root: Any) -> Any:
    for _ in range(32):
        if not isinstance(schema, dict) or not isinstance(schema.get("$ref"), str):
            return schema
        target = _pointer(root, schema["$ref"])
        if target is None:
            return schema
        schema = target
    return schema


def _types(schema: dict) -> Optional[set]:
    value = schema.get("type")
    if value is None:
        return None
    names = {n for n in (value if isinstance(value, list) else [value]) if isinstance(n, str)}
    if "number" in names:
        names.add("integer")
    return names


def _join(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _narrowing(p: Any, c: Any, p_root: Any, c_root: Any, where: str = "",
               depth: int = 0) -> List[str]:
    """Reasons the schema c accepts fewer instances than the schema p did.

    The list is empty when c is not narrower. Only the subset of JSON Schema
    that guidance keeps to is read. Adding an optional property is not
    narrowing, as the plan's MINOR list says. Requiring one is.
    """
    if depth > _MAX_DEPTH:
        return []
    p = _deref(p, p_root)
    c = _deref(c, c_root)
    label = where or "the contract"
    if p is False or c is True:
        return []
    if c is False:
        return [f"{label} accepts nothing"]
    if not _constrains(c):
        return []
    if p is True or not _constrains(p):
        return [f"{label} is now constrained"]
    if not isinstance(p, dict) or not isinstance(c, dict):
        return []

    out: List[str] = []
    p_types, c_types = _types(p), _types(c)
    if c_types is not None and (p_types is None or not p_types <= c_types):
        out.append(f"{label} narrows its type")
    if isinstance(c.get("enum"), list):
        p_enum = p.get("enum")
        if not isinstance(p_enum, list):
            out.append(f"{label} adds an enum")
        elif any(not any(_eq(v, w) for w in c["enum"]) for v in p_enum):
            out.append(f"{label} removes an enum value")
    if "const" in c and ("const" not in p or not _eq(p["const"], c["const"])):
        out.append(f"{label} adds or changes a const")
    new_required = sorted(set(_strings(c.get("required"))) - set(_strings(p.get("required"))))
    if new_required:
        out.append(f"{label} requires {', '.join(new_required)}")

    p_props, c_props = _as_dict(p.get("properties")), _as_dict(c.get("properties"))
    closed = c.get("additionalProperties") is False
    for key in sorted(set(p_props) - set(c_props)):
        if closed:
            out.append(f"{label} no longer allows {key}")
    for key in sorted(set(p_props) & set(c_props)):
        out += _narrowing(p_props[key], c_props[key], p_root, c_root, _join(where, key), depth + 1)
    if p.get("additionalProperties") is not False and c.get("additionalProperties") is False:
        out.append(f"{label} stops allowing extra properties")

    if isinstance(c.get("items"), dict):
        p_items = p.get("items", True)
        if isinstance(p_items, list):
            p_items = True
        out += _narrowing(p_items, c["items"], p_root, c_root, _join(where, "items"), depth + 1)

    for key in ("minItems", "minLength", "minProperties"):
        floor = p.get(key) if _is_num(p.get(key)) else 0
        if _is_num(c.get(key)) and c[key] > floor:
            out.append(f"{label} raises {key}")
    for key in ("minimum", "exclusiveMinimum"):
        if _is_num(c.get(key)) and (not _is_num(p.get(key)) or c[key] > p[key]):
            out.append(f"{label} raises {key}")
    for key in ("maxItems", "maxLength", "maxProperties", "maximum", "exclusiveMaximum"):
        if _is_num(c.get(key)) and (not _is_num(p.get(key)) or c[key] < p[key]):
            out.append(f"{label} lowers {key}")
    if "pattern" in c and c.get("pattern") != p.get("pattern"):
        out.append(f"{label} adds or changes a pattern")
    for kw in ("oneOf", "anyOf", "allOf"):
        if kw in c and not _eq(c[kw], p.get(kw)):
            out.append(f"{label} changes {kw}")
    if "not" in c and not _eq(c["not"], p.get("not")):
        out.append(f"{label} changes not")
    return out


# ---------------------------------------------------------------------------
# V-major
# ---------------------------------------------------------------------------

def _current_graph(ctx: Context) -> Optional[dict]:
    try:
        return compile(ctx.marketplace, ctx.upstreams)
    except CompileError:
        return None


def _major_reasons(prev: Dict[str, dict], cur: Dict[str, dict], market: str,
                   everywhere: Optional[Dict[str, dict]] = None) -> List[str]:
    """Every MAJOR change between two plugin parts, as short reasons.

    cur holds the plugin's own current nodes. everywhere holds every current node in the
    marketplace, so that a concept renamed into another plugin (or a removed plugin whose
    concepts moved) is resolved through its alias. It defaults to cur.
    """
    everywhere = cur if everywhere is None else everywhere
    alias_to_id: Dict[str, str] = {}
    for cid in sorted(everywhere):
        for alias in _strings(everywhere[cid].get("aliases")):
            alias_to_id.setdefault(alias, cid)

    def resolve(ref: Any) -> Any:
        # An old name that an alias carries now names the aliased node.
        if not isinstance(ref, str) or "@" not in ref or ref in everywhere:
            return ref
        name, marketplace = ref.rsplit("@", 1)
        if marketplace == market and name in alias_to_id:
            return alias_to_id[name]
        return ref

    reasons: List[str] = []
    for pid in sorted(prev):
        if pid not in everywhere and pid.rsplit("@", 1)[0] not in alias_to_id:
            reasons.append(f"removes {pid}")

    for pid in sorted(prev):
        if pid not in cur:
            continue
        p, c = prev[pid], cur[pid]
        dropped = [a for a in _strings(p.get("aliases")) if a not in alias_to_id]
        if dropped:
            reasons.append(f"drops alias {', '.join(dropped)} from {pid}")
        for outcome, target in sorted(_edge_pairs(p, resolve) - _edge_pairs(c, resolve)):
            reasons.append(f"removes edge {pid} {outcome} -> {target}")

        p_contract, c_contract = _as_dict(p.get("contract")), _as_dict(c.get("contract"))
        if _selection(p_contract) == "many" and _selection(c_contract) == "one":
            reasons.append(f"changes {pid} from selection many to one")
        for key in ("frame", "input", "result"):
            if p_contract.get(key) is None:
                continue
            if c_contract.get(key) is None:
                reasons.append(f"removes the {key} contract of {pid}")
                continue
            for why in _narrowing(p_contract[key], c_contract[key], p_contract[key], c_contract[key]):
                reasons.append(f"narrows the {key} contract of {pid}: {why}")

        if p.get("role") in ("refinement", "observer"):
            role = p["role"]
            if p.get("optional") is True and c.get("optional") is not True:
                reasons.append(f"makes the optional {role} {pid} required")
            p_when, c_when = _as_dict(p.get("when")), _as_dict(c.get("when"))
            added = sorted(k for k in c_when if k not in p_when)
            changed = sorted(k for k in p_when if k in c_when and not _eq(p_when[k], c_when[k]))
            if added or changed:
                reasons.append(f"adds or changes when on {pid}: {', '.join(added + changed)}")
    return reasons


def _git_baseline(ctx: Context, name: str, cur_version: Optional[str],
                  findings: List[Finding]) -> Optional[Tuple[Optional[str], Dict[str, dict]]]:
    repo = ctx.repo
    if not _history(repo):
        return None
    tags = _release_tags(repo, name)
    eligible = [t for t in tags if _parse_version(cur_version) is None or t[0] <= _parse_version(cur_version)]
    if not eligible:
        return None
    _, version, tag = eligible[-1]
    rel = _repo_relpath(ctx.root, repo)
    if rel is None:
        return None
    path = "./" + os.path.normpath(os.path.join(rel, COMPILED_FILE)).replace(os.sep, "/")
    text = _git(repo, "show", f"refs/tags/{tag}:{path}")
    if text is None:
        return None
    try:
        graph = json.loads(text)
    except ValueError:
        findings.append(Finding(
            "V-major", "warn", None,
            f"{COMPILED_FILE} at {tag} cannot be read, so the graph change for {name} was not compared",
            f"recompile the release, or tag a commit whose {COMPILED_FILE} is valid"))
        return None
    return version, _plugin_items(graph).get(name, {})


def _release_tags(repo: Path, name: str) -> List[Tuple[Tuple, str, str]]:
    """(sort key, version text, tag) for every <name>--v<version> tag in repo, oldest first."""
    prefix = f"{name}--v"
    out = _git(repo, "tag", "--list", prefix + "*") or ""
    found = []
    for line in out.splitlines():
        tag = line.strip()
        if not tag.startswith(prefix):
            continue
        text = tag[len(prefix):]
        key = _parse_version(text)
        if key is not None:
            found.append((key, text, tag))
    return sorted(found, key=lambda item: item[0])


def _plugin_manifest_rel(ctx: Context, plugin) -> str:
    if plugin is not None and plugin.dir is not None:
        return ctx.marketplace.rel(plugin.dir / ".claude-plugin" / "plugin.json")
    return ctx.marketplace.rel(ctx.root / ".claude-plugin" / "marketplace.json")


def _v_major(ctx: Context, findings: List[Finding]) -> None:
    if any(f.blocking for f in ctx.marketplace.findings):
        return
    current = _current_graph(ctx)
    if current is None:
        return
    cur_all = _plugin_items(current)
    everywhere = {nid: node for items in cur_all.values() for nid, node in items.items()}
    prev_all = _plugin_items(ctx.previous_graph) if ctx.previous_graph is not None else None
    names = set(ctx.marketplace.plugins)
    if prev_all is not None:
        names |= set(prev_all)

    for name in sorted(names):
        plugin = ctx.marketplace.plugins.get(name)
        cur_version = plugin.version if plugin is not None else None
        if prev_all is not None:
            prev_items = prev_all.get(name)
            if not prev_items:
                continue
            prev_version = _version_of(prev_items)
        else:
            baseline = _git_baseline(ctx, name, cur_version, findings)
            if baseline is None:
                continue
            prev_version, prev_items = baseline
            if not prev_items:
                continue

        reasons = _major_reasons(prev_items, cur_all.get(name, {}), ctx.marketplace.name, everywhere)
        if not reasons:
            continue
        detail = "; ".join(reasons)
        if plugin is None:
            findings.append(Finding(
                "V-major", "block", ctx.marketplace.rel(ctx.root / ".claude-plugin" / "marketplace.json"),
                f"plugin {name} is no longer in the marketplace, a MAJOR change ({detail})",
                f"restore {name} or keep its concepts under aliases; a removed plugin cannot bump its version"))
            continue
        cur_key = _parse_version(cur_version)
        prev_key = _parse_version(prev_version)
        if cur_key is not None and prev_key is not None and cur_key[0] > prev_key[0]:
            continue
        findings.append(Finding(
            "V-major", "block", _plugin_manifest_rel(ctx, plugin),
            f"plugin {name} changes its graph in a MAJOR way ({detail}), but its version is "
            f"{cur_version or 'unset'} against the previous {prev_version or 'unset'}",
            f"raise the MAJOR version of {name} in its plugin.json, or undo the MAJOR change"))


# ---------------------------------------------------------------------------
# V-bump
# ---------------------------------------------------------------------------

def _v_bump(ctx: Context, findings: List[Finding]) -> None:
    repo = ctx.repo
    if not _history(repo):
        return
    for name in sorted(ctx.marketplace.plugins):
        plugin = ctx.marketplace.plugins[name]
        if plugin.dir is None or not isinstance(plugin.version, str):
            continue
        released = [t for t in _release_tags(repo, name) if t[1] == plugin.version]
        if not released:
            continue
        pathspec = _repo_relpath(plugin.dir, repo)
        if pathspec is None:
            continue
        tag = released[0][2]
        changed = _git(repo, "diff", "--name-only", f"refs/tags/{tag}", "--", pathspec)
        if changed and changed.strip():
            findings.append(Finding(
                "V-bump", "warn", _plugin_manifest_rel(ctx, plugin),
                f"plugin {name} changed since its release {tag} but its version is still {plugin.version}",
                f"bump the version of {name} in its plugin.json, or revert the change"))


# ---------------------------------------------------------------------------
# A8 (reversed) and AD3 (amended)
# ---------------------------------------------------------------------------

def _dependency_refs(raw: Any) -> List[Tuple[str, Optional[str]]]:
    """(plugin name, marketplace or None) for each dependency entry."""
    refs: List[Tuple[str, Optional[str]]] = []
    for item in (raw if isinstance(raw, list) else [raw]):
        if isinstance(item, str):
            if "@" in item:
                name, marketplace = item.rsplit("@", 1)
                refs.append((name, marketplace))
            else:
                refs.append((item, None))
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            marketplace = item.get("marketplace")
            refs.append((item["name"], marketplace if isinstance(marketplace, str) else None))
    return refs


def _a8(ctx: Context, findings: List[Finding]) -> None:
    guidance = guidance_marketplace_name()
    market_rel = ctx.marketplace.rel(ctx.root / ".claude-plugin" / "marketplace.json")
    if guidance in _strings(ctx.marketplace.manifest.get("allowCrossMarketplaceDependenciesOn")):
        findings.append(Finding(
            "A8", "block", market_rel,
            f"allowCrossMarketplaceDependenciesOn lists the guidance marketplace {guidance}",
            "remove that entry; no marketplace depends on guidance"))
    for plugin in ctx.marketplace.plugins.values():
        sources = [(market_rel, plugin.entry.get("dependencies"))]
        if plugin.dir is not None:
            sources.append((_plugin_manifest_rel(ctx, plugin),
                            _as_dict(plugin.manifest).get("dependencies")))
        for rel, raw in sources:
            for name, marketplace in _dependency_refs(raw):
                if name in GUIDANCE_PLUGIN_NAMES or marketplace == guidance:
                    findings.append(Finding(
                        "A8", "block", rel,
                        f"plugin {plugin.name} declares a dependency on the guidance plugin {name}",
                        "remove the dependency; guidance runs only in marketplace repositories, "
                        "and a realization calls the activation check only if it is installed"))


def _ad3(ctx: Context, findings: List[Finding]) -> None:
    for realization in ctx.marketplace.realizations:
        if realization.realizes is None:
            continue
        owner = qualifier(realization.concept_ref)
        if owner is None or owner == ctx.marketplace.name:
            continue
        if realization.default:
            findings.append(Finding(
                "AD3", "block", realization.skill_relpath,
                f"realization {realization.name} realizes {realization.concept_ref}, a concept of "
                f"another marketplace, and is marked default",
                "remove 'default: true'; only the workspace's selection may run an inherited realization"))


def run(ctx: Context) -> List[Finding]:
    findings: List[Finding] = []
    _a8(ctx, findings)
    _ad3(ctx, findings)
    _v_bump(ctx, findings)
    _v_major(ctx, findings)
    return findings
