"""Set M, set U and AD1 to AD2: the mechanical parts of the marketplace conventions.

Standard library only. run(ctx) returns the findings of these checks:

    M1    a plugin entry with a relative-path source resolves to a directory (block)
    M2    every plugin name starts with the marketplace's prefix (warn)
    M3    README.md and LICENSE exist at the root, and the README refers to LICENSE (block)
    U1    a cross-marketplace dependency sits in a marketplace entry, not in plugin.json (block)
    U2    a cross-marketplace dependency is an object with a version (block);
          a version that is textually open-ended warns
    U3    every marketplace an entry depends on is in the root allowlist (block)
    U4    the README has the Required marketplaces section in the template's form, with a
          row for each allowlisted marketplace whose plugin names match the entries (block);
          a row whose range text differs from the entry's version warns
    AD1   each concept name is defined by one plugin (block)
    AD2   no plugin name, concept name or prefix equals one of a resolved upstream (block)

The judgement parts of these checks (the name in M1, the README content in M3, M4 and
M5) belong to the skills and are never reported here. The guidance marketplace is neither
an upstream nor a cross-marketplace dependency here; set A8 reports a dependency on it.

The prefix is Marketplace.prefix, which honours metadata.pluginPrefix. A concept's name is
its plugin's name without "<prefix>-" (concept_name in gc_model).
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from gc_model import Context, Finding, Marketplace, concept_name
from gc_parse import load_json

GUIDANCE_MARKETPLACE = "claude-plugin-guidance"
MANIFEST_FILE = ".claude-plugin/marketplace.json"
README_FILE = "README.md"
LICENSE_FILE = "LICENSE"
ALLOWLIST_KEY = "allowCrossMarketplaceDependenciesOn"
SECTION_HEADING = "## Required marketplaces"
TABLE_COLUMNS = ["Marketplace name", "Registration source", "Plugins used (range)", "Why"]
OPEN_ENDED_VERSIONS = ("", "*", "x", "X", "latest", ">=")
_MISSING = object()


class _Dependency(NamedTuple):
    """One cross-marketplace dependency, as it is written."""
    file: str                   # the file that declares it, relative to the marketplace root
    plugin: str                 # the plugin that declares it
    marketplace: str            # the marketplace it names
    name: Optional[str]         # the plugin it names, None when the object has no name
    string_form: bool           # written as "name@marketplace"
    version: Any                # the version, or _MISSING when the key is absent
    in_entry: bool              # declared in the marketplace entry (True) or plugin.json (False)


class _Name(NamedTuple):
    """One name that the additive-only rule compares: a plugin name, a concept name or a prefix."""
    value: str
    kind: str                   # "plugin name", "concept name" or "prefix"
    owner: str                  # the plugin, or the marketplace for a prefix
    file: str


# -- reading the marketplace -------------------------------------------------

def _entries(marketplace: Marketplace) -> List[dict]:
    """The plugin entries that have a string name. A repeated name is read once."""
    raw = marketplace.manifest.get("plugins", [])
    if not isinstance(raw, list):
        return []
    found: List[dict] = []
    seen = set()
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"] not in seen:
            seen.add(entry["name"])
            found.append(entry)
    return found


def _relative(entry: dict) -> bool:
    """True when the entry's source is a relative path, which is what M1 checks."""
    source = entry.get("source")
    return isinstance(source, str) and (source.startswith("./") or source.startswith("../"))


def _source_dir(marketplace: Marketplace, entry: dict) -> Optional[Path]:
    """The directory a relative-path source names, inside the repository, or None."""
    if not _relative(entry):
        return None
    path = Path(os.path.normpath(str(marketplace.root / entry["source"])))
    try:
        path.relative_to(marketplace.root)
    except ValueError:
        return None
    return path if path.is_dir() else None


def _is_concept(path: Optional[Path]) -> bool:
    return path is not None and (path / "skills" / "concept" / "SKILL.md").is_file()


def _plugin_json(path: Optional[Path]) -> Optional[dict]:
    if path is None or not (path / ".claude-plugin" / "plugin.json").is_file():
        return None
    try:
        value = load_json(path / ".claude-plugin" / "plugin.json")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _allowlist(marketplace: Marketplace) -> Optional[List[str]]:
    """The root allowlist as a list of names, or None when the root has no allowlist."""
    raw = marketplace.manifest.get(ALLOWLIST_KEY)
    if not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, str)]


def _dependency_items(raw: Any, plugin: str, file: str, in_entry: bool, own: str) -> List[_Dependency]:
    """The cross-marketplace dependencies in one dependencies list."""
    if not isinstance(raw, list):
        return []
    found: List[_Dependency] = []
    for item in raw:
        if isinstance(item, str):
            if "@" in item:
                name, marketplace = item.rsplit("@", 1)
            else:
                name, marketplace = item, None
            string_form, version = True, None
        elif isinstance(item, dict):
            name = item.get("name") if isinstance(item.get("name"), str) else None
            marketplace = item.get("marketplace") if isinstance(item.get("marketplace"), str) else None
            string_form, version = False, item.get("version", _MISSING)
        else:
            continue
        if not marketplace or marketplace in (own, GUIDANCE_MARKETPLACE):
            continue
        found.append(_Dependency(file, plugin, marketplace, name or None, string_form, version, in_entry))
    return found


def _declared(marketplace: Marketplace) -> List[_Dependency]:
    """Every cross-marketplace dependency in the entries and in each plugin.json."""
    found: List[_Dependency] = []
    for entry in _entries(marketplace):
        name = entry["name"]
        found.extend(_dependency_items(entry.get("dependencies"), name, MANIFEST_FILE, True, marketplace.name))
        path = _source_dir(marketplace, entry)
        manifest = _plugin_json(path)
        if manifest is not None:
            file = marketplace.rel(path / ".claude-plugin" / "plugin.json")
            found.extend(_dependency_items(manifest.get("dependencies"), name, file, False, marketplace.name))
    return found


# -- set M -------------------------------------------------------------------

def plugin_names_ok(name: str, prefix: str) -> bool:
    return name.startswith(prefix + "-") and len(name) > len(prefix) + 1


def _m1(marketplace: Marketplace, findings: List[Finding]) -> None:
    for entry in _entries(marketplace):
        if not _relative(entry):
            continue
        if _source_dir(marketplace, entry) is None:
            findings.append(Finding(
                "M1", "block", MANIFEST_FILE,
                f"plugin {entry['name']} has source {entry['source']}, which is not a directory in this repository",
                "create the plugin directory under plugins/, or correct the source"))


def _m2(marketplace: Marketplace, upstreams: Dict[str, Marketplace], findings: List[Finding]) -> None:
    prefix = marketplace.prefix
    # An upstream that uses the same prefix makes "<prefix>-<concept>" a name AD2 blocks,
    # so the fix must move this marketplace to a different prefix instead.
    shared = sorted(name for name, upstream in upstreams.items() if upstream.prefix == prefix)
    for entry in _entries(marketplace):
        name = entry["name"]
        if name.startswith("guidance-") and marketplace.name != GUIDANCE_MARKETPLACE:
            problem = "uses guidance-, which is reserved for the guidance marketplace"
            fix = f"rename the plugin under this marketplace's prefix, {prefix}-<concept>"
        elif not plugin_names_ok(name, prefix):
            problem = f"does not start with the marketplace prefix {prefix}-"
            if shared:
                fix = (f"declare metadata.pluginPrefix in {MANIFEST_FILE} with a value other than {prefix!r}, "
                       f"which upstream {', '.join(shared)} uses, and name the plugin under that new prefix; "
                       f"do not rename it {prefix}-<concept>, which AD2 still reports")
            else:
                fix = f"name the plugin {prefix}-<concept>, or declare metadata.pluginPrefix"
        else:
            continue
        findings.append(Finding("M2", "warn", MANIFEST_FILE, f"plugin {name} {problem}", fix))


def _m3(marketplace: Marketplace, findings: List[Finding]) -> None:
    names = set(os.listdir(marketplace.root))
    if LICENSE_FILE not in names:
        findings.append(Finding("M3", "block", LICENSE_FILE, "the repository root has no LICENSE file",
                                "add the license file at the root"))
    if README_FILE not in names:
        findings.append(Finding("M3", "block", README_FILE, "the repository root has no README.md",
                                "add README.md at the root"))
        return
    text = _read_text(marketplace.root / README_FILE) or ""
    if not re.search(r"\bLICENSE\b", text):
        findings.append(Finding("M3", "block", README_FILE, "README.md does not refer to the LICENSE file",
                                "say in the README where the license is, by naming the LICENSE file"))


# -- set U -------------------------------------------------------------------

def _u1(dependencies: List[_Dependency], findings: List[Finding]) -> None:
    for dep in dependencies:
        if not dep.in_entry:
            findings.append(Finding(
                "U1", "block", dep.file,
                f"plugin {dep.plugin} declares a dependency on {dep.name or '(unnamed)'} of {dep.marketplace} "
                "in plugin.json",
                "move the dependency to the plugin's entry in the marketplace manifest"))


def _u2(dependencies: List[_Dependency], findings: List[Finding]) -> None:
    for dep in dependencies:
        if dep.string_form:
            problem, fix = "is written in string form", "write it as an object with name, marketplace and version"
        elif dep.name is None:
            problem, fix = "is an object with no name", "give the object a name"
        elif dep.version is _MISSING:
            problem, fix = "is an object with no version", "add a version range, such as ^1.0.0"
        elif not isinstance(dep.version, str):
            problem, fix = "has a version that is not a string", "write the version as a range string"
        else:
            if _open_ended(dep.version):
                findings.append(Finding(
                    "U2", "warn", dep.file,
                    f"plugin {dep.plugin} depends on {dep.name} of {dep.marketplace} with the open-ended "
                    f"version {dep.version!r}, which is not parsed",
                    "use a bounded range, such as ^1.0.0"))
            continue
        findings.append(Finding(
            "U2", "block", dep.file,
            f"plugin {dep.plugin} depends on {dep.name or '(unnamed)'} of {dep.marketplace} and the dependency {problem}",
            fix))


def _u3(dependencies: List[_Dependency], allowlist: Optional[List[str]], findings: List[Finding]) -> None:
    named: Dict[str, List[str]] = {}
    for dep in dependencies:
        if dep.in_entry:
            plugins = named.setdefault(dep.marketplace, [])
            if dep.plugin not in plugins:
                plugins.append(dep.plugin)
    for marketplace in sorted(named):
        if allowlist is not None and marketplace in allowlist:
            continue
        if allowlist is None:
            problem = f"the root has no {ALLOWLIST_KEY}"
        else:
            problem = f"it is not in {ALLOWLIST_KEY}"
        findings.append(Finding(
            "U3", "block", MANIFEST_FILE,
            f"{marketplace} is named by the entries of {', '.join(named[marketplace])}, and {problem}",
            f"add {marketplace!r} to {ALLOWLIST_KEY} at the root"))


_RANGE_START = re.compile(r"[\^~<>=]")
_PLAIN_VERSION = re.compile(r"v?\d+(\.[\dxX*]+)*")
_SEPARATOR = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?")


def _open_ended(version: str) -> bool:
    """True when the version text is open-ended as the catalog defines it (empty, a wildcard, latest, or a bare >=)."""
    return version.strip() in OPEN_ENDED_VERSIONS


def _section_body(text: str) -> Optional[List[str]]:
    """The lines under the Required marketplaces heading, up to the next heading of level one or two."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == SECTION_HEADING:
            body: List[str] = []
            for later in lines[index + 1:]:
                if re.match(r"#{1,2}\s", later):
                    break
                body.append(later)
            return body
    return None


def _cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table(body: List[str]):
    """The header cells and the data rows of the first table in the section, or (None, [])."""
    lines = [line.strip() for line in body if line.strip().startswith("|")]
    if not lines:
        return None, []
    header = _cells(lines[0])
    rows = [_cells(line) for line in lines[1:] if not _SEPARATOR.fullmatch(line)]
    return header, rows


def _is_range(token: str) -> bool:
    """A backticked token that is a version range rather than a plugin name."""
    return (bool(_RANGE_START.match(token)) or bool(_PLAIN_VERSION.fullmatch(token))
            or token in ("*", "x", "X", "latest"))


def _row_plugins(cell: str) -> Dict[str, Optional[str]]:
    """Plugin names and their range text from the Plugins used cell. A name without a range maps to None."""
    listed: Dict[str, Optional[str]] = {}
    current: Optional[str] = None
    for token in re.findall(r"`([^`]*)`", cell):
        if _is_range(token):
            if current is not None:
                listed[current] = token
            current = None
        else:
            current = token
            listed.setdefault(token, None)
    return listed


def _u4(marketplace: Marketplace, dependencies: List[_Dependency], allowlist: Optional[List[str]],
        findings: List[Finding]) -> None:
    if not dependencies and not allowlist:
        return
    text = _read_text(marketplace.root / README_FILE)
    body = _section_body(text) if text is not None else None
    if body is None:
        findings.append(Finding(
            "U4", "block", README_FILE, f"README.md has no '{SECTION_HEADING}' section",
            "add the section in the template of architecture.md section 9"))
        return
    header, rows = _table(body)
    if header is None:
        findings.append(Finding(
            "U4", "block", README_FILE, "the Required marketplaces section has no table",
            "add the table in the template's columns, in the template's order"))
    elif header != TABLE_COLUMNS:
        findings.append(Finding(
            "U4", "block", README_FILE,
            f"the Required marketplaces table has the columns {header}, not the template's {TABLE_COLUMNS}",
            "use the template's heading text and column order"))
    by_name: Dict[str, List[str]] = {}
    for cells in rows:
        if cells:
            by_name.setdefault(cells[0].strip("`").strip(), cells)
    for name in allowlist or []:
        if name == GUIDANCE_MARKETPLACE:
            continue
        cells = by_name.get(name)
        if cells is None:
            findings.append(Finding(
                "U4", "block", README_FILE,
                f"the Required marketplaces section has no row for the allowlisted marketplace {name}",
                f"add a row for {name} with its registration source and the plugins it provides"))
            continue
        source = cells[1] if len(cells) > 1 else ""
        if not source.strip(" `"):
            findings.append(Finding(
                "U4", "block", README_FILE, f"the row for {name} gives no registration source",
                "give the registration source, such as a GitHub owner and repository"))
        listed = _row_plugins(cells[2] if len(cells) > 2 else "")
        expected = {dep.name: dep for dep in dependencies if dep.in_entry and dep.marketplace == name
                    and dep.name is not None}
        if set(listed) != set(expected):
            findings.append(Finding(
                "U4", "block", README_FILE,
                f"the row for {name} lists the plugins {sorted(listed)}, but the entries depend on "
                f"{sorted(expected)}",
                "make the plugin names in the row match the dependencies in the entries"))
        for plugin in sorted(set(listed) & set(expected)):
            version = expected[plugin].version
            if not isinstance(version, str) or listed[plugin] == version:
                continue
            findings.append(Finding(
                "U4", "warn", README_FILE,
                f"the row for {name} gives the range of {plugin} as {listed[plugin]!r}, "
                f"but the entry's version is {version!r}",
                "make the range text in the row equal the entry's version"))


# -- set AD ------------------------------------------------------------------

def _ad1(marketplace: Marketplace, findings: List[Finding]) -> None:
    prefix = marketplace.prefix
    defined: Dict[str, str] = {}
    for entry in _entries(marketplace):
        path = _source_dir(marketplace, entry)
        if not _is_concept(path):
            continue
        cname = concept_name(entry["name"], prefix)
        if cname in defined:
            findings.append(Finding(
                "AD1", "block", marketplace.rel(path / "skills" / "concept" / "SKILL.md"),
                f"concept {cname} is defined by plugin {defined[cname]} and by plugin {entry['name']}",
                "rename one of the two plugins under the marketplace's own prefix"))
        else:
            defined[cname] = entry["name"]


def _names(marketplace: Marketplace) -> List[_Name]:
    """The plugin names, concept names and prefix of one marketplace."""
    prefix = marketplace.prefix
    names: List[_Name] = []
    for entry in _entries(marketplace):
        name = entry["name"]
        path = _source_dir(marketplace, entry)
        plugin_file = path / ".claude-plugin" / "plugin.json" if path is not None else None
        file = marketplace.rel(plugin_file) if plugin_file is not None and plugin_file.is_file() else MANIFEST_FILE
        names.append(_Name(name, "plugin name", name, file))
        if _is_concept(path):
            names.append(_Name(concept_name(name, prefix), "concept name", name,
                               marketplace.rel(path / "skills" / "concept" / "SKILL.md")))
    names.append(_Name(prefix, "prefix", marketplace.name, MANIFEST_FILE))
    return names


def _ad2(marketplace: Marketplace, upstreams: Dict[str, Marketplace], findings: List[Finding]) -> None:
    mine = _names(marketplace)
    for upstream_name in sorted(upstreams):
        upstream = upstreams[upstream_name]
        theirs: Dict[str, _Name] = {}
        for item in _names(upstream):
            theirs.setdefault(item.value, item)
        reported = set()
        for item in mine:
            other = theirs.get(item.value)
            if other is None or item.value in reported:
                continue
            reported.add(item.value)
            if marketplace.prefix == upstream.prefix:
                fix = (f"declare metadata.pluginPrefix in {MANIFEST_FILE} with a value other than "
                       f"{upstream.prefix!r}, then name the plugin under that new prefix")
            else:
                fix = "rename it under this marketplace's own prefix, and declare that prefix in metadata.pluginPrefix"
            findings.append(Finding(
                "AD2", "block", item.file,
                f"{item.kind} {item.value} of {item.owner} equals the {other.kind} of {other.owner} "
                f"in upstream marketplace {upstream.name}",
                fix))


def run(ctx: Context) -> List[Finding]:
    """The findings of the mechanical parts of sets M and U and of AD1 and AD2."""
    marketplace = ctx.marketplace
    findings: List[Finding] = []
    dependencies = _declared(marketplace)
    allowlist = _allowlist(marketplace)
    _m1(marketplace, findings)
    _m2(marketplace, ctx.upstreams, findings)
    _m3(marketplace, findings)
    _u1(dependencies, findings)
    _u2(dependencies, findings)
    _u3(dependencies, allowlist, findings)
    _u4(marketplace, dependencies, allowlist, findings)
    _ad1(marketplace, findings)
    _ad2(marketplace, ctx.upstreams, findings)
    return findings
