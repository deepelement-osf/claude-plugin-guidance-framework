---
name: validate-marketplace
description: Validate a Claude Code plugin marketplace repository against DeepElement's guidance conventions (naming, required docs, attribution, and the declarations a published marketplace makes when it builds on another). Use when the user asks to check, lint, audit, or validate a plugin marketplace repo, or its plugins, for convention compliance.
---

# Validate Marketplace

Checks the marketplace under validation, a Claude Code plugin marketplace
repository (typically a published marketplace authored with the guidance
marketplace), against DeepElement's guidance conventions. This skill does
**not** validate the plugin/marketplace file schema itself (required
fields, allowed types, directory layout) — that standard is owned and
maintained by Anthropic and evolves independently of this plugin. For
schema validity, defer to the official docs:

- Plugins reference: https://code.claude.com/docs/en/plugins-reference
- Creating plugins: https://code.claude.com/docs/en/plugins
- Plugin marketplaces: https://code.claude.com/docs/en/plugin-marketplaces

If a file doesn't parse as valid JSON, or is missing fields the docs above
describe as required, report that as a **schema issue** and point the user
to the relevant doc page above rather than guessing at what's required —
the schema can change and this skill should not be a second source of truth
for it.

## What this skill checks

Everything below is a DeepElement convention on top of the standard, not
part of the standard itself. Checks 1–5 are referred to as M1–M5; the two
sets after them (U and AD) cover a published marketplace that builds on
another (see
[architecture.md §9](../../../../docs/architecture.md#9-chains-of-published-marketplaces)).

1. **Marketplace naming (M1).** `.claude-plugin/marketplace.json`'s `name`
   field should describe the marketplace's own identity (e.g. matches the
   repo purpose), and its `plugins` entries should each resolve to a real
   directory under `plugins/`. Only an entry with a relative-path source
   resolves to a directory ([plugin sources](https://code.claude.com/docs/en/plugins/marketplace-reference#relative-path-plugin-source)
   lists which marketplace source types carry the plugin files); for an
   entry with any other source type, skip every check that reads the plugin
   directory and say it was skipped.

2. **Plugin naming prefix (M2).** The marketplace's prefix is the first
   hyphen-delimited segment of its plugin names (`acme` in `acme-secrets`),
   and every plugin in it must share that one prefix. This applies to every
   plugin directory under `plugins/` and to the corresponding `name` in its
   `.claude-plugin/plugin.json`. Flag any plugin whose name doesn't share
   the prefix, and any name with no hyphen, which has no prefix to share.
   The `guidance-` prefix is reserved for the guidance marketplace (the
   marketplace named `claude-plugin-guidance`); flag it in any other
   marketplace. M2 is non-blocking as a whole: report each M2 finding as a
   convention issue and do not treat it as failing the validation, because
   earlier guidance used `guidance-<concept>` in its own examples and a
   marketplace that followed it would otherwise start failing. A **concept name** is a concept plugin's name without its prefix
   (`secrets` for `acme-secrets`); set AD below uses it.

3. **Required top-level docs (M3).** The repo root should have:
   - `README.md` describing the marketplace, how to add it
     (`/plugin marketplace add ...`), and its plugin naming convention.
   - `LICENSE` present, and referenced from the README.

4. **No restated standard (M4).** Scan README/docs for content that duplicates
   or paraphrases the base plugin/marketplace schema (e.g. hand-written
   lists of `plugin.json` fields, directory layout diagrams that mirror the
   official reference). Flag these as drift risk and recommend replacing
   them with a link to the relevant docs.claude.com/code.claude.com page,
   since the base standard is a living convention that can change out from
   under a static description.

5. **Attribution note (M5; only if the guidance marketplace's license
   model is reused).** If the LICENSE of the marketplace under validation contains
   a public-attribution clause (as opposed to plain MIT/Apache/BSD),
   confirm the README states the attribution requirement in plain
   language, not just by reference to a LICENSE section number.

## Upstream declarations (set U)

A published marketplace B builds on a published marketplace A when a plugin
in B lists a plugin of A in its `dependencies`. Run set U only if some
marketplace entry or `plugin.json` names a dependency on another
marketplace, or the root `marketplace.json` has
`allowCrossMarketplaceDependenciesOn`; otherwise say it does not apply. A
dependency is cross-marketplace if it is an object with a `marketplace`
field naming a marketplace other than the one under validation, or a string
of the form `name@marketplace`
([dependency entry forms](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint)). This skill reads the declarations only. An
invalid range, an unregistered marketplace or a missing release tag is
reported by Claude Code when the dependency is resolved, so do not
re-implement those checks, and do not parse version ranges. Set U also
runs on a realization marketplace, whose entries depend on the plugin that
defines the concept it realizes; there the defining marketplace is a
depended-on marketplace, not an upstream one (upstream and downstream
name only a relation between published marketplaces). For the
recommended way to write these declarations, link
[architecture.md §9](../../../../docs/architecture.md#9-chains-of-published-marketplaces)
rather than restating it.

| Id | Pass | Fail | Severity |
|---|---|---|---|
| **U1** Placement | Every cross-marketplace dependency is in the marketplace entry | One is in a plugin's `plugin.json` | Blocking |
| **U2** Form | Each is an object with `name`, `marketplace` and `version` | A string form, or an object with no `version` | Blocking |
| | | A `version` that is textually open-ended (`*`, `x`, empty, `latest`, or a bare `>=`) | Non-blocking |
| **U3** Allowlist | Every marketplace named by an entry's dependencies is in the root `allowCrossMarketplaceDependenciesOn` (direct dependencies only) | A named marketplace is missing, or the root has no allowlist | Blocking |
| **U4** README section | The README has a `## Required marketplaces` section in the [architecture.md §9 template](../../../../docs/architecture.md#readme-template--required-marketplaces), with the template's column order and a row for every allowlisted marketplace giving its registration source; the plugin names in each row match the entries | The section, or a row for an allowlisted marketplace, is missing | Blocking |
| | | A row's range text differs from the entry's `version` | Non-blocking |

An entry-level `dependencies` list is the one Claude Code enforces for a
cross-marketplace dependency, which is why U1 asks for it there. U3 reads
the root allowlist only, because an upstream's own allowlist is ignored.
The README section is the author's own statement and nothing verifies a
registration source, so U4 checks that the section exists and agrees with
the manifest, not that a source is correct.

A dependency on the guidance marketplace is not reported here. Check A8 in
`validate-concept-plugin` refuses it, and set U does not repeat that finding
as U1, U2 or U3.

## Additive-only chains (set AD)

Run set AD only on a published marketplace, that is, one in which at least
one plugin has a `skills/concept/SKILL.md` (the signal described in
`validate-concept-plugin`); otherwise say it does not apply. The rule being
checked is
[architecture.md §9, "The additive-only rule"](../../../../docs/architecture.md#the-additive-only-rule):
B adds new concept plugins under its own prefix and does not reuse anything
of an upstream's. A concept name is defined in M2 above. When M2 reports
mixed prefixes, take each plugin's concept name from its own first segment.

| Id | Pass | Fail | Severity |
|---|---|---|---|
| **AD1** Unique concept names | Each concept name is defined by one plugin in the marketplace under validation | Two plugins define the same concept name (for example `acme-secrets` and `beacon-secrets`) | Blocking |
| **AD2** No overlap with an upstream | No plugin name, concept name or prefix of the marketplace under validation equals one of an upstream published marketplace's whose copy is on disk | An overlap, naming both plugins and the shared name or prefix | Blocking |
| | | An upstream published marketplace named by an entry dependency is not on disk, so overlap cannot be checked ("unverified") | Non-blocking |
| **AD3** Realizations stay with their concept | Every plugin with a `skills/realize-*/` skill also has its own `skills/concept/`, and every `realizes` block in the marketplace under validation names a concept it defines | A plugin has realizations and no `skills/concept/` of its own (a realization-only plugin) | Blocking |
| | | A `realizes` block whose qualifier is not the `name` of the marketplace under validation, or whose concept name is not the concept name of any of its concept plugins | Blocking |

For AD2, an upstream published marketplace is a marketplace named in an
entry's cross-marketplace dependency, other than the guidance marketplace,
which is neither upstream nor downstream of anything. It is on disk when the
user gives you its directory or when Claude Code has a local copy of it
(`claude plugin marketplace list --json` lists the registered marketplaces
and, for each, `installLocation` or `path`: see the
[CLI reference](https://code.claude.com/docs/en/plugins/cli-reference#plugin-marketplace-list));
read that copy's `marketplace.json` and plugin
directories the same way as the marketplace under validation. Do not fetch
it. A later upstream release that adds a concept a downstream already uses
fails AD2 on the downstream's next run, if the upstream is on disk then; a
prefix of the downstream's own, distinct from the upstream's, is what
prevents it.

AD3 reports a realization-only plugin, and a `realizes` block that names a
concept the marketplace does not define, because a published marketplace
has no way to provide realizations for another published marketplace's
concept; its realizations stay with the concept plugin that defines it. A
`realizes` block is the fenced block described in
[architecture.md §10](../../../../docs/architecture.md#the-realizes-declaration)
(a concept plugin's own realizations need not carry one, so a missing
block is not an AD3 finding), and its `concept` is `<concept>@<marketplace>`.
A marketplace that mixes concept plugins with realization-only plugins is
classified as published (see `validate-concept-plugin`, "How to classify a
marketplace and detect a Concept plugin"), and AD3 reports that mix once,
naming every realization-only plugin, with the message "belongs in a
realization marketplace
([architecture.md §10](../../../../docs/architecture.md#10-realization-marketplaces))".
A plugin that has `skills/concept/` and `skills/realize-*/` but no
`skills/realization-contract/` is reported by `validate-concept-plugin`
check 2, not here.

`validate-concept-plugin` reports, in a published marketplace, a plugin
that has `skills/realization-contract/` or `skills/realize-*/` but no
`skills/concept/` under its check 1, not marked non-blocking there. AD3
reports the realization-only case for the marketplace as a whole, as a
blocking finding. AD3 does not change or downgrade check 1: when both
skills run, the check 1 finding keeps its own severity, and AD3 is the
marketplace-level view of it. In a realization marketplace that same shape
is the expected one, and `validate-concept-plugin` checks it with set E.

**Severity.** A set U or set AD finding marked Blocking fails the
validation. Three stay non-blocking: an open-ended range (U2), a README
range that differs from the entry (U4) and an upstream that is not on
disk (AD2, "unverified"). They report a range this skill does not parse,
wording in the README, or something it could not read, not a wrong
declaration; report them and do not treat them as failing the
validation. M2 is non-blocking too, as it says above. How an existing
marketplace migrates is in
[architecture.md §9](../../../../docs/architecture.md#validator-severity-and-migrating-a-chain).

## How to run the check

1. Locate `.claude-plugin/marketplace.json` at the repo root. If missing,
   stop and report: this isn't a marketplace repo.
2. Parse it; list every entry in `plugins`.
3. For each plugin entry, resolve its path and read
   `.claude-plugin/plugin.json`.
4. Run checks 1–5 above (M1–M5). Then run set U if the marketplace has a
   cross-marketplace dependency or an allowlist, and set AD if it is a
   published marketplace; say which sets you skipped and why. A
   realization marketplace (see `validate-concept-plugin`, "How to
   classify a marketplace and detect a Concept plugin") has no concept
   plugin, so set AD does not apply to it; its own checks are set E in
   `validate-concept-plugin`.
5. Report findings grouped as **Schema issues** (point to official docs)
   vs. **Convention issues** (the guidance marketplace's own opinions),
   each with the file and a one-line fix suggestion. Name each finding's
   check id (M1–M5, U1–U4, AD1–AD3) and whether it is blocking (see
   "Severity" under set AD). Do not silently auto-fix — report and let
   the user decide, unless they've explicitly asked you to fix issues
   found.
