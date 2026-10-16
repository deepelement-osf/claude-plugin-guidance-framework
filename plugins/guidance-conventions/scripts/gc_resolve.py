#!/usr/bin/env python3
"""Find the upstream marketplaces a marketplace depends on, at the versions it needs.

resolve(marketplace, options, guidance) walks the chain from the marketplace.
For each upstream it names, it reads the version the dependent needs, then looks
in these places, in this order, and takes the first copy that holds those
versions:

  (a) the directory given by --upstreams, as DIR/<name>. A copy found there is
      used as it is, so an explicit directory always wins; X-versions still
      compares its versions with the declared ranges;
  (b) Claude Code's registered copy, <marketplaces>/<name>, where <marketplaces>
      is GUIDANCE_CHECK_MARKETPLACES_DIR or ~/.claude/plugins/marketplaces;
  (c) the cache, <data>/upstreams/<name>, where <data> is CLAUDE_PLUGIN_DATA or
      ~/.cache/guidance-conventions;
  (d) a fetch from the source that the repository's .claude/settings.json
      registers for <name>. Each needed plugin is fetched from its own
      <plugin>--v<version> tag and verified there. The assembled copy takes
      marketplace.json and concept-graph.json from the tag with the newest version,
      and each other needed plugin's directory from its own tag. It is stored in
      the cache, and only after it verifies.

The version a copy must hold is the one the dependent's compiled graph records
for it (decision 10), or, when nothing is recorded or the script compiles, the
newest version within the declared range. Only when a version has to be chosen
does the script list tags, through the source's ls-remote.

A copy whose .claude-plugin/guidance.json is not valid is not used, because AD2
compares the upstream's plugin-name prefix, and the loader would silently fall
back to the default prefix.

Exit 2 (ResolveError) only when none of (a) to (d) gives a copy. The message
says what was tried, in order.

A marketplace reached by two dependents is resolved once, against the first
dependent that names it. A later dependent's versions are still checked by
X-versions against the recorded graph.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gc_checks_f import guidance_findings  # noqa: E402
from gc_checks_x import parse_range, parse_version, satisfies  # noqa: E402
from gc_model import GUIDANCE_FILE, GUIDANCE_MARKETPLACE, Marketplace, MarketplaceError, Options  # noqa: E402
from gc_parse import load_json  # noqa: E402

SETTINGS_RELPATH = ".claude/settings.json"
MARKETPLACES_ENV = "GUIDANCE_CHECK_MARKETPLACES_DIR"
DATA_ENV = "CLAUDE_PLUGIN_DATA"
GIT_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


class ResolveError(Exception):
    """An upstream cannot be found, fetched or verified. The caller decides the exit code."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message = message
        self.fix = fix


@dataclass
class _Need:
    """What one dependent needs from one plugin of an upstream."""
    plugin: str
    range: Optional[str]      # the declared dependency range, or None
    recorded: Optional[str]   # the version the dependent's compiled graph records, or None


# -- locations ----------------------------------------------------------------

def _registered_root() -> Path:
    override = os.environ.get(MARKETPLACES_ENV)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "plugins" / "marketplaces"


def _cache_root() -> Path:
    data = os.environ.get(DATA_ENV)
    if data:
        return Path(data) / "upstreams"
    return Path.home() / ".cache" / "guidance-conventions" / "upstreams"


def _guidance_problem(marketplace: Marketplace) -> Optional[str]:
    """Why the marketplace's guidance.json makes it unusable as an upstream, or None."""
    findings = guidance_findings(marketplace)
    if not findings:
        return None
    return f"its {GUIDANCE_FILE} is not valid: " + "; ".join(f.message for f in findings)


def _source_url(repo: Path, name: str) -> Optional[str]:
    """The git URL that the repository's settings register for marketplace name, or None.

    A github source is owner/repo; a git source is its url. Other kinds give None.
    """
    path = Path(repo) / SETTINGS_RELPATH
    if not path.is_file():
        return None
    try:
        settings = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ResolveError(f"{path} is not readable JSON: {exc}",
                           "fix the JSON syntax of .claude/settings.json") from None
    if not isinstance(settings, dict):
        return None
    known = settings.get("extraKnownMarketplaces")
    entry = known.get(name) if isinstance(known, dict) else None
    source = entry.get("source") if isinstance(entry, dict) else None
    if not isinstance(source, dict):
        return None
    kind = source.get("source")
    if kind == "github" and isinstance(source.get("repo"), str) and source["repo"]:
        return f"https://github.com/{source['repo']}.git"
    if kind in ("git", "url") and isinstance(source.get("url"), str) and source["url"]:
        return source["url"]
    return None


# -- git ----------------------------------------------------------------------

def _run_git(args: List[str], cwd=None) -> Optional[subprocess.CompletedProcess]:
    env = {k: v for k, v in os.environ.items() if k not in GIT_OVERRIDES}
    try:
        return subprocess.run(["git", *args], cwd=None if cwd is None else str(cwd), env=env,
                              capture_output=True, text=True, check=False)
    except OSError:
        return None


def _local_tags(directory: Path) -> Optional[List[str]]:
    """The tags of a checkout, or None when directory is not a git checkout that git can list."""
    if not (Path(directory) / ".git").exists():
        return None
    result = _run_git(["tag", "--list"], cwd=directory)
    if result is None or result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _remote_tags(url: str) -> List[str]:
    result = _run_git(["ls-remote", "--tags", url])
    if result is None or result.returncode != 0:
        detail = "git is not available" if result is None else result.stderr.strip()
        raise ResolveError(f"cannot list the tags of {url}: {detail}",
                           "check the source in .claude/settings.json and the network")
    tags = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        tag = parts[1][len("refs/tags/"):]
        if tag.endswith("^{}"):
            tag = tag[:-3]
        tags.add(tag)
    return sorted(tags)


# -- the dependent's view -----------------------------------------------------

def _needs(dependent: Marketplace, name: str) -> List[_Need]:
    ranges: Dict[str, Optional[str]] = {}
    for plugin in dependent.plugins.values():
        for dep in plugin.dependencies:
            if dep.get("marketplace") != name or not isinstance(dep.get("name"), str):
                continue
            version = dep.get("version") if isinstance(dep.get("version"), str) else None
            if ranges.get(dep["name"]) is None:
                ranges[dep["name"]] = version
    recorded = _recorded_of(dependent, name)
    return [_Need(plugin, ranges.get(plugin), recorded.get(plugin))
            for plugin in sorted(set(ranges) | set(recorded))]


def _recorded_of(dependent: Marketplace, name: str) -> Dict[str, str]:
    compiled = dependent.compiled
    entries = compiled.get("upstreams") if isinstance(compiled, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("marketplace") == name:
            plugins = entry.get("plugins")
            if isinstance(plugins, dict):
                return {k: v for k, v in plugins.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


# -- the resolver -------------------------------------------------------------

_ADD_SOURCE_FIX = ("add {name} to extraKnownMarketplaces in " + SETTINGS_RELPATH + " with a source, "
                   "or check it out under its own name and pass the parent directory with --upstreams")


def _nothing_found(name: str, tried: List[str]) -> str:
    return f"upstream marketplace {name!r} could not be found; tried, in order: " + "; ".join(tried)

class _Resolver:
    def __init__(self, marketplace: Marketplace, options: Options, guidance: str):
        self.marketplace = marketplace
        self.options = options
        self.guidance = guidance
        self.repo = Path(options.repo) if options.repo else marketplace.root
        self.upstreams_dir = Path(options.upstreams_dir) if options.upstreams_dir else None
        self.compile = bool(getattr(options, "compile", False))

    def run(self) -> Dict[str, Marketplace]:
        loaded: Dict[str, Marketplace] = {}
        queue = deque([self.marketplace])
        while queue:
            dependent = queue.popleft()
            for name in dependent.direct_upstreams():
                if name in loaded or name in (self.marketplace.name, self.guidance):
                    continue
                upstream = self._acquire(name, _needs(dependent, name))
                loaded[name] = upstream
                queue.append(upstream)
        return loaded

    # -- one upstream ---------------------------------------------------------

    def _acquire(self, name: str, needs: List[_Need]) -> Marketplace:
        tried: List[str] = []
        if self.upstreams_dir is not None:
            candidate = self.upstreams_dir / name
            if candidate.is_dir():
                return self._load_given(candidate, name)
            tried.append(f"--upstreams: {candidate} is not present")
        else:
            tried.append("--upstreams: not given")

        version_error: Optional[ResolveError] = None
        targets: Dict[str, str] = {}
        try:
            targets = self._targets(name, needs)
        except ResolveError as exc:
            version_error = exc
            tried.append(f"version: {exc.message}")
        registered = _registered_root() / name
        cache = _cache_root() / name
        for label, directory in (("Claude Code's registered copy", registered), ("the cache", cache)):
            if not directory.is_dir():
                tried.append(f"{label}: {directory} is not present")
                continue
            if version_error is not None:
                tried.append(f"{label}: {directory} is not checked, because no version could be chosen")
                continue
            found, reason = self._check(directory, name, targets)
            if found is not None:
                return found
            tried.append(f"{label}: {directory} is not usable, because {reason}")

        if version_error is not None:
            tried.append("fetch: not tried, because no version could be chosen")
            raise ResolveError(_nothing_found(name, tried), version_error.fix)

        url = _source_url(self.repo, name)
        if url is None:
            tried.append(f"fetch: {SETTINGS_RELPATH} registers no source for {name}")
            raise ResolveError(_nothing_found(name, tried), _ADD_SOURCE_FIX.format(name=name))
        tried.append(f"fetch: from {url}")
        return self._fetch(name, url, targets)

    def _load_given(self, candidate: Path, name: str) -> Marketplace:
        try:
            upstream = Marketplace.load(candidate)
        except MarketplaceError as exc:
            raise ResolveError(f"upstream {name!r}: {exc}",
                               f"make {candidate} a marketplace repository") from None
        if upstream.name != name:
            raise ResolveError(f"{candidate} holds marketplace {upstream.name!r}, not {name!r}",
                               "check out the upstream named in the marketplace's dependencies")
        problem = _guidance_problem(upstream)
        if problem is not None:
            raise ResolveError(f"upstream {name!r} at {candidate}: {problem}",
                               f"fix {GUIDANCE_FILE} in {name}, because AD2 compares its plugin-name prefix")
        return upstream

    def _targets(self, name: str, needs: List[_Need]) -> Dict[str, str]:
        """The version each needed plugin must have in the copy. Plugins with no version are omitted."""
        targets: Dict[str, str] = {}
        for need in needs:
            if self.compile:
                targets[need.plugin] = self._newest(name, need)
            elif need.recorded is not None:
                targets[need.plugin] = need.recorded
            elif need.range is not None:
                targets[need.plugin] = self._newest(name, need)
        return targets

    def _newest(self, name: str, need: _Need) -> str:
        """The newest version of the plugin within the range. Lists tags only when this is called."""
        rng = need.range if need.range is not None else "*"
        if parse_range(rng) is None:
            raise ResolveError(f"the range {rng} of {need.plugin} from {name} is not understood",
                               "use a caret, tilde or comparator range")
        url = _source_url(self.repo, name)
        if url is not None:
            tags = _remote_tags(url)
        else:
            tags = None
            for directory in self._checkouts(name):
                tags = _local_tags(directory)
                if tags is not None:
                    break
            if tags is None:
                raise ResolveError(
                    f"cannot list the versions of {need.plugin} from {name}: no source is registered "
                    f"and no checkout with tags is present",
                    f"register a source for {name} in {SETTINGS_RELPATH}")
        prefix = f"{need.plugin}--v"
        candidates = []
        for tag in tags:
            if not tag.startswith(prefix):
                continue
            text = tag[len(prefix):]
            if parse_version(text) is not None and satisfies(text, rng) is True:
                candidates.append(text)
        if not candidates:
            raise ResolveError(f"no version of {need.plugin} from {name} satisfies {rng}",
                               "check the dependency range, or publish a version that satisfies it")
        return max(candidates, key=parse_version)

    def _checkouts(self, name: str) -> List[Path]:
        found = []
        if self.upstreams_dir is not None:
            found.append(self.upstreams_dir / name)
        found.append(_registered_root() / name)
        found.append(_cache_root() / name)
        return [path for path in found if path.is_dir()]

    def _check(self, directory: Path, name: str, targets: Dict[str, str]) -> Tuple[Optional[Marketplace], str]:
        try:
            marketplace = Marketplace.load(directory)
        except MarketplaceError as exc:
            return None, f"it is not a marketplace repository ({exc})"
        if marketplace.name != name:
            return None, f"it holds marketplace {marketplace.name!r}"
        problem = _guidance_problem(marketplace)
        if problem is not None:
            return None, problem
        for plugin, version in sorted(targets.items()):
            found = marketplace.plugins.get(plugin)
            if found is None:
                return None, f"it has no plugin {plugin}"
            if found.version != version:
                return None, f"it has {plugin} {found.version}, and {version} is needed"
        return marketplace, ""

    def _fetch(self, name: str, url: str, targets: Dict[str, str]) -> Marketplace:
        cache_root = _cache_root()
        cache_root.mkdir(parents=True, exist_ok=True)
        staging = cache_root / f".{name}.staging-{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        try:
            assembled = self._assemble(name, url, targets, staging)
            cache = cache_root / name
            if cache.is_dir() and not cache.is_symlink():
                shutil.rmtree(cache)
            elif cache.exists() or cache.is_symlink():
                cache.unlink()
            os.replace(assembled, cache)
            fetched = Marketplace.load(cache)
            problem = _guidance_problem(fetched)
            if problem is not None:
                raise ResolveError(f"upstream {name!r} fetched from {url}: {problem}",
                                   f"fix {GUIDANCE_FILE} in {name}, because AD2 compares its plugin-name prefix")
            return fetched
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _assemble(self, name: str, url: str, targets: Dict[str, str], staging: Path) -> Path:
        """Fetch what the targets need into staging, and return the assembled marketplace directory.

        Each needed plugin is cloned from its own <plugin>--v<version> tag and checked there.
        The clone of the tag with the newest version is the base: its marketplace.json and
        concept-graph.json are the assembled ones, and every other needed plugin's directory
        is replaced by the one from its own tag. With no targets, the base is the default branch.
        The assembled copy is checked again before it is returned.
        """
        base_dir = staging / "assembled"
        if not targets:
            self._clone(name, url, None, base_dir)
            found, reason = self._check(base_dir, name, targets)
            if found is None:
                raise ResolveError(f"the fetched {name} from {url} is not usable, because {reason}",
                                   "publish the tag for the version the dependent needs, or fix the source")
            return base_dir

        plugins = sorted(targets)
        newest = max(plugins, key=lambda plugin: (parse_version(targets[plugin]) or (), plugin))
        clones: Dict[str, Tuple[Path, Marketplace]] = {}
        for plugin in plugins:
            tag = f"{plugin}--v{targets[plugin]}"
            directory = base_dir if plugin == newest else staging / "tags" / tag
            self._clone(name, url, tag, directory)
            found, reason = self._check(directory, name, {plugin: targets[plugin]})
            if found is None:
                raise ResolveError(f"the fetched {name} from {url} is not usable at tag {tag}, because {reason}",
                                   "publish the tag for the version the dependent needs, or fix the source")
            clones[plugin] = (directory, found)

        _, base = clones[newest]
        for plugin in plugins:
            if plugin == newest:
                continue
            _, source = clones[plugin]
            plugin_dir = source.plugins[plugin].dir
            entry = base.plugins.get(plugin)
            if entry is not None and entry.dir is not None:
                destination = entry.dir
            else:
                destination = Path(os.path.normpath(base_dir / source.plugins[plugin].source))
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            elif destination.is_dir():
                shutil.rmtree(destination)
            shutil.copytree(plugin_dir, destination, symlinks=True)

        found, reason = self._check(base_dir, name, targets)
        if found is None:
            raise ResolveError(f"the fetched {name} from {url} is not usable, because {reason}",
                               "publish the tag for the version the dependent needs, or fix the source")
        return base_dir

    def _clone(self, name: str, url: str, tag: Optional[str], directory: Path) -> None:
        directory.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", "1"]
        if tag is not None:
            args += ["--branch", tag]
        args += [url, str(directory)]
        result = _run_git(args)
        if result is None or result.returncode != 0:
            detail = "git is not available" if result is None else result.stderr.strip()
            where = "" if tag is None else f" at tag {tag}"
            raise ResolveError(f"cannot fetch {name} from {url}{where}: {detail}",
                               "check the source in .claude/settings.json, the network, and that the tag exists")


def resolve(marketplace: Marketplace, options: Options, guidance: str = GUIDANCE_MARKETPLACE) -> Dict[str, Marketplace]:
    """Every upstream marketplace of marketplace, transitively, keyed by name.

    Raises ResolveError when one cannot be found, fetched or verified.
    """
    return _Resolver(marketplace, options, guidance).run()
