---
name: check-realization-config
description: Pre-flight check invoked by a concept-plugin realization before it does real work, or by a user asking to check/audit their marketplace-plugin-settings.yml. Resolves the concept and the selected realization across the marketplaces installed in the consuming workspace and the workspace's own realizations, confirms the caller is the selected realization and that its declared contractVersion range accepts the installed contract, reports when a workspace realization overrides an installed one, checks the installed realization a workspace realization extends, and validates the workspace's config against the realization's schema.json. It checks config against a schema only, never calls a live API, and does not detect that an external service changed or verify credentials. Use before executing any concept realization's actual behavior, and whenever the user asks whether their marketplace plugin configuration is valid or complete.
allowed-tools: Bash(claude plugin list *), Bash(realpath *), Bash(git rev-parse --show-toplevel)
---

# Check Realization Config

This is the activation-check convention described in
[docs/architecture.md](../../../../docs/architecture.md#6-activation-check-a-shared-convention-not-a-hook).
Any concept realization's instructions invoke this skill as their first
step, before doing real work, so a missing, stale or ambiguous workspace
configuration produces one clear, early, blocking message instead of a
confusing failure deep inside the realization.

Speak to the consuming workspace's owner. This skill validates `config`
against a `schema.json` and nothing else: it never calls a live API, and
it cannot see an external service, CLI or MCP server change after the
realization was written, verify credentials or reachability, or
authenticate its caller. It shows consistency, not authenticity
([what it does not do](../../../../docs/architecture.md#what-the-activation-check-does-not-do)).

## Inputs

A realization invokes this skill with three things:

- the **concept**, as written in the realization's `realizes` block
  (`secrets@acme-concepts`), or a bare name (`secrets`);
- the realization's own **name** (`aws-secrets-manager`);
- the realization's own `CLAUDE_SKILL_DIR`, the directory holding its
  `SKILL.md` and `schema.json`. The caller writes this variable inline in
  its own `SKILL.md`, where Claude Code substitutes it; it cannot be read
  from here ([substitutions](https://code.claude.com/docs/en/skills#available-string-substitutions)).

A **legacy caller** passes names only. With no directory this skill cannot
identify the caller by location, so it compares names literally, skips the
contract gate (step 5) and the no-entry fallback (step 4), and otherwise
runs the steps below, including the override notice and step 5b, which read
the selected candidate's files.

## Where things are looked up

- **Workspace root:** `${CLAUDE_PROJECT_DIR}`. It is written inline in this
  `SKILL.md`; do not use `$CLAUDE_PROJECT_DIR` in a Bash command, which does
  not have it. Claude Code substitutes it from v2.1.196 onward
  ([substitutions](https://code.claude.com/docs/en/skills#available-string-substitutions));
  on an older version the placeholder stays literal, so say that the
  workspace root cannot be determined and halt, rather than guess one.
- **Settings file:** `${CLAUDE_PROJECT_DIR}/marketplace-plugin-settings.yml`.
- **Workspace-authored realizations:** the files matched by
  `${CLAUDE_PROJECT_DIR}/.claude/skills/realize-*/schema.json`, one level
  deep; the directory is `realize-<name>` or `realize-<concept>-<name>`
  ([identity of a workspace-authored realization](../../../../docs/architecture.md#identity-of-a-workspace-authored-realization),
  [where it lives](../../../../docs/architecture.md#where-a-workspace-authored-realization-lives)).
- **Installed plugins:** step 0. Never work out another plugin's location
  from the caller's directory or from this skill's own; a sibling plugin
  has its own install path.

**Comparing directories.** Every comparison of two directories (a plugin's
`projectPath` against the workspace root, the caller's directory against a
candidate's) is made after resolving real paths with `realpath`, so a
symlink, a relative path or a trailing slash does not read as a mismatch.

**Comparing versions.** Step 5b compares a plugin's installed version with
the `extends.version` range of a workspace realization. That range uses a
small subset of node-semver, so this skill evaluates it by the rules below
and not by a library. The grammar
([extending an installed realization](../../../../docs/architecture.md#extending-an-installed-realization)
defines the same one):

```
range      := comparator | lower SP upper
comparator := ["=" | "^" | "~" | ">=" | ">" | "<=" | "<"] version
lower      := (">=" | ">") version
upper      := ("<=" | "<") version
version    := NUM "." NUM "." NUM
NUM        := "0" | a digit 1-9 followed by zero or more digits
```

- A bare `version` and `=version` mean exactly that version.
- Exactly one `SP` (space) between the two bounds, and no space after an
  operator.
- Not accepted, each an invalid range: partial versions (`1.4`, `^1.4`),
  `x`, `*`, `latest`, a leading `v`, any pre-release or build suffix
  (`1.4.0-rc.1`, `1.4.0+b`), `||`, hyphen ranges, three or more clauses,
  `^` or `~` combined with another clause, two lower bounds, an upper bound
  first, an empty string, and a pair no version can satisfy
  (`>=2.0.0 <1.0.0`).

Expand the range, then compare:

- `^M.m.p`: if M is above 0, `>=M.m.p <(M+1).0.0`; else if m is above 0,
  `>=0.m.p <0.(m+1).0`; else `>=0.0.p <0.0.(p+1)`.
- `~M.m.p`: `>=M.m.p <M.(m+1).0`.
- `=M.m.p` or a bare version: exactly `M.m.p`.
- A pair: both bounds must hold.

Compare the three numbers as integers, left to right, never as strings
(1.10.0 is greater than 1.9.0). Every pass line and every breach message
prints the **expanded bounds**, and a breach message names the component that
decides (for example "major 3 is not below 3"), so a slip in the arithmetic
is visible to a person.

| Installed | Range | Expands to | Result |
|---|---|---|---|
| 1.4.2 | `^1.4.0` | `>=1.4.0 <2.0.0` | satisfies |
| 1.3.9 | `^1.4.0` | `>=1.4.0 <2.0.0` | below (minor 3 < 4) |
| 2.0.0 | `^1.4.0` | `>=1.4.0 <2.0.0` | above (major 2 is not below 2) |
| 1.10.0 | `^1.9.0` | `>=1.9.0 <2.0.0` | satisfies (10 > 9 as numbers) |
| 1.4.2 | `~1.4.0` | `>=1.4.0 <1.5.0` | satisfies |
| 1.5.0 | `~1.4.0` | `>=1.4.0 <1.5.0` | above |
| 0.3.9 | `^0.3.1` | `>=0.3.1 <0.4.0` | satisfies |
| 0.4.0 | `^0.3.1` | `>=0.3.1 <0.4.0` | above (caret on 0.x stops at the next minor) |
| 0.0.4 | `^0.0.3` | `>=0.0.3 <0.0.4` | above (only 0.0.3 satisfies) |
| 1.4.2 | `>=1.4.0 <2.0.0` | as written | satisfies |
| 1.4.2 | `1.4.2` or `=1.4.2` | exactly 1.4.2 | satisfies |
| 1.4.3 | `1.4.2` | exactly 1.4.2 | above |
| 1.4.2 | `^1.4` | | invalid range |
| 1.4.2 | `>=1.0.0 \|\| ^2.0.0` | | invalid range |
| 1.4.2 | `>= 1.4.0` | | invalid range |

**Non-semver installed versions.** An installed version can be compared only
if it is exactly three numbers, `NUM.NUM.NUM`. A 12-character commit SHA,
`unknown`, a pre-release or build suffix (`2.0.0-beta.1`), a two-part
version or a missing value cannot be compared and halts step 5b. It never
passes silently, because the check cannot know whether an update breached
the range.

**Worktrees.** A linked git worktree that has no `.claude/skills` of its
own loads the main checkout's project skills instead (Claude Code v2.1.277
or later; see
[skill discovery](https://code.claude.com/docs/en/skills#discovery-from-parent-and-nested-directories)).
A caller loaded that way has a directory outside the workspace root, the
glob above then finds none of the workspace's realizations, and a project
or local plugin recorded against the main checkout's path fails the
`projectPath` comparison, so the check could report a false "stale" or
"selected a different realization", and an override of an installed
realization may not be reported. Therefore, when the caller's directory
is under neither the workspace root nor an installed plugin's `installPath`,
or when `git rev-parse --show-toplevel` run in the workspace root does not
resolve to the workspace root, label the whole result **BEST-EFFORT**, and
add to any such halt that the session may be a worktree without its own
`.claude/skills`.

## When invoked for a specific concept (normal pre-flight use)

0. **List the installed plugins.** Run `claude plugin list --json` through
   Bash, calling the `claude` binary directly, and parse stdout only
   (ignore anything on stderr). See
   [`claude plugin list`](https://code.claude.com/docs/en/plugins/cli-reference#plugin-list)
   for the fields.
   - Keep entries whose `scope` is `user`, or whose `scope` is `project` or
     `local` and whose `projectPath` equals the workspace root. Drop the
     rest. When one `id` remains more than once, keep one entry for its
     `installPath`, `enabled` and `errors`, and note the version and scope
     of every entry that remained (see **Installed version**).
   - Entries with `scope` `session` (plugins passed with `--plugin-dir` to
     this `claude plugin list` call, id `name@inline`) are dropped too: the
     list does not report the running session's own `--plugin-dir` plugins,
     and a session plugin is not installed for the workspace's other
     users. If a halt names a plugin that is only available this way, say
     that it is not visible to this check instead of calling it missing.
   - An entry's `installPath` is that plugin's root. `id` is
     `name@marketplace`.
   - A plugin is **loaded** only when `enabled` is `true` **and** it has no
     non-empty `errors`. Never treat `enabled` alone as loaded: a plugin
     whose dependency is unmet can still report `enabled: true`.
   - An unmet dependency is an `errors` entry whose `errorDetails` item has
     `type` `dependency-unsatisfied` or `dependency-version-unsatisfied`
     ([dependency errors](https://code.claude.com/docs/en/plugins/troubleshooting#dependency-errors);
     `errorDetails` needs Claude Code v2.1.268 or later, and on an older
     version read the `errors` text instead). The fields are documented
     under [JSON output](https://code.claude.com/docs/en/plugins/cli-reference#json-output).
   - **Installed version.** A plugin's installed version is the `version`
     of its entry, or its `folderVersion` when the entry has
     `readFromFolder` and a `folderVersion` (Claude Code v2.1.289 or later;
     it is the version read from the folder). Print it as reported: it can
     be a semantic version, a 12-character commit SHA or `unknown`. When one
     `id` has more than one loaded entry after the filter above, read each:
     equal values are one version, and different values are a version
     conflict (an override notice prints each value with its scope; step 5b
     halts only if they disagree about the range). If a version cannot be
     read, print `unknown`. In the fallback below, read the `version` key of
     the `installed_plugins.json` entry, or `unknown`.
   - **If the CLI is unavailable** (not found, a non-zero exit, or output
     that is not JSON), fall back and label every result **BEST-EFFORT**:
     read `~/.claude/plugins/installed_plugins.json` for the installed
     plugins and their `installPath`, `enabledPlugins` from the user,
     project and local settings files for which are enabled, and each
     plugin's `.claude-plugin/plugin.json` `dependencies` for which are
     installed and enabled. The fallback cannot confirm that a plugin loaded.
     Say so in the output.

1. **Locate the settings file.** Read `marketplace-plugin-settings.yml` at
   the workspace root. A missing file means there is no entry for any
   concept; carry on and let step 4 decide, and say in any halt that the
   file was not found.

2. **Resolve the concept.** A concept plugin is a loaded plugin with
   `skills/concept/SKILL.md` under its `installPath`. Its concept name is
   its plugin name without the first hyphen-delimited segment (`secrets`
   for `acme-secrets`), and its qualifier is the marketplace in its `id`.
   - **Zero matches: halt.** Say which of these applies:
     - *The defining plugin is found but not installed or enabled.* A
       plugin that would define this concept is installed but disabled or
       reporting errors, is named by another plugin's unmet-dependency
       error, or is offered by a registered marketplace without being
       installed. `claude plugin list --json --available` prints one object
       instead of an array: `installed` holds the array step 0 parses, and
       `available` holds one object per uninstalled plugin (`pluginId`,
       `name`, `marketplaceName`). Name the missing `plugin@marketplace` and give the
       remedy: `claude plugin install <plugin>@<marketplace> --scope project`,
       then `/reload-plugins`. Observed on Claude Code 2.1.286, enabling a
       relative-path plugin in settings did not by itself install its
       cross-marketplace dependencies; the docs promise neither behaviour
       ([architecture §9](../../../../docs/architecture.md#what-the-consuming-workspace-must-do)),
       so do not promise it either way.
     - *No such concept.* Name the concept, the marketplace to register
       when the name was qualified, and say the missing piece is the plugin
       that defines it.
   - **A bare name matching concepts from more than one marketplace: halt**
     and print the qualified forms, for example: "Concept `secrets` is
     defined by `acme-concepts` and `other-concepts`; pass `secrets@acme-concepts`
     or `secrets@other-concepts`."
   - **No `skills/realization-contract/` in the concept plugin: halt** with
     "no contract to realize". A concept-only plugin cannot be selected
     against.
   - Otherwise read the contract's `skills/realization-contract/schema.json`
     and keep its `contractVersion`. Steps 5 and 5b compare against it.

3. **List the candidate realizations** for the resolved concept. A candidate
   has a name, a source and a directory:
   - **The workspace's own:** each `.claude/skills/realize-*/` found above
     whose `SKILL.md` carries a `realizes` block naming this concept with
     the resolved qualifier. Its name is the block's `realization` value if
     there is one, and otherwise its directory name without `realize-`.
     When the block has `realization`, the directory must be
     `realize-<name>` or `realize-<concept>-<name>` (the bare concept name);
     the check composes those two names from the block and compares them,
     and never splits a directory name. The block decides identity and the
     directory is only checked against it. A directory that fails this, or
     that gives a name another workspace directory also gives for this
     concept, is not a candidate. Halt (naming the directory, the file to
     fix and what it should be) only if it is the caller's directory, or its
     `realization` text or its directory name without `realize-` equals the
     bare name that the settings entry selects; otherwise skip it. The
     messages:
     - `realization` is not a valid name (lowercase letters, digits and
       single hyphens, so it matches `^[a-z0-9]+(-[a-z0-9]+)*$`, and not
       starting with `realize-`):

       > Workspace realization `.claude/skills/realize-foo/` has
       > `realization: AWS`, which is not a valid name; use lowercase letters,
       > digits and single hyphens, not starting with `realize-`, in the
       > `realizes` block of its `SKILL.md`.

     - The directory and the block disagree:

       > Workspace realization `.claude/skills/realize-foo/` declares
       > `realization: aws` for concept `secrets@acme-concepts`, so its
       > directory must be `realize-aws` or `realize-secrets-aws`. Rename the
       > directory, or fix `realization` or `concept` in the `realizes` block
       > of its `SKILL.md`.

     - Two workspace directories give the same name for the concept:

       > Workspace realizations `.claude/skills/realize-aws/` and
       > `.claude/skills/realize-secrets-aws/` both realize `aws` for concept
       > `secrets@acme-concepts`; remove or rename one.

     A workspace realization whose block names a different concept is
     examined when that concept is resolved. A workspace realization
     without the `realizes` block is not a candidate; if a selection names
     one, say so in the halt. Two workspace realizations of different
     concepts may share a name (`realize-secrets-aws/` and
     `realize-queues-aws/`). Not supported: two concepts with the same bare
     name from different marketplaces and the same realization name, and two
     pairs that compose the same directory name (`a-b` with `c`, and `a` with
     `b-c`); use different realization names, or the short form for one.
   - **The defining plugin's:** its `skills/realize-*/` directories. Source
     is the defining marketplace. The name is the directory name without
     `realize-`.
   - **Realization plugins':** the `skills/realize-*/` directories of other
     loaded plugins whose `SKILL.md` `realizes` block names this concept
     with the resolved qualifier. Source is the marketplace in the plugin's
     `id`. The name is the directory name without `realize-`; a
     `realization` key in a plugin's block is ignored.

4. **Find the concept's entry and select.** Look for a top-level key equal
   to the bare concept name in the settings file.
   - **An entry with `realization`.** The value is a bare name or
     `realization@marketplace`.
     - A bare name that a workspace realization carries **resolves to the
       workspace's own**. The workspace wins; this is not a collision and
       not a halt. Call the workspace realization W and its name N. Work out
       the **shadowed set**: the candidates from the defining plugin and
       from loaded realization plugins (the two sources above) whose plugin
       is loaded and whose name is N. Keep the set, and print nothing yet;
       the **override notice** is printed in step 7 or at the head of a
       later halt. The name N under another concept is not a candidate and
       never counts.
     - Otherwise a bare name matching installed candidates from more than
       one marketplace **halts**, printing the qualified forms to copy:
       "Realization `aws-secrets-manager` for concept `secrets@acme-concepts`
       is offered by `acme-aws-realizations` and `acme-other`; select
       `aws-secrets-manager@acme-aws-realizations` or
       `aws-secrets-manager@acme-other` in `marketplace-plugin-settings.yml`."
     - A qualified name matches installed candidates from that marketplace
       only; it is how the workspace chooses an installed one over its own.
       The workspace realization is then not selected and there is no
       override notice.
     - **Zero matches is a stale configuration: halt.** Name the missing
       realization, the three places searched (the defining plugin, loaded
       realization plugins, `.claude/skills/realize-*/`), and
       `marketplace-plugin-settings.yml` as the file to fix. When the
       realization is offered by a plugin that is installed but not loaded,
       report that distinctly (name the `plugin@marketplace` and the remedy
       from step 2) instead of calling it stale. If workspace directories of
       this concept were skipped in step 3, end with a sentence naming each
       and why: "Skipped workspace directories with an identity problem:
       `.claude/skills/realize-foo/` (directory does not match
       `realization: aws`)."
   - **The caller must be the target.** Compare the selected candidate's
     directory with the caller's directory. If they differ, halt: the
     workspace selected a different realization than the one invoked.
     Report both and which file or skill to check. A legacy caller is
     compared by name, so it cannot be told from W when it shares W's name,
     which an installed realization that W overrides always does. For such a
     legacy caller the halt below cannot fire: add the note "The caller passed
     only a name, so it could not be confirmed that the workspace
     realization was the one invoked" to the success report. When the
     selected candidate is W and a caller with a directory is a member of W's
     shadowed set, halt with this text instead of the general one, and print
     no override notice with it:

     > Workspace realization `aws` (`.claude/skills/realize-secrets-aws/`)
     > overrides `aws@acme-aws-realizations`, which was invoked here, so it
     > will not run. Select `aws@acme-aws-realizations` in
     > `marketplace-plugin-settings.yml` to use the installed one. To run the
     > workspace realization, invoke it directly.
   - **No entry** (or no file). Only a caller with a directory can take
     this path.
     - The caller is the defining plugin's default (its directory is in the
       defining plugin and it is marked the default, per
       [architecture §4](../../../../docs/architecture.md#4-a-concept-may-be-published-with-no-realization-at-all))
       **and** its `schema.json` has no required fields: run, and give the
       notice "no explicit selection; running the defining marketplace's
       default".
     - The caller is that default but its schema has required fields:
       **halt** with "no entry; this default needs config" and name the
       missing fields.
     - The caller is not the default: **halt** with "not selected", and
       name the entry to add.
     - The concept has no default: **halt** with "select one" and list the
       candidates in their qualified forms.
     [Why the default can run](../../../../docs/architecture.md#no-entry-for-the-concept).
   - An entry with no `realization` value halts, naming the key to add.

   **The override notice.** It is one line, never a halt. It is printed when
   the selected candidate is W and its shadowed set is not empty: once per
   run, in step 7 on success, or at the head of the message of a halt in
   step 5 or 6 (always in its plain form there), never twice. A halt before
   step 5, the caller-in-the-set halt above and a halt in step 5b print no
   override notice (a 5b halt already names the base and its version). The
   fields are N (the name), `C@Q` (the concept and qualifier) and, for each
   member of the shadowed set, `` `N@M` V ``, where M is the marketplace in
   the plugin's `id` and V the installed version of its plugin (step 0), as
   reported; a realization has no version of its own. For a candidate
   shipped in the defining plugin, V is the concept plugin's version. With
   several members, list all of them ordered by marketplace name, then
   plugin name, comma-separated with a final "and":

   > Workspace realization `aws` for concept `secrets@acme-concepts`
   > overrides `aws@acme-aws-realizations` 1.4.2; the workspace's own runs.

   > Workspace realization `aws` for concept `secrets@acme-concepts`
   > overrides `aws@acme-aws-realizations` 1.4.2 and `aws@acme-other` 0.4.1;
   > the workspace's own runs.

   If a plugin directory cannot be read, leave that candidate out and add
   `(some installed candidates could not be read)` before the semicolon.
   If W declares a valid `extends`, step 5b makes this line part of the
   `Extends checked:` line instead. In a result labelled BEST-EFFORT because
   the CLI was unavailable (step 0), append:

   > BEST-EFFORT: installed versions were read from `installed_plugins.json`
   > and loaded state was not confirmed.

   In a result labelled BEST-EFFORT because of the worktree rule, append
   instead:

   > BEST-EFFORT: the session may be a worktree without its own
   > `.claude/skills`, so an override may not be reported.

5. **Gate on the contract version.** Read the `realizes` block in the
   caller's `SKILL.md`. Its `concept` must name the resolved concept, or
   halt. Its `contractVersion` is a range over the Tier 2 `contractVersion`
   read in step 2. If the installed version does not satisfy the range,
   **halt**, giving the installed version and the range, and say that the
   realization's author needs to publish a compatible realization or the
   workspace needs to stay on a contract version it accepts. A range that
   is invalid, or an installed contract with no `contractVersion`, also
   halts.
   - A caller with **no range declared** (a legacy caller, or a defining
     plugin's own realization, where the block is only recommended) skips
     the gate; say so in a note.

5b. **Check what the realization extends.** Read the `extends` entry of
   the **selected candidate's** `realizes` block, whoever the caller is
   (a legacy caller too). Skip this step when the selected candidate has
   none. When the selected candidate is shipped by a plugin and its block
   has `extends`, skip this step and give the notice "`extends` in
   `<realization>@<marketplace>` is ignored: only a workspace-authored
   realization can extend another." The step records a guard and a
   dependency: it does not run the base. Work in this order, static errors
   first, then the environment. A halt names the file to fix, here
   `<file>` is `.claude/skills/<dir>/SKILL.md` of the extending workspace
   realization `X`.

   The block is:

   ```realizes
   concept: secrets@acme-concepts
   contractVersion: "^1.1.0"
   realization: aws
   extends:
     realization: aws@acme-aws-realizations
     version: "^1.4.0"
   ```

   `extends` is a mapping with exactly two keys, both required:
   `realization`, the base, always qualified (`<name>@<marketplace>`, the
   marketplace being the one in the base plugin's `id`), and `version`, a
   quoted range from **Comparing versions** over the base plugin's installed
   version. The base's name may equal X's own name (the usual case, X
   shadows its base), or differ from it. The contract side is not repeated
   here: X's own `contractVersion` is gated in step 5, and the base's own
   is checked below.

   1. **Shape.** Any other key halts, naming the key; an unknown key must
      not silently drop enforcement.

      > Workspace realization `X` has a malformed `extends` in `<file>`:
      > <reason>. Write it as a mapping with `realization:
      > <name>@<marketplace>` and `version: "<range>"`; no other key is
      > allowed.

      The reason is one of: "it is not a mapping"; "`realization` is missing
      or empty"; "`version` is missing or empty"; "unknown key `<key>`".
      When the key is `contractVersion`, append: "The contract range for this
      realization is `contractVersion` in the same block, which the check
      already gates." A bare name in `extends.realization` halts too (it
      would mean a workspace realization, which cannot be a base, not even X
      itself):

      > `extends.realization` in `<file>` is `<value>`, a bare name. A bare
      > name means a workspace realization, and a workspace realization
      > cannot be a base, not even this one. Name the installed realization
      > as `<name>@<marketplace>`.

   2. **Range.** `extends.version` must be in the grammar above:

      > `extends.version` `<text>` in `<file>` is not a range this check
      > evaluates. Use an exact version (`1.4.2`), `^1.4.0`, `~1.4.0`, one
      > comparator (`>=1.4.0`) or two joined by a space (`>=1.4.0 <2.0.0`),
      > each with all three numbers and no pre-release suffix.

   3. **Resolve the base** (`B` = `N@M`) among the loaded installed
      candidates of the resolved concept `C@Q` whose marketplace is `M`
      and whose name is `N` (the defining plugin's and the realization
      plugins' candidates from step 3). More than one match halts:

      > `extends` names `<N>@<M>`, but two loaded plugins of `<M>` (`<p1>`
      > and `<p2>`) ship a realization `<N>` of `C@Q`, which breaks that
      > marketplace's unique-name rule ([defaults and collisions](../../../../docs/architecture.md#defaults-and-collisions)).
      > Ask its author to fix it, or disable one of them; `extends` cannot
      > name a plugin.

      With no match, halt with the first of these that applies, in this
      order:

      - A plugin of `M` that ships `N` for this concept is installed but not
        loaded:

        > `extends` in `<file>` names `<N>@<M>`, which is installed but not
        > loaded: plugin `<plugin>@<M>` is <disabled | reporting errors:
        > <first error>>. Enable it or fix the error, then `/reload-plugins`.

      - A loaded plugin of another marketplace ships `N` for this concept:

        > `extends` in `<file>` names `<N>@<M>`, but `<M>` does not offer
        > `<N>` for concept `C@Q`; it is offered by `<M2>` [and `<M3>`].
        > Change `extends.realization` in `<file>` to `<N>@<M2>`, and check
        > `extends.version` against that plugin's version (`<V2>`).

      - A loaded plugin of `M` ships `N` for a different concept:

        > `<N>@<M>` realizes concept `<other>`, not `C@Q`. `extends` in
        > `<file>` must name a realization of the same concept as `X`.

      - Nothing installed ships it:

        > Realization `<N>@<M>`, named by `extends` in `<file>`, is not
        > installed: no installed plugin of marketplace `<M>` ships it.
        > Register `<M>` if needed, install the plugin that ships `<N>`
        > (`claude plugin list --json --available` lists the plugins of
        > `<M>`), for example `claude plugin install <plugin>@<M> --scope
        > project`, then `/reload-plugins`.

        If `N` equals X's own name, append: "The workspace realization `<N>`
        is this one and is not the base; the base must be the installed
        realization." If the plugin is visible only as a session plugin,
        say it is not visible to this check (step 0's wording) instead of
        calling it missing. Do not promise that enabling alone installs
        dependencies (step 2's wording).

   4. **Version.** Read the installed version(s) of the base's plugin (the
      plugin whose `skills/realize-*/` ships the base; for a base shipped
      in the defining plugin, the concept plugin) as step 0 defines it: the
      version `claude plugin list` reports for the plugin. Claude Code takes
      it from `plugin.json`, or from the marketplace entry when the manifest
      sets none; do not substitute a git tag or a `schema.json`
      `contractVersion`. Then:
      - If the entries at different scopes hold different versions and they
        disagree about the range, halt; this check cannot tell which one
        Claude Code loads. If they all satisfy it, pass and print every value
        with its scope; if none do, use the breach message below and list
        every value:

        > Plugin `<plugin>@<M>` is installed with different versions at
        > different scopes (`V1` (scope `s1`), `V2` (scope `s2`)), and they
        > disagree about `extends.version` `<R>` in `<file>`. This check
        > cannot tell which one Claude Code loads. Bring the installs to one
        > version.

      - A version that is not `NUM.NUM.NUM` (see **Non-semver installed
        versions**) halts. Say so when the value came from `folderVersion`.

        > Base `<B>` has version `<V>`, which is not MAJOR.MINOR.PATCH, so
        > `<R>` cannot be checked. A plugin whose `plugin.json` and
        > marketplace entry set no `version` is reported under a commit SHA or
        > `unknown` ([how the
        > version is computed](https://code.claude.com/docs/en/plugins/loading#versions-and-updates)).
        > Ask the base's author to set `version` to a plain release number,
        > or write `<file>` without `extends`.

      - Compare with `extends.version`. Above the range (the breach an
        update causes) halts; `<lower>` and `<upper>` are the expanded
        bounds, and the deciding component is named, for example "major 3 is
        not below 3". Fill the bounds this way: a range with one side only
        (`>=1.4.0`, `<2.0.0`) omits the missing side and the word "to" and
        prints just the bound it has (`>=1.4.0`); an exact range prints
        "exactly `1.4.2`"; for `>`, `<=` and exact comparisons the deciding
        component names the failed bound (for example "1.4.3 is not at most
        1.4.2"). When scope entries breach in opposite directions, print the
        above-range message and list every value with its scope:

        > Workspace realization `X` extends `<B>` for `<R>` (`<lower>` to
        > `<upper>`), but version `<V>` is installed (<the deciding
        > component>). An update to the base most likely moved it past the
        > range. Nothing was run. Choose one: (1) after testing `X` against
        > `<V>`, widen `extends.version` in `<file>`; (2) pin or roll the
        > base plugin `<plugin>@<M>` back to a version that satisfies `<R>`
        > and keep auto-update off for `<M>` ([versions and updates](https://code.claude.com/docs/en/plugins/loading#versions-and-updates));
        > (3) update `X` for the new base and raise the range with it. A
        > running session keeps the version it loaded, so after changing
        > plugins run `/reload-plugins` and run this again.

        Below the range also halts:

        > Workspace realization `X` extends `<B>` for `<R>` (`<lower>` to
        > `<upper>`), but version `<V>` is installed, which is older than the
        > range (<the deciding component>). Nothing was run. Choose one: (1)
        > update the base plugin `<plugin>@<M>` to a version that satisfies
        > `<R>`, then `/reload-plugins`; (2) if `X` works with `<V>`, lower
        > the range in `extends.version` in `<file>`.

        Do not invent an "install version x" command; state pinning as a
        goal.

   5. **Base contract.** Read the `realizes.contractVersion` range in the
      base's own `SKILL.md` (a node-semver range, evaluated as in step 5)
      and compare it with the installed Tier 2 `contractVersion` from step 2.
      If the base has no `realizes` block (a defining plugin's own
      realization, where the block is only recommended), skip and say so in
      the `Extends checked:` line. If its range cannot be parsed, skip, and
      say so there too; it does not halt, because X's author cannot fix the
      base's block. If the installed contract is outside the base's range,
      halt:

      > Base `<B>` (version `<V>`) declares that it accepts contract `<base
      > range>`, but `C@Q` is at `<contract>`, so the base would refuse to
      > run. Update the concept plugin or pin the base to a version that
      > accepts `<contract>`; the base's author needs to publish a
      > compatible realization.

   6. **Pass.** Keep what was found; the line is printed in step 7. It
      begins with the exact token `Extends checked:` (no other text before
      it, and no BEST-EFFORT text inside the token), and the token never
      appears in a halt message. When the base is also in X's shadowed set
      (the same name, the usual case), it reads "extends and overrides":

      > Extends checked: workspace realization `aws` for concept
      > `secrets@acme-concepts` extends and overrides
      > `aws@acme-aws-realizations` 1.4.2 (satisfies `^1.4.0`, >=1.4.0
      > <2.0.0; base accepts contract `^1.1.0`, installed 1.3.0); the
      > workspace's own runs. Base files: `<installPath>/skills/realize-aws/`.

      When the base has a different name, it is not shadowed:

      > Extends checked: workspace realization `aws-strict` for concept
      > `secrets@acme-concepts` extends `aws@acme-aws-realizations` 1.4.2
      > (satisfies `^1.4.0`, >=1.4.0 <2.0.0; base accepts contract
      > `^1.1.0`, installed 1.3.0); the workspace's own runs. Base files:
      > `<installPath>/skills/realize-aws/`.

      If the shadowed set has members other than the base, add ` and
      overrides LIST` (the list format of the override notice) after the
      base clause and before the semicolon. The base contract clause has
      three forms: `base accepts contract `R`, installed C`; `base declares
      no contract range`; and `base contract range `R` was not checked (not
      readable)`. With several scopes of the base's plugin all satisfying
      the range, print every value with its scope in the parentheses:
      `1.4.2 (scope `user`) and 1.4.3 (scope `project`) (satisfy `^1.4.0`,
      ...)`. `Base files:` is the base's `<installPath>/skills/realize-<name>/`,
      so the extender can read the base's instructions without guessing a
      sibling plugin's location. It is for reading: the extender follows
      those instructions and must not invoke the base as a skill, because
      the base's own first instruction would call this check, which would
      halt as "selected a different realization". The extender skips that
      first instruction, since its own run of this check already covers the
      base, and it does not pass the base's `${CLAUDE_SKILL_DIR}` anywhere:
      in a file that is read and not invoked, the placeholder is not
      substituted.

   **BEST-EFFORT (CLI unavailable).** Versions come from
   `installed_plugins.json`. A breach still halts. "Installed but not
   loaded" cannot be confirmed and does not halt: treat an installed plugin
   as present. The `Extends checked:` line gets the suffix from step 4 that
   matches the reason for the label. In a worktree, add to any 5b halt that the session may be a
   worktree without its own `.claude/skills`.

6. **Validate the config block.** Read the `schema.json` beside the
   caller's `SKILL.md` (the caller's directory plus `schema.json`, a JSON
   Schema document per the
   [`schema.json` convention](../../../../docs/architecture.md#the-schemajson-convention-tier-2-and-tier-3),
   a superset of the concept's Tier 2 schema). A legacy caller has no
   directory; use the matched candidate's. Validate the entry's `config:`
   block against it, and no more than this:
   - Every field listed in the schema's `required` array is present.
   - Every field's value matches the schema's declared `type`.
   If anything is missing or invalid, halt and report each field (using the
   schema's `description` if present), what is expected, and that the fix
   is in `marketplace-plugin-settings.yml` under `<concept>.config`.

7. **Only if every step passes**, report success and let the calling
   realization proceed, with any notices from steps 0 to 5b (the
   running-the-default notice, the override notice or the `Extends checked:`
   line, a skipped gate, a skipped contract check, an ignored `extends`,
   BEST-EFFORT results). Say what was not checked: "Config matches the
   realization's schema; no live call was made to the service." Do not
   perform the realization's actual work; this skill only gates it.

   A check of `extends` happens only when this skill runs: nothing hooks a
   plugin update, and a running session keeps the version it loaded.

## When invoked directly by a user ("check my config", "audit my settings")

There is no caller, so the checks that compare against a caller (the
caller must be the target, the caller's contract range, the no-entry
fallback for a caller) do not apply. Run steps 0 to 4, 5b and 6 for every
concept entry in `marketplace-plugin-settings.yml`, validating each entry
against the `schema.json` of the realization it selects. Step 5b
runs with no caller for every workspace realization that declares
`extends`, selected or not, since an unselected one can rot too. A failure
in 5b, and an identity problem from step 3, is reported under its concept
with the text it would have produced as a halt, and does not stop the rest
of the audit. Then add:

- **Leftover entries.** An entry no loaded concept plugin defines. Say
  whether a plugin that defines it is installed but not loaded (step 2)
  or nothing defines it.
- **Concepts with no entry.** For each loaded concept plugin that has a
  contract and no entry, report whether it would run on an implicit
  default (and what that default needs in `config`) or has no default, and
  say "select explicitly". A concept-only plugin has nothing to configure.
- **Ambiguous names.** Every concept name defined by more than one
  marketplace, and every realization name that more than one installed
  marketplace offers for one concept, with the qualified forms to copy. A
  name a workspace realization also carries is not ambiguous.
- **Overrides.** For each concept with a loaded concept plugin, every
  workspace realization of it whose name equals the name of a loaded
  installed candidate (the defining plugin's and the realization plugins',
  step 3). One line per workspace realization:

      <concept>@<qualifier>: workspace `<name>` (`.claude/skills/<dir>/`) overrides
      `<name>@<marketplace>` <version> [and `<name>@<marketplace>` <version>]:
      active, selected by `<concept>.realization: <name>`.

  or the same with "dormant, <why>". An override is **active** when step 4
  would select the workspace realization (the entry has a bare `realization`
  equal to its name), which is exactly when the run-time notice fires. It
  is **dormant** when it shadows a loaded installed candidate but is not
  selected; the reason is one of "the entry selects `<x>`", "the entry is
  qualified to `<marketplace>`" or "no entry". Active lines come first. Add
  "; it extends `<base>`" when its `extends` names a member of that set.
  Say "Overrides: none." when there are none. A disabled shadowing plugin
  is not listed, and a concept with no loaded concept plugin is covered by
  "Leftover entries". Overrides never fail an audit. In a result labelled
  BEST-EFFORT, end the section with "may be incomplete".
- **Extensions.** One line for each workspace realization that declares
  `extends`:

      secrets@acme-concepts: workspace `aws` extends `aws@acme-aws-realizations`:
      installed 1.4.2 satisfies `^1.4.0` (>=1.4.0 <2.0.0): pass.
      secrets@acme-concepts: workspace `aws-hardened` extends `aws@acme-aws-realizations`:
      installed 2.0.1 does not satisfy `^1.4.0` (>=1.4.0 <2.0.0): fail, above the range;
      see the remedies in the halt message.

  In a result labelled BEST-EFFORT, end the section with "may be incomplete".
- **Ignored declarations.** An `extends` or `realization` key found in the
  `realizes` block of a plugin-shipped realization (loaded plugins'
  `skills/realize-*/`), which the check ignores.
- **Workspace realizations.** Each `.claude/skills/realize-*/` found: the
  concept its `realizes` block names, its derived name, the directory form
  (short or long), whether it declares `extends` (with the base and pass or
  fail, or "not selected"), and any with no block, a missing `schema.json`,
  a directory that does not match its `realization`, or a name another
  directory also gives.

Report results grouped by concept, each as pass/fail with specifics.
Never just "invalid": always the field and the file to fix, and say that
nothing was called live.
