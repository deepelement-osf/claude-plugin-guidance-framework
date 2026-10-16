---
name: validate-concept-plugin
description: Validate that a plugin claiming to be a "Concept" plugin correctly follows the concept/realization architecture (Tier 1 concept, Tier 2 realization contract, Tier 3 realizations, default realization, activation-check invocation), validate the realization plugins of a realization marketplace against the published contract they target, and detect when a concept plugin has drifted into needing more than one realization contract (or is bundling more than one capability into Tier 1) and should be split into sibling concepts. It runs the compliance script first, then performs the judgement checks. Use proactively whenever the user is authoring or editing a plugin under plugins/*/skills/concept/, plugins/*/skills/realization-contract/, or plugins/*/skills/realize-*/, or whenever the user explicitly asks to check/validate/audit a concept plugin, a realization, or whether a plugin should be split. It runs only in a plugin marketplace repository; a consuming workspace never runs guidance checks.
---

# Validate Concept Plugin

Checks the concept plugins of a published marketplace, the realization
plugins of a realization marketplace, and workspace-authored
realizations, against the concept/realization architecture described in
[docs/architecture.md](../../../../docs/architecture.md). Read that
document first if you haven't already — this skill enforces it, it
doesn't restate it.

This skill only applies to plugins/skills that opt into the pattern. It
does not apply to plain, single-tier plugins, and should never demand that
a plugin adopt this structure — only that a plugin or realization which
*has* adopted it (see "How to classify a marketplace" below) does so
correctly.

## Step 1: run the compliance script

Run the script on the marketplace root before anything else:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance_check.py" <repo root>
```

- The script runs every check that
  [spec/checks.md](../../../../spec/checks.md) marks mechanical with scope
  `marketplace` or `both`, with its check id, severity and fix. It also classifies the marketplace and finds the concept
  plugins. Take its result; do not re-derive it.
- Report the script's findings as it prints them, grouped by check id, with each
  file and fix. Do not re-run a mechanical check by hand.
- Exit `0`: passed, possibly with warnings. Exit `1`: blocking findings. Exit
  `2`: the script could not run. Report its message. If the user pointed at one
  plugin directory and not at the marketplace root, the script cannot run; say
  so, and do the judgement checks on the plugin alone.
- Once the script has run, do only the judgement checks below.

## Step 2: the judgement checks

[spec/checks.md](../../../../spec/checks.md) marks the following as judgement, or
as having a judgement part. This skill performs them:

- **A1** Tier 1 abstractness and operation-group coherence.
- **A2** Tier 2 as a contract, not an implementation.
- **A3** provider-specific fields in `schema.json`.
- **A6** optional fields with a sensible default, the knob, and the
  unexplained direct integration.
- **A7** generic realization names.
- **D** (check 10) the split signal.

## How to classify a marketplace and detect a Concept plugin

The script classifies the marketplace under validation as one of:

- **Published marketplace**: at least one plugin has a `skills/concept/`
  directory. Sets A and D apply.
- **Realization marketplace**: at least one plugin has a `skills/realize-*/`
  directory and no plugin has `skills/concept/`. Set E applies.
- **Anything else**: outside this model. Say so and skip the judgement checks.

A marketplace that mixes concept plugins with realization-only plugins is
classified as published. The script reports the mix under AD3 in
`validate-marketplace`.

A plugin is a Concept plugin if it has a `skills/concept/SKILL.md` file. That
file is the sole signal. A concept plugin may legitimately have
`skills/concept/` and nothing else (check 4). In a published marketplace, a
plugin with `skills/realization-contract/` or `skills/realize-*/` but no
`skills/concept/` is reported under check 1. In a realization marketplace that
shape is expected, and set E checks it.

A plugin with none of `skills/concept/`, `skills/realization-contract/` or
`skills/realize-*/` is a plain plugin. Skip it and say so. In a realization
marketplace such a plugin is not skipped: E1 flags it.

## Checks (A: concept plugin structure)

For each Concept plugin found, or the one the user named. Checks 4 and 5 count
and mark realizations, so they apply only to a plugin that has
`skills/concept/`. A realization plugin of a realization marketplace has none of
that structure (see set E).

1. **Tier 1 present and abstract (A1).** The script checks that
   `skills/concept/SKILL.md` exists. The judgement part:
   - The content describes the capability without naming a specific
     provider or vendor in the body. A provider name that appears only as a
     passing example is fine. Flag any Tier 1 file that reads like
     documentation for one particular provider, or that assumes one provider's
     API or behavior.
   - Non-blocking: the operations a realization must support are a short list
     (verb, inputs, outputs), not prose.
   - Non-blocking: failure modes are named in the abstract, for example "not
     found" or "not authorized", not as one provider's error names or codes.
   - **Operation-group coherence (architecture.md §7).** This is a different
     axis from abstraction level. A Tier 1 file can name no provider and still
     be too broad. Read the enumerated operations and ask whether they are all
     variations on one verb and object, for example "store a secret", "retrieve
     a secret" and "delete a secret". Or do they split into two or more groups a
     reader would name differently, for example "post a chat message" and "send
     an email"? Also check whether the concept's "when to use this" reads as one
     scenario or several unrelated ones. Either sign is evidence that Tier 1 is
     bundling more than one concept. Report it as in check 10: non-blocking,
     "consider splitting", with the sibling concepts suggested and the
     operations or scenarios quoted. This works from Tier 1's prose alone, so it
     applies even to a concept-only plugin. As a softer secondary signal, note
     an operations list that is unusually long relative to a typical concept's
     3 to 6 verbs. A high count alone is not proof of a bundled concept.

2. **Tier 2 is a contract, not an implementation (A2).** The script checks that
   `skills/realization-contract/SKILL.md` exists, once the plugin has at least one
   realization (see check 4). Judgement: flag the file if it contains working
   implementation logic rather than a schema or contract definition. That content
   belongs in a Tier 3 realization.

3. **Tier 2 `schema.json` (A3).** The script checks that
   `skills/realization-contract/schema.json` exists, parses as JSON Schema, and
   has a `contractVersion`. Judgement, non-blocking: flag any field that looks
   provider-specific rather than something every realization needs. The
   [`schema.json` convention](../../../../docs/architecture.md#the-schemajson-convention-tier-2-and-tier-3)
   keeps this file minimal.

4. **Realization count (A4).** The script counts the `skills/realize-<provider>/`
   directories. It decides which of the checks below apply.
   - **Zero realizations, and no `skills/realization-contract/`**: a concept-only
     plugin (architecture.md §4). That is a legitimate, permanent or transitional
     end state, not a failure. Report it as such, and say: *"This is a
     concept-only plugin (0 realizations) — a valid, permanent-or-transitional
     state per architecture.md §4. Only Tier 1 applies."* Do not list it as a
     finding.
   - **Zero realizations, but `skills/realization-contract/` exists**: unusual,
     because a contract is normally added with the first realization. The script
     reports this as a warning (A4), which is expected while a contract is
     written ahead of its first realization.
   - **One or more realizations**: all checks 2 to 9 apply, and
     `skills/realization-contract/` is required.

5. **Exactly one default realization (A5).** The script checks that exactly one
   realization carries `default: true` in its `realize-*` SKILL.md frontmatter
   (the rule is in [spec/checks.md](../../../../spec/checks.md#shared-rules)).
   Not applicable to a concept-only plugin.

6. **Superset `schema.json` for each realization (A6).** The script checks that
   each `skills/realize-<provider>/schema.json` exists, parses, and keeps every Tier 2
   required field required, with the same type and meaning. It also checks that each property has a
   description. Judgement:
      - **Optional defaults.** An optional field with a sensible default has one.
     Flag an optional field that has none.
   - **Unexplained direct integration.** If the realization calls a provider's
     REST API itself, rather than binding to an existing MCP server or
     command-line tool for that provider, its SKILL.md should say why.
     Architecture.md §7 prefers the binding. Flag an unexplained direct
     integration for the user to confirm.
   - **A6 knob (resilience rule).** A realization that talks to an external
     service exposes an endpoint (base URL) and an API or tool version as optional
     properties in its `schema.json`, and its SKILL.md uses them, so that a change
     in the service can be absorbed from configuration. The rule is stated once,
     in
     [architecture.md §11](../../../../docs/architecture.md#rule-for-realization-authors).
     This bullet is the single definition of the check, which B3 reuses for a
     workspace-authored realization. It is not part of the Tier 2 check (check
     3), because provider-specific fields belong in Tier 3. It is a judgment
     call. Pass: `schema.json` has a property whose name matches
     `endpoint|base_?url|api_?version` (case-insensitive) and the realization's
     SKILL.md refers to it, or SKILL.md says why no such property applies (for
     example, the realization calls no external service). Fail: neither. Report
     the finding as non-blocking, and name the properties you found, if any, that
     SKILL.md does not use.

7. **Realization naming matches provider, not concept (A7).** Judgement, non-blocking:
   flag any `skills/realize-<provider>/` whose name is generic, or repeats the
   concept name (for example `realize-default`), rather than naming the provider
   or technology it implements.

8. **Activation check first, and no guidance dependency (A8).** Two parts.
   - *Invocation.* Each realization's SKILL.md instructs Claude to run the
     activation check (from `guidance-activation-check`), if installed, before
     doing any real work. A missing call is blocking. A call that is present but
     not the literal first instruction (for example, operational steps come
     before it), or that is not written as "if installed", is non-blocking. A
     consuming workspace does not install the guidance plugin, so an
     unconditional call would fail there. Inside a marketplace repository the
     check validates the realization against its contract. In a consuming
     workspace it does nothing, so the call is harmless there.
   - *No guidance dependency.* The script runs this part on every marketplace,
     realization marketplaces included. No plugin in the marketplace declares a
     guidance plugin as a dependency, and the root does not allowlist the
     guidance marketplace. A guidance plugin is
     `guidance-conventions` or `guidance-activation-check`, from any marketplace,
     or any plugin of the guidance marketplace (`claude-plugin-guidance`).

9. **Naming consistency (A9).** The script checks that the realization names in
   each `skills/realize-*/SKILL.md` are unique within the plugin, and match the
   name rule in [spec/checks.md](../../../../spec/checks.md#shared-rules): the
   directory name minus `realize-`.

10. **Split-signal check (D; architecture.md §8): does this plugin hold two
    concepts?** Judgement, not a hard rule. Always report it as "consider
    splitting", never as a failure, and always show the evidence so the user can
    decide. The three proxies below need a Tier 2 contract or Tier 3
    realizations to compare. For a concept-only plugin, or one with a single
    realization so far, check 1's operation-group coherence check is what catches
    this drift earlier, from Tier 1's prose. Look for these proxies:
    - **Branching language in Tier 1.** `skills/concept/SKILL.md` contains
      conditional phrasing keyed on realization type or provider category (for
      example, "if using a chat-style realization... if using an email-style
      realization...", or "for hosted providers... for self-hosted providers...").
      This is the clearest tell. Tier 1 should describe one uniform set of
      operations, not branch on how a realization implements them.
    - **Low schema overlap across realizations.** Compare the `properties` keys
      across all `skills/realize-*/schema.json` files for this concept. If they
      share little beyond what Tier 2's base schema already requires, most of
      what makes each realization work is realization-specific, not
      concept-shared. That is evidence that the single contract is straining to
      cover two shapes of capability.
    - **Tier 2 itself branches.** `skills/realization-contract/SKILL.md` or its
      `schema.json` describes alternate or optional groups of required fields by
      realization "type", for example a discriminated union, an `if`/`then` in
      the JSON Schema, or prose such as "chat realizations must also provide...
      email realizations must also provide...". A single contract that needs
      internal branching to describe its own realizations shows the same drift
      as Tier 1 branching.

    When any of these appear, report: what was found (with the quoted text or
    field list), why it suggests two concepts, and the suggested split. Give a
    name for each resulting sibling concept, and note that the original plugin's
    Tier 1 should reference the new siblings by name (per §5), rather than absorb
    their contract.

## Workspace-side checks (B and C)

A consuming workspace can author its own realization for a concept, in
`.claude/skills/`, instead of one a marketplace offers
([architecture.md §2](../../../../docs/architecture.md#where-a-workspace-authored-realization-lives)).
The checks of those realizations (B1 to B4) and the cross-concept reference
checks (C1 to C4) run in a consuming workspace, where the workspace runtime
implements them. [spec/checks.md](../../../../spec/checks.md) states each rule,
with its scope `workspace`.

Guidance does not run them. This skill does not check a realization skill kept
outside the marketplace under validation, such as a fixture, and it does not
report them as covered.

## Realization marketplaces (E)

Set E applies only to a realization marketplace. A realization marketplace
contains realization plugins and nothing that defines a concept. What it may
contain, how it targets a contract and how it declares its dependency are in
[architecture.md §10](../../../../docs/architecture.md#10-realization-marketplaces).
This section does not restate them.

The script runs E1 to E5. Look up each id in
[spec/checks.md](../../../../spec/checks.md). The script reads each
realization's fenced `realizes` block in its SKILL.md, and reads the defining
marketplace's Tier 2 through the upstream resolution in Set X of
[spec/checks.md](../../../../spec/checks.md).

Set D does not apply to a realization marketplace, because it holds no Tier 1
or Tier 2. The other judgement parts of this skill apply to realization plugins
as the catalog states. In particular, A6's knob and A7 apply. The script checks A8 on every marketplace.

## Reporting

- State which check sets ran, and which parts were script and which were
  skill, so the user knows what was and was not covered.
- If check 4 finds a concept-only plugin, say so as the message in check 4
  gives it. Do not list it as a finding.
- Give each finding its check id, its file and a one-line fix. Use the catalog
  for each finding's severity. Do not restate severities here.
- Do not silently modify files. Report the findings and let the user decide,
  unless the user has explicitly asked you to fix them.
