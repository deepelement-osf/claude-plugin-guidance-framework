---
name: check-realization-config
description: Authoring check for a concept realization inside a plugin marketplace repository. A realization calls it, if installed, before doing real work. It does nothing outside a marketplace repository, so the same call is harmless in a consuming workspace. Inside a marketplace repository it checks the realization being authored against that repository's own Tier 2 contract range, and validates the config in the repository's test selection (marketplace-plugin-settings.yml at its root) against the realization's schema.json. It checks config against a schema only, never calls a live API, and does not verify credentials. Use when authoring or testing a realization in a marketplace repository, or when the user asks whether a realization's test configuration matches its schema.
allowed-tools: Bash(python3 *is_marketplace_repo.py*)
---

# Check Realization Config

This is the activation-check convention described in
[docs/architecture.md](../../../../docs/architecture.md#6-activation-check-a-shared-convention-not-a-hook).
A realization's instructions may call this skill as their first step, if
installed. It is an authoring aid. It runs only inside a plugin marketplace
repository, where it checks a realization while the author builds and tests
it. Everywhere else it does nothing.

It checks config against a `schema.json` and nothing else. It never calls a
live API, does not detect a change in an external service, does not verify
credentials, and does not authenticate its caller. It shows consistency, not
authenticity.

## Inputs

A realization invokes this skill with three things:

- the **concept**, from its `realizes` block (`secrets@acme-concepts`), or a
  bare name (`secrets`);
- the realization's own **name** (`aws-secrets-manager`);
- the realization's own `CLAUDE_SKILL_DIR`, the directory holding its
  `SKILL.md` and `schema.json`. The caller writes this variable inline in its
  own `SKILL.md`, where Claude Code substitutes it; it cannot be read from
  here ([substitutions](https://code.claude.com/docs/en/skills#available-string-substitutions)).

## First step: is this a marketplace repository?

Run this command before anything else:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/is_marketplace_repo.py" "${CLAUDE_PROJECT_DIR}"
```

`${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PROJECT_DIR}` are written inline here,
and Claude Code substitutes them. On an older version a placeholder is not
substituted, the command fails, and the directory cannot be determined. Report
that and halt; do not guess a directory.

The script prints nothing. Its exit code is the result:

- **Exit 0:** this is a marketplace repository. Continue with "Inside a
  marketplace repository".
- **Exit 1:** this is not one. Report nothing and return. This is the normal
  result in a consuming workspace, and it is not a failure.
- **Any other exit code:** report the exit code and the command, and stop.

The script exits 0 only when `.claude-plugin/marketplace.json` exists in the
directory and `git rev-parse --show-toplevel`, run in that directory, gives
that same directory (both compared as real paths). A `marketplace.json` in a
subdirectory, in a submodule, or in a directory that is not a git repository
does not qualify.

## Inside a marketplace repository

The repository is the one at `${CLAUDE_PROJECT_DIR}`.

1. **Read the test selection.** Read `marketplace-plugin-settings.yml` at the
   repository root. If the file is missing, there is nothing to check: say so
   and return.

2. **Read the realization being authored.** Read the `realizes` block in the
   caller's `SKILL.md`, and the `schema.json` beside it. The concept is the
   part of `concept` before `@`. The realization's name is its directory name
   without the `realize-` prefix. A realization with no `realizes` block has no
   contract range, so step 4 skips the gate and says so. A concept's own
   realization need not carry the block.

3. **Find the selections for this realization.** Look for a top-level key equal
   to the concept's bare name. That key holds a base selection, and may also hold
   scoped selections (pattern 13) and, when the contract allows several
   realizations, a list of selections (pattern 12).
   - **Base selection.** The key's own `realization` value.
   - **Scoped selections.** Each entry under `scoped:`. Its `when:` keys are run
     facts such as the environment or the node. They have no value in a test, so
     do not evaluate them. Check each entry whose `realization` names this
     realization, and say which `when:` it carries.
   - **Several selections.** When the key lists more than one realization
     (pattern 12), read each listed item as a base selection, with its own
     `config`. The form of the list is the one
     [architecture.md section 3](../../../../docs/architecture.md#3-workspace-configuration-marketplace-plugin-settingsyml)
     gives for multiple selections.
   - No selection in the file names this realization: there is nothing to check
     for it. Say which realization the test selection names, if any, and return.
   - A selection with no `realization` value: report it as a finding and name the
     key to add.
   - A `realization` value is a bare name, or `name@marketplace` where
     `marketplace` is this repository's `name` in
     `.claude-plugin/marketplace.json`. Any other qualifier does not select this
     realization.

4. **Gate on the contract range.** Find this repository's Tier 2 contract for
   the concept: the plugin here whose name, without its first hyphen-delimited
   segment, equals the concept name, and which has
   `skills/realization-contract/schema.json`. Read its `contractVersion`.
   - Not in this repository (for example, another marketplace defines the
     concept): report the gate as "unverified" and name the contract that could
     not be read. Continue to step 5.
   - In this repository with no `contractVersion`: report a finding.
   - Otherwise the realization's `contractVersion` range must accept that
     version, read with the same rules as a dependency's
     [`version` field](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint).
     If it does not, or the range is invalid, report a finding that gives the
     contract's version and the range.
   - A realization with no range skips this gate; say so in a note.

5. **Validate the config.** Validate the `config` block of each selection that
   step 3 collected, against the realization's `schema.json`, and no more than
   this:
   - every field in the schema's `required` array is present;
   - every field's value matches the schema's declared `type`.
   Report each missing or invalid field, using the schema's `description` if
   present, what is expected, and where the fix goes: under `<concept>.config`
   for the base selection, or under that scoped entry's or listed item's
   `config`, in `marketplace-plugin-settings.yml`.

## Reporting

- Name the steps that ran, and each step that did not run and why.
- Report pass or fail for each finding, with the field and the file to fix.
  Never just "invalid".
- Only when every step passes, report success and say: "Config matches the
  realization's schema; no live call was made to the service." Do not perform
  the realization's actual work; this skill only gates it.
- Say what was not checked: credentials, reachability, and any change in the
  external service.

## What this skill does not do

- It does not run outside a marketplace repository. In a consuming workspace the
  first step exits 1, and the check reports nothing.
- It does not validate a consuming workspace's own selection. The workspace
  runtime checks that, and a consuming workspace does not install this plugin.
- It does not call a live API, verify credentials, or detect a change in an
  external service.
