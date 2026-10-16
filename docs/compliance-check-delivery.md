# How the compliance check is delivered

The compliance check is `guidance_check.py`, in the `guidance-conventions` plugin. It runs the
mechanical checks of the [check catalog](../spec/checks.md) on a marketplace repository. This
document says how the check reaches an author: the commit hook, the on-demand skill, and the
continuous integration (CI) gate. It also says which version each author runs.

The rows that define each check, with its pass rule, fail rule and severity, are in the
[check catalog](../spec/checks.md). What counts as a marketplace repository is in
[architecture section 12](./architecture.md#what-counts-as-a-marketplace-repository). This
document does not restate either.

Facts below were read from `guidance-conventions` 5.0.0 at commit `ab5460a`, tagged
`guidance-conventions--v5.0.0`.

## Where the check runs

The checks are meant for a marketplace repository: a git repository whose top level holds
`.claude-plugin/marketplace.json`. Two parts of the delivery apply that test differently.

- The commit hook applies the git test. It exits silently in a project directory that is not a
  marketplace repository, and runs nothing there. A manifest in a subdirectory, a submodule or a
  fixture does not qualify for the hook.
- The script does not apply the git test. It needs `.claude-plugin/marketplace.json` at the
  directory it is given, and it exits `2` with a `SCOPE` finding when that file is missing, is not
  valid JSON, or has no string `name`. Given a directory that holds a readable manifest, it runs the
  checks, whether or not that directory is a git top level. The gap between this and the spec is
  an open point, below.

## The three triggers

**1. A commit made through Claude Code: the `PreToolUse` hook.**

`hooks/hooks.json` registers `pre_commit_hook.py` on the `Bash` tool, with a timeout of 300
seconds. For each Bash call, the hook acts only when all of these hold:

- the project directory is a marketplace repository, as defined above;
- the command makes a commit, including `git -C <dir> commit` and a commit chained after other
  commands;
- the commit lands in the project repository.

Then the hook exports what the commit will contain and runs the script on that export with
`--json`, with the project's `.claude/settings.json` as the pin source (see
[the pin](#the-pin)).

- By default the export is the index as the commit will see it. A `git add` earlier in the same
  command is replayed on a copy of the index, and the real index is not written.
- With `-a` or `--all`, the export is the tracked files of the working copy.
- Index-changing commands other than `add` in the same chain (`git rm`, `git mv`, `git reset`)
  are not replayed.

Exit `0` lets the commit proceed. Exit `1`, or exit `2`, denies the tool call. The denial reason
carries the text report, so Claude Code can fix the findings and commit again. If the export
itself fails, the hook denies with a message that says the commit was not checked.

**2. On demand: the `validate-marketplace` skill.**

The skill runs the script on the repository first, then performs the judgement checks itself.
It reports the findings and blocks nothing. See the skill's own
[SKILL.md](../plugins/guidance-conventions/skills/validate-marketplace/SKILL.md).

**3. On each pull request: the CI gate.**

CI runs the script from the installed plugin and fails the job on exit `1` or `2`. The recipe is
in [Continuous integration for a marketplace repository](#continuous-integration-for-a-marketplace-repository).
A commit made from a terminal or an IDE skips the hook, so CI is the gate that every merge must
pass.

## The script

Run it from the plugin's directory, on the root of the marketplace repository:

```
python3 <plugin directory>/scripts/guidance_check.py [DIRECTORY]
```

| Option | Effect |
|---|---|
| `--json` | Print `{"exit": n, "findings": [...]}` instead of text. Each finding has `check`, `severity`, `file`, `message` and `fix`. |
| `--compile` | Write `concept-graph.json` at the repository root and stop. The checks do not run. Upstream resolution (below) still runs first. |
| `--no-official` | Skip the official validator (below). |
| `--no-pin` | Skip the pin check (below). |
| `--repo PATH` | Read the pin from this repository's `.claude/settings.json`. The default is the checked directory. |
| `--upstreams DIR`, `--previous DIR` | Locate upstream marketplaces and the previous compiled graph, for the checks that compare them. |

Exit codes:

| Exit | Meaning |
|---|---|
| `0` | Every check passed, possibly with warnings. |
| `1` | At least one blocking finding. |
| `2` | The check could not run: the directory has no readable `.claude-plugin/marketplace.json` with a `name` (`SCOPE`), an upstream cannot be resolved, the pin does not match, or the official validator cannot run. |

The official validator is part of the script. It runs
`claude plugin validate --json --strict` on the repository. It needs `claude` on `PATH`, and
Claude Code 2.1.259 or later, the first release whose validator accepts `--json`. An older
Claude Code, or a missing `claude`, exits `2`. The validator needs no model credentials. It was
run on Claude Code 2.1.301 with no API key and no OAuth token set, and it passed.

### Writes and network access

The script writes into the repository only under `--compile`, which writes `concept-graph.json` at
its root. Python also writes `__pycache__` beside the plugin's modules unless it runs with `-B`,
which the CI recipe below does. The commit hook and the skill run the same script, so they do the
same.

Every run resolves each upstream marketplace that the repository depends on, and that can use the
network and write a cache. The script tries these, in order, for each upstream `<name>`, and stops at
the first copy that holds the versions the repository needs:

1. `--upstreams DIR`: the copy at `DIR/<name>`, used as it is. Nothing is written.
2. Claude Code's registered copy at `$GUIDANCE_CHECK_MARKETPLACES_DIR/<name>`, or
   `~/.claude/plugins/marketplaces/<name>` when that variable is unset. Read only.
3. The cache at `$CLAUDE_PLUGIN_DATA/upstreams/<name>`, or
   `~/.cache/guidance-conventions/upstreams/<name>` when that variable is unset. Read only.
4. A fetch, when the first three give no usable copy and a version can be chosen. The script clones
   each needed plugin from its own `<plugin>--v<version>` tag, with `git clone --depth 1`, from the
   source that `.claude/settings.json` registers for the marketplace. It assembles a copy, stores it
   in the cache at `<name>`, and replaces the cache entry of that name.

A version has to be chosen under `--compile`, and for an upstream whose declared range has no
recorded version. Then the script lists that upstream's tags with `git ls-remote --tags` from the
registered source, or from a local checkout that has tags when no source is registered. It does
this before it looks at the copies in steps 2 and 3, and it does not do it when `--upstreams`
supplies the copy.

## The pin

Every author runs the same version of the check. The pin is in the marketplace repository's
committed `.claude/settings.json`, at `extraKnownMarketplaces.claude-plugin-guidance.source.ref`,
and it reads `guidance-conventions--v<version>`.

- A pin that names the script's own version passes.
- A pin that names another version makes the script halt with exit `2`. The message names the
  pinned version and the update commands: `claude plugin marketplace update claude-plugin-guidance`,
  then `claude plugin update guidance-conventions@claude-plugin-guidance`.
- No pin is a warning, and the run can still pass. The warning says that results can differ
  between authors.

A marketplace takes up a new check by moving its pin in a pull request.

## Continuous integration for a marketplace repository

The CI job needs no model and no model credentials. It must not set `ANTHROPIC_API_KEY`, an
OAuth token or any other credential. Config names a credential only by its environment variable,
and this recipe uses none.

1. Install Claude Code at 2.1.259 or later. Pin the exact version in the workflow. The example
   below uses 2.1.301, the version this recipe was run on.
2. Register guidance at the ref the committed settings pin. A CI job runs no session, so the
   `extraKnownMarketplaces` declaration is not applied by itself, and an install fails until the
   marketplace is registered (observed below). The job therefore registers the marketplace
   explicitly, from the same repository and ref the settings declare.
3. Install `guidance-conventions@claude-plugin-guidance`. The install is in the default user
   scope, so the committed settings file is not written.
4. Find the installed plugin directory from `claude plugin list --json`, in the entry's
   `installPath`, and run the script from it on the repository root.

```yaml
name: Guidance compliance

on:
  pull_request:

permissions:
  contents: read

jobs:
  compliance:
    runs-on: ubuntu-latest
    env:
      CLAUDE_CODE_VERSION: "2.1.301"
    steps:
      - uses: actions/checkout@v4

      - name: Install Claude Code at a pinned version
        run: npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

      - name: Register guidance at the ref the committed settings pin
        run: |
          SOURCE=$(python3 -c 'import json; print(json.dumps(json.load(open(".claude/settings.json"))["extraKnownMarketplaces"]["claude-plugin-guidance"]["source"]))')
          REPO=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["repo"])' "$SOURCE")
          REF=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["ref"])' "$SOURCE")
          claude plugin marketplace add "https://github.com/${REPO}.git#${REF}"

      - name: Install guidance-conventions
        run: claude plugin install guidance-conventions@claude-plugin-guidance

      - name: Run the compliance script from the installed plugin
        run: |
          INSTALL_PATH=$(claude plugin list --json | python3 -c 'import json,sys; print(next(p["installPath"] for p in json.load(sys.stdin) if p["id"] == "guidance-conventions@claude-plugin-guidance"))')
          python3 -B "${INSTALL_PATH}/scripts/guidance_check.py" .
```

Observed on Claude Code 2.1.301, with `CLAUDE_CONFIG_DIR` set to an empty directory and no
marketplace registered, `claude plugin install guidance-conventions@claude-plugin-guidance` exited
`1` and printed:

```
Plugin "guidance-conventions" not found in marketplace "claude-plugin-guidance". Your local copy may be out of date — try `claude plugin marketplace update claude-plugin-guidance`.
```

The bare name `guidance-conventions` printed `Plugin "guidance-conventions" not found in any
configured marketplace`. The qualified install printed the same text from a neutral directory and
from a directory whose committed settings declare the source. The hint in the first message is the
CLI's own; it is printed even though the marketplace was never registered.

The `github` source in the committed settings file looks like this, with the repository and ref
the recipe reads:

```json
{
  "extraKnownMarketplaces": {
    "claude-plugin-guidance": {
      "source": {
        "source": "github",
        "repo": "deepelement-osf/claude-plugin-guidance-framework",
        "ref": "guidance-conventions--v5.0.0"
      }
    }
  }
}
```

If a runner has no Node.js for npm, the native installer takes a version argument instead:
`curl -fsSL https://claude.ai/install.sh | bash -s 2.1.301`, then add `$HOME/.local/bin` to the
path. The recipe above is the one that was run.

## Open points

- **SCOPE: spec and script disagree.** The SCOPE row of the [check catalog](../spec/checks.md#set-scope-where-the-checks-run)
  defines the marketplace-repository test as a git top level holding the manifest, and lists a
  manifest in a subdirectory or a submodule as a case that must not qualify. Observed at `ab5460a`:
  `guidance_check.py` applies no git test. `is_marketplace_repository()` in `gc_model.py` is defined
  but never called by the script, and only `pre_commit_hook.py` applies it. A directory that holds
  only `.claude-plugin/marketplace.json`, inside another git repository, ran the checks and exited
  `1`, with the findings from its missing README and LICENSE. Not decided here: whether the script
  should apply the git test, so that it exits `2` with `SCOPE`, or whether the spec should state
  what the script does.

## Related

- [Check catalog](../spec/checks.md): each check's rule, severity and scope, and the `PIN` and
  `SCOPE` rows.
- [Architecture section 12](./architecture.md#the-stated-checks): the concept graph standard the
  mechanical checks enforce.
- [Contributing](../CONTRIBUTING.md#plugin-versions-and-releases): when a change to these docs needs
  a version bump. It does not, because docs outside `plugins/` carry none.
