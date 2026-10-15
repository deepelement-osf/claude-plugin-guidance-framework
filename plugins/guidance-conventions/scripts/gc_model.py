"""The model that the guidance checks and the compiler share.

Standard library only. This module loads a marketplace repository into plain
objects. It never edits a file and never decides whether a finding blocks a
commit; the checks do that.

Public API
----------
Constants
    GRAPH_SPEC_VERSION = "1.0"
    ROLES              ("phase", "entry", "refinement", "observer")
    INTERACTIONS       ("autonomous", "pause", "conversational")
    COMPILED_FILE      "concept-graph.json"
    WORKSPACE_QUALIFIER "workspace"

Finding(check, severity, file, message, fix="")
    One result. severity is "block" or "warn". file is a path relative to the
    marketplace root in POSIX form, or None. to_dict() gives the JSON shape of
    the command-line report. blocking is True for "block".

Options(json, compile, upstreams_dir, previous_dir, repo, no_official, no_pin)
    The command-line options, as a plain object.

Plugin, Concept, Realization, Marketplace
    Loaded objects. Marketplace.load(root) reads .claude-plugin/marketplace.json,
    each plugin's .claude-plugin/plugin.json, every skills/concept/SKILL.md
    (a concept), every skills/realization-contract/ (graph-contract.json and
    schema.json) and every skills/realize-*/ (a realization). It raises
    MarketplaceError only when the directory is not a marketplace at all. Every
    other problem is recorded in Marketplace.findings, as an F-files finding
    (or AD1 for a duplicate concept), and loading goes on.

Context(root, marketplace, upstreams, previous_graph, options, guidance_version)
    What a check receives. upstreams maps a marketplace name to its loaded
    Marketplace. previous_graph is the compiled graph at the previous release,
    or None.

concept_name(plugin_name, prefix) -> str
    A concept's name is its plugin's name without "<prefix>-". The prefix is
    the first hyphen-separated segment of the marketplace name.
qualifier(ref) -> str | None
    The marketplace part of "<concept>@<marketplace>".
declared_references(graph) -> list[(field, ref)]
    Every qualified reference in a graph declaration, with the field it came
    from. Role-filter observers and "all" are not references.
is_marketplace_repository(directory) -> bool
    Guidance's one test: the directory holds .claude-plugin/marketplace.json
    and git reports that directory as its own top level.

Plugin.dependencies is a list of {"name", "marketplace", "version"} dicts,
read from the marketplace entry and from plugin.json. A string entry means a
plugin of the same marketplace and has marketplace None.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gc_parse import SkillDoc, load_json, participation_bullets, read_skill, realizes_block

GRAPH_SPEC_VERSION = "1.0"
ROLES = ("phase", "entry", "refinement", "observer")
INTERACTIONS = ("autonomous", "pause", "conversational")
COMPILED_FILE = "concept-graph.json"
WORKSPACE_QUALIFIER = "workspace"

_REFERENCE_FIELDS = ("refines", "observes", "uses", "handoff", "after", "replaced_by")


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    file: Optional[str]
    message: str
    fix: str = ""

    def __post_init__(self):
        if self.severity not in ("block", "warn"):
            raise ValueError(f"severity must be 'block' or 'warn', not {self.severity!r}")

    @property
    def blocking(self) -> bool:
        return self.severity == "block"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "file": self.file,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class Options:
    json: bool = False
    compile: bool = False
    upstreams_dir: Optional[Path] = None
    previous_dir: Optional[Path] = None
    repo: Optional[Path] = None
    no_official: bool = False
    no_pin: bool = False


class MarketplaceError(Exception):
    """The directory cannot be read as a marketplace at all."""


def qualifier(ref: Any) -> Optional[str]:
    if isinstance(ref, str) and "@" in ref:
        return ref.rsplit("@", 1)[1]
    return None


def declared_references(graph: Any) -> List[Tuple[str, str]]:
    """Return (field, ref) for every qualified reference in a graph declaration."""
    if not isinstance(graph, dict):
        return []
    found: List[Tuple[str, str]] = []
    for name in _REFERENCE_FIELDS:
        value = graph.get(name)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if name == "observes" and item == "all":
                continue
            if isinstance(item, str):
                found.append((name, item))
    edges = graph.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, dict) and isinstance(edge.get("to"), str):
                found.append(("edges", edge["to"]))
    return found


def concept_name(plugin_name: str, prefix: str) -> str:
    stem = prefix + "-"
    if plugin_name.startswith(stem) and len(plugin_name) > len(stem):
        return plugin_name[len(stem):]
    return plugin_name


def is_marketplace_repository(directory) -> bool:
    """The test for a marketplace repository: manifest present and the directory is a git top level."""
    real = os.path.realpath(str(directory))
    if not os.path.isfile(os.path.join(real, ".claude-plugin", "marketplace.json")):
        return False
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=real, env=env, capture_output=True, text=True, check=False,
        )
    except OSError:
        return False
    top = result.stdout.strip()
    return result.returncode == 0 and bool(top) and os.path.realpath(top) == real


def _normal_dependencies(raw: Any) -> Tuple[List[dict], List[Any]]:
    """Return (normalised dependencies, entries that were not understood)."""
    normal: List[dict] = []
    odd: List[Any] = []
    if not isinstance(raw, list):
        return normal, ([raw] if raw is not None else odd)
    for item in raw:
        if isinstance(item, str):
            normal.append({"name": item, "marketplace": None, "version": None})
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            marketplace = item.get("marketplace")
            version = item.get("version")
            normal.append({
                "name": item["name"],
                "marketplace": marketplace if isinstance(marketplace, str) else None,
                "version": version if isinstance(version, str) else None,
            })
        else:
            odd.append(item)
    return normal, odd


@dataclass
class Plugin:
    name: str
    entry: dict
    source: Optional[str]
    dir: Optional[Path]
    version: Optional[str] = None
    manifest: Optional[dict] = None
    dependencies: List[dict] = field(default_factory=list)
    has_concept: bool = False


@dataclass
class Concept:
    """One concept plugin: a skills/concept/SKILL.md, with its Tier 2 files."""
    name: str
    plugin: Plugin
    marketplace: str
    skill: SkillDoc
    skill_relpath: str
    graph: Any
    participation_bullets: Optional[List[Tuple[str, str]]]
    contract_skill_exists: bool
    contract: Optional[dict]
    contract_relpath: str
    schema: Optional[dict]
    schema_relpath: str
    realizations: List["Realization"] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.name}@{self.marketplace}"

    @property
    def role(self) -> Any:
        """The declared role, or None for a capability (or a non-dict graph)."""
        if isinstance(self.graph, dict):
            return self.graph.get("role")
        return None

    @property
    def participation(self) -> Optional[dict]:
        if self.participation_bullets is None:
            return None
        return dict(self.participation_bullets)

    def references(self) -> List[Tuple[str, str]]:
        return declared_references(self.graph)


@dataclass
class Realization:
    """One realize-* skill, in its plugin's skills/ directory."""
    name: str
    plugin: Plugin
    dir: Path
    skill: SkillDoc
    skill_relpath: str
    graph: Any
    realizes: Optional[dict]
    realizes_error: Optional[str]
    concept_ref: Optional[str]
    default: bool
    schema: Optional[dict]
    schema_relpath: str


class Marketplace:
    """A loaded marketplace repository. Build one with Marketplace.load(root)."""

    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.manifest = manifest
        self.name: str = manifest["name"]
        self.prefix: str = self.name.split("-", 1)[0]
        self.plugins: Dict[str, Plugin] = {}
        self.concepts: Dict[str, Concept] = {}
        self.realizations: List[Realization] = []
        self.findings: List[Finding] = []
        self.compiled: Optional[dict] = None
        self.compiled_path: Path = root / COMPILED_FILE

    @classmethod
    def load(cls, root) -> "Marketplace":
        root = Path(root).resolve()
        manifest_path = root / ".claude-plugin" / "marketplace.json"
        if not manifest_path.is_file():
            raise MarketplaceError(f"{root} has no .claude-plugin/marketplace.json")
        try:
            manifest = load_json(manifest_path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise MarketplaceError(f".claude-plugin/marketplace.json is not valid JSON: {exc}") from None
        if not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str) or not manifest["name"]:
            raise MarketplaceError(".claude-plugin/marketplace.json needs a non-empty string 'name'")
        marketplace = cls(root, manifest)
        marketplace._load_plugins()
        marketplace._load_skills()
        marketplace._load_compiled()
        return marketplace

    # -- paths and findings ------------------------------------------------

    def rel(self, path) -> str:
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def _find(self, check: str, severity: str, path, message: str, fix: str = "") -> None:
        file = self.rel(path) if path is not None else None
        self.findings.append(Finding(check, severity, file, message, fix))

    def _read_json(self, path: Path) -> Optional[Any]:
        if not path.is_file():
            return None
        try:
            return load_json(path)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self._find("F-files", "block", path, f"file is not valid JSON: {exc}",
                       "fix the JSON syntax of this file")
            return None

    # -- loading -----------------------------------------------------------

    def _load_plugins(self) -> None:
        entries = self.manifest.get("plugins", [])
        if not isinstance(entries, list):
            self._find("F-files", "block", self.root / ".claude-plugin" / "marketplace.json",
                       "'plugins' must be a list", "make 'plugins' a list of plugin entries")
            return
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                self._find("F-files", "block", self.root / ".claude-plugin" / "marketplace.json",
                           "a plugin entry has no string 'name'", "give every plugin entry a name")
                continue
            name = entry["name"]
            if name in self.plugins:
                self._find("F-files", "block", self.root / ".claude-plugin" / "marketplace.json",
                           f"two plugin entries are named {name!r}", "give each plugin a unique name")
                continue
            source = entry.get("source")
            plugin_dir = self._plugin_dir(name, source)
            plugin = Plugin(name=name, entry=entry,
                            source=source if isinstance(source, str) else None, dir=plugin_dir)
            deps, odd = _normal_dependencies(entry.get("dependencies"))
            plugin.dependencies.extend(deps)
            if odd:
                self._find("F-files", "warn", self.root / ".claude-plugin" / "marketplace.json",
                           f"plugin {name!r} has dependency entries that are not understood",
                           "use a plugin name string or {name, marketplace, version}")
            if plugin_dir is not None:
                manifest = self._read_json(plugin_dir / ".claude-plugin" / "plugin.json")
                if isinstance(manifest, dict):
                    plugin.manifest = manifest
                    if isinstance(manifest.get("version"), str):
                        plugin.version = manifest["version"]
                    more, _ = _normal_dependencies(manifest.get("dependencies"))
                    plugin.dependencies.extend(more)
            self.plugins[name] = plugin

    def _plugin_dir(self, name: str, source: Any) -> Optional[Path]:
        if not isinstance(source, str) or not source.startswith("./"):
            self._find("F-files", "warn", self.root / ".claude-plugin" / "marketplace.json",
                       f"plugin {name!r} has a source that is not a relative path; its files are not read",
                       "use a relative source such as ./plugins/" + name)
            return None
        path = Path(os.path.normpath(self.root / source))
        try:
            path.relative_to(self.root)
        except ValueError:
            self._find("F-files", "block", self.root / ".claude-plugin" / "marketplace.json",
                       f"plugin {name!r} has a source outside the marketplace",
                       "point the source inside this repository")
            return None
        if not path.is_dir():
            self._find("F-files", "block", self.root / ".claude-plugin" / "marketplace.json",
                       f"plugin {name!r} source directory does not exist: {source}",
                       "create the plugin directory or correct the source")
            return None
        return path

    def _load_skills(self) -> None:
        for plugin_name in sorted(self.plugins):
            plugin = self.plugins[plugin_name]
            if plugin.dir is None:
                continue
            skills = plugin.dir / "skills"
            concept_skill = skills / "concept" / "SKILL.md"
            if concept_skill.is_file():
                plugin.has_concept = True
                cname = concept_name(plugin.name, self.prefix)
                if cname in self.concepts:
                    self._find("AD1", "block", concept_skill,
                               f"concept {cname!r} is already defined by plugin "
                               f"{self.concepts[cname].plugin.name!r}",
                               "rename one of the two plugins under the marketplace's own prefix")
                else:
                    self.concepts[cname] = self._load_concept(plugin, cname, concept_skill)
            if skills.is_dir():
                for child in sorted(skills.iterdir()):
                    if child.is_dir() and child.name.startswith("realize-") and (child / "SKILL.md").is_file():
                        self.realizations.append(self._load_realization(plugin, child))
        for concept in self.concepts.values():
            concept.realizations = [r for r in self.realizations if r.concept_ref == concept.id]

    def _load_concept(self, plugin: Plugin, cname: str, skill_path: Path) -> Concept:
        skill = read_skill(skill_path)
        if skill.error:
            self._find("F-files", "block", skill_path,
                       f"concept skill front matter cannot be read: {skill.error}",
                       "fix the YAML of the front matter in this file")
        graph = skill.frontmatter.get("graph") if skill.frontmatter else None
        bullets = participation_bullets(skill.body)
        contract_dir = plugin.dir / "skills" / "realization-contract"
        contract = self._read_json(contract_dir / "graph-contract.json")
        schema = self._read_json(contract_dir / "schema.json")
        if contract is not None and not isinstance(contract, dict):
            contract = None
        if schema is not None and not isinstance(schema, dict):
            schema = None
        return Concept(
            name=cname,
            plugin=plugin,
            marketplace=self.name,
            skill=skill,
            skill_relpath=self.rel(skill_path),
            graph=graph,
            participation_bullets=bullets,
            contract_skill_exists=(contract_dir / "SKILL.md").is_file(),
            contract=contract,
            contract_relpath=self.rel(contract_dir / "graph-contract.json"),
            schema=schema,
            schema_relpath=self.rel(contract_dir / "schema.json"),
        )

    def _load_realization(self, plugin: Plugin, directory: Path) -> Realization:
        skill_path = directory / "SKILL.md"
        skill = read_skill(skill_path)
        if skill.error:
            self._find("F-files", "block", skill_path,
                       f"realization front matter cannot be read: {skill.error}",
                       "fix the YAML of the front matter in this file")
        front = skill.frontmatter or {}
        realizes = None
        realizes_error = None
        try:
            realizes = realizes_block(skill.body)
        except ValueError as exc:
            realizes_error = str(exc)
            self._find("F-files", "block", skill_path, f"'realizes' block cannot be read: {exc}",
                       "keep the 'realizes' block to a flat mapping of scalars")
        name = directory.name[len("realize-"):]
        if realizes is not None and isinstance(realizes.get("name"), str):
            name = realizes["name"]
        concept_ref = None
        if realizes is not None and isinstance(realizes.get("concept"), str):
            concept_ref = realizes["concept"]
        elif realizes is None and plugin.has_concept:
            concept_ref = f"{concept_name(plugin.name, self.prefix)}@{self.name}"
        schema = self._read_json(directory / "schema.json")
        if schema is not None and not isinstance(schema, dict):
            schema = None
        return Realization(
            name=name,
            plugin=plugin,
            dir=directory,
            skill=skill,
            skill_relpath=self.rel(skill_path),
            graph=front.get("graph"),
            realizes=realizes,
            realizes_error=realizes_error,
            concept_ref=concept_ref,
            default=front.get("default") is True,
            schema=schema,
            schema_relpath=self.rel(directory / "schema.json"),
        )

    def _load_compiled(self) -> None:
        if not self.compiled_path.is_file():
            return
        value = self._read_json(self.compiled_path)
        if value is None:
            self._find("F-compiled", "block", self.compiled_path,
                       "concept-graph.json cannot be read", "run the compiler again with --compile")
            return
        self.compiled = value if isinstance(value, dict) else None
        if self.compiled is None:
            self._find("F-compiled", "block", self.compiled_path,
                       "concept-graph.json is not a JSON object", "run the compiler again with --compile")

    # -- queries -----------------------------------------------------------

    def concept_id(self, name: str) -> str:
        return f"{name}@{self.name}"

    def direct_upstreams(self) -> List[str]:
        """Names of the marketplaces this one declares a dependency on or references."""
        names = set()
        for plugin in self.plugins.values():
            for dep in plugin.dependencies:
                if dep.get("marketplace"):
                    names.add(dep["marketplace"])
        for concept in self.concepts.values():
            for _, ref in concept.references():
                names.add(qualifier(ref))
        for realization in self.realizations:
            if realization.concept_ref:
                names.add(qualifier(realization.concept_ref))
        names.discard(None)
        names.discard(self.name)
        names.discard(WORKSPACE_QUALIFIER)
        return sorted(names)

    def compiled_upstream_names(self) -> List[str]:
        if not isinstance(self.compiled, dict):
            return []
        entries = self.compiled.get("upstreams", [])
        if not isinstance(entries, list):
            return []
        return sorted({e["marketplace"] for e in entries
                       if isinstance(e, dict) and isinstance(e.get("marketplace"), str)} - {self.name})


@dataclass
class Context:
    """What each check receives. See the module docstring."""
    root: Path
    marketplace: Marketplace
    upstreams: Dict[str, Marketplace] = field(default_factory=dict)
    previous_graph: Optional[dict] = None
    options: Options = field(default_factory=Options)
    guidance_version: Optional[str] = None

    def __post_init__(self):
        self.root = Path(self.root)
        self.upstreams = dict(self.upstreams)

    @property
    def repo(self) -> Path:
        return Path(self.options.repo) if self.options.repo else self.root

    def upstream(self, name: str) -> Optional[Marketplace]:
        return self.upstreams.get(name)
