---
name: validate-marketplace
description: Validate a Claude Code plugin marketplace repository against DeepElement's guidance conventions (naming, required docs, attribution, and the declarations a published marketplace makes when it builds on another). It runs the compliance script first, then performs the judgement checks itself. Use when the user asks to check, lint, audit, or validate a plugin marketplace repo, or its plugins, for convention compliance.
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

## Step 1: run the compliance script

Run the script on the repository root before anything else:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance_check.py" <repo root>
```

- The script runs every check that
  [spec/checks.md](../../../../spec/checks.md) marks mechanical with scope
  `marketplace` or `both`, with its check id, severity and fix. It also decides which check sets apply. Take its
  applicability from its output; do not re-derive it.
- Report the script's findings as it prints them, grouped by check id, with
  each file and fix. Do not re-run a mechanical check by hand.
- Exit `0`: passed, possibly with warnings. Exit `1`: blocking findings. Exit
  `2`: the script could not run. That covers a directory with no
  `.claude-plugin/marketplace.json`, an upstream that no step can resolve, and
  a guidance pin that does not match the script's version. Report its message
  and stop. A partial run would read as a pass.
- Once the script has run, do only the judgement checks below.

## Step 2: the judgement checks

[spec/checks.md](../../../../spec/checks.md) marks these checks, or the judgement
part of them, as judgement. This skill performs them.

**M1, the name describes the identity (judgement part).** The
`.claude-plugin/marketplace.json` `name` should describe the marketplace's own
identity, for example by matching the repo's purpose. The script checks that
each plugin entry resolves to a real directory, so do not repeat that.

**M3, the README content (judgement part).** The script checks that `README.md`
and `LICENSE` exist. Read the README and check that it:
- describes the marketplace;
- says how to add it (`/plugin marketplace add ...`);
- states its plugin naming convention.

**M4, no restated standard.** Scan README and docs for content that duplicates
or paraphrases the base plugin or marketplace schema, for example a
hand-written list of `plugin.json` fields, or a directory layout diagram that
mirrors the official reference. Flag these as drift risk. Recommend a link to
the official docs page instead, because the base standard can change under a
static description.

**M5, attribution wording.** If the LICENSE contains a public-attribution clause
(not plain MIT, Apache or BSD), confirm the README states the attribution
requirement in plain language, not only by a reference to a LICENSE section
number.

## Checks the script runs

These checks are mechanical. The script runs them. This skill does not repeat
their procedure. Look up the pass rule, the fail rule and the severity for each
id in [spec/checks.md](../../../../spec/checks.md).

- **M2, plugin naming prefix.** Every plugin name starts with the
  marketplace's prefix and a hyphen. The prefix is `metadata.pluginPrefix` in
  `.claude-plugin/marketplace.json`, written without a trailing hyphen
  (`acme-aws`, not `acme-aws-`), or, when that key is absent, the first
  hyphen-delimited segment of the marketplace `name`. A plugin that does not
  match is named by its full plugin name as its concept name. The `guidance-`
  prefix is reserved for the guidance marketplace. A malformed `pluginPrefix`
  is an F-schema block.
- **U1 to U4, upstream declarations (set U).** Cross-marketplace dependencies
  sit in the marketplace entry, use the object form with a version, and are
  allowed by the root allowlist. The README has the `## Required marketplaces`
  section, and its rows match the entries. A dependency on the guidance
  marketplace is refused by A8, which the script runs on every marketplace, and
  set U does not repeat that finding.
- **AD1 and AD2, additive-only chains (set AD).** Concept names are unique, and
  nothing in this marketplace equals a plugin name, concept name or prefix of an
  upstream marketplace that the run resolved. An upstream that cannot be resolved
  stops the run with exit `2`.
- **AD3, realizations stay with their concept.** The rules are:
  - A `realizes` block that names an ancestor's concept is not an error. A
    downstream published marketplace may ship non-default realizations of an
    ancestor's concept, under the realization-marketplace rules in
    [architecture.md section 10](../../../../docs/architecture.md#10-realization-marketplaces).
    - Such a realization is never the default, so it carries no `default: true`
    marker in its `realize-*` SKILL.md. A marker on it is blocking. The default
    marker is described in [spec/checks.md](../../../../spec/checks.md#shared-rules).
  - A `realizes` block whose concept no visible marketplace defines is a
    reference that does not resolve. The script reports it under the reference
    checks.
  - A plugin with a `realize-*` skill that has no `realizes` block, or with
    `skills/realization-contract/`, needs `skills/concept/SKILL.md`. The script
    reports its absence as a blocking A1 finding, with the fix: add the Tier 1
    concept skill, or move the realization to a realization marketplace
    ([architecture.md section 10](../../../../docs/architecture.md#10-realization-marketplaces)).

## Severity

The catalog states each check's severity. Do not restate it here. Known
non-blocking findings are M2, the open-ended range in U2, the range text in U4.

## How to run the check

1. Run step 1 above. If the script exits `2` because this is not a marketplace
   repository, report that and stop.
2. Do step 2 for the judgement checks. M1 to M5 apply to every marketplace.
   If a check set the script did not run applies to this marketplace, say so,
   and say why.
3. Report the findings in two groups:
   - **Schema issues**: point to the official docs above.
   - **Convention issues**: the guidance marketplace's own opinions.

   Under each group, name each finding's check id, whether it is blocking
   (from the catalog), the file, and a one-line fix suggestion. Name the
   source as the script or this skill.
4. Do not auto-fix silently. Report the findings and let the user decide, unless
   the user has asked you to fix them.
