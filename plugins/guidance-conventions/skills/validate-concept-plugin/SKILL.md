---
name: validate-concept-plugin
description: Validate that a plugin claiming to be a "Concept" plugin correctly follows the concept/realization architecture (Tier 1 concept, Tier 2 realization contract, Tier 3 realizations, default realization, activation-check invocation), validate a realization skill kept outside the marketplace under validation (such as a fixture) against a concept's published contract, check that concepts reference each other only by name in the required backtick-quoted form (qualified as `name@marketplace` only when the bare name is ambiguous), validate the realization plugins of a realization marketplace against the published contract they target, and detect when a concept plugin has drifted into needing more than one realization contract (or is bundling more than one capability into Tier 1) and should be split into sibling concepts. Use proactively whenever the user is authoring or editing a plugin under plugins/*/skills/concept/, plugins/*/skills/realization-contract/, or plugins/*/skills/realize-*/ — this always includes scanning for leaked cross-concept references (check C), not just structural checks — or whenever the user explicitly asks to check/validate/audit a concept plugin, a realization, cross-concept references, or whether a plugin should be split. It runs only in a plugin marketplace repository; a consuming workspace never runs guidance checks.
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
*has* adopted it (see "How to detect a Concept plugin" below) does so
correctly.

This skill covers five distinct checks, run independently depending on
what's being authored or what the user asks for:

- **A. Concept plugin structure** — checks 1–9 below (referred to as
  A1–A9), for a concept plugin of a published marketplace, living in the
  `plugins/` tree of the marketplace under validation. Several of them
  also apply to a realization plugin; see "Realization marketplaces
  (E)". Check
  C (below) runs automatically as part of set A whenever a Tier 1 or
  Tier 3 file is authored or edited — it is not gated behind a separate
  audit request.
- **B. A workspace-authored realization** — checks 1–4 in "Validating a
  workspace-authored realization" below (referred to as B1–B4), for a
  realization skill living outside the marketplace under validation
  (such as a fixture that copies a workspace's `.claude/skills/` layout)
  that claims to satisfy a concept plugin's contract. Guidance never runs in
  a consuming workspace (decision 21), so B never checks a workspace's own
  realization.
- **C. Cross-concept reference discipline** — see "Cross-concept
  reference check" below (C1–C4), scanning any concept's Tier 1 or Tier 3
  skill for leaked coupling to a specific realization, and confirming any
  correct reference uses the required backtick-quoted concept-name form,
  qualified only when the bare name is ambiguous (architecture.md §5).
- **D. Split-signal check** — check 10 below, detecting when a concept
  plugin has outgrown the one-contract-per-concept rule and should be
  split into sibling concepts instead of accommodating a second contract
  shape in place.
- **E. Realization marketplace** — see "Realization marketplaces (E)"
  below, for the realization plugins of a realization marketplace: a
  marketplace that offers realizations (Tier 3 only) for concepts a
  published marketplace defines
  ([architecture.md §10](../../../../docs/architecture.md#10-realization-marketplaces)).

## How to classify a marketplace and detect a Concept plugin

Classify the marketplace under validation first. Classification is
structural, per marketplace, and reads only the plugins whose entry has a
relative-path source (see `validate-marketplace` M1 for which entries
that is; say which entries you could not read):

- **Published marketplace** — at least one plugin has a
  `skills/concept/` directory. Sets A, C and D apply.
- **Realization marketplace** — at least one plugin has a
  `skills/realize-*/` directory and no plugin has `skills/concept/`.
  Set E applies, with the applicability of sets A, C and D given under
  "Realization marketplaces (E)".
- **Anything else** — outside this model. Say so and skip every check
  below.

A marketplace that mixes concept plugins with realization-only plugins is
classified as published; `validate-marketplace` reports the mix once
under AD3. If the marketplace root (the directory with
`.claude-plugin/marketplace.json`) cannot be found, for example when the
user points at one plugin directory, say that the marketplace cannot be
classified and detect from the plugin alone, as follows.

A plugin is a Concept plugin if it has a
`skills/concept/SKILL.md` file. Presence of that file is the sole
signal — no `plugin.json` field is required to opt in, and neither is
having any realization-contract or realization yet (see check 4: a
Concept plugin may legitimately have `skills/concept/` and nothing
else). If a plugin in a published marketplace has
`skills/realization-contract/` or `skills/realize-*/` but no
`skills/concept/`, flag that on its own (see check 1) rather than
assuming intent. In a realization marketplace, a plugin with
`skills/realize-*/` and no `skills/concept/` is the expected shape and is
checked by set E, not flagged here.

If a plugin has none of `skills/concept/`, `skills/realization-contract/`,
or `skills/realize-*/`, it's a plain plugin — skip all checks below and
say so. (In a realization marketplace such a plugin is not skipped: E1
flags it.)

## Checks (A: concept plugin structure)

For each Concept plugin found (or the one specified by the user). Checks
4 and 5 count and mark realizations among the realizations of a concept
plugin, so they apply only to a plugin that has `skills/concept/`; a
realization plugin of a realization marketplace has none of that
structure (see "Realization marketplaces (E)"):

1. **Tier 1 present and abstract.** `skills/concept/SKILL.md` exists and
   its content describes the capability without naming a specific
   provider/vendor/technology in the body (a provider name appearing only
   as a passing example is fine; the operations/description should not
   assume one specific provider's API or behavior). Flag any Tier 1 file
   that reads like documentation for one particular provider. Also check,
   non-blocking:
   - the operations a realization must support are enumerated as a
     short list (verb, inputs, outputs) rather than buried in prose
   - failure modes are named in the abstract (e.g. "not found," "not
     authorized") rather than as one provider's actual error names/codes
   - **operation-group coherence (architecture.md §7).** This is a
     different axis from abstraction level above — a Tier 1 file can
     name no provider at all and still be too broad. Read the enumerated
     operations and ask whether they're all variations on one verb+object
     (e.g. "store a secret," "retrieve a secret," "delete a secret" — one
     capability) or whether they split into two or more groups a reader
     would naturally name differently (e.g. "post a chat message" and
     "send an email" — two capabilities). Also check whether the
     concept's own "when to use this" reads as one scenario or several
     unrelated ones. Either sign is evidence Tier 1 is bundling more than
     one concept — report it the same way as check 10's split-signal
     findings (non-blocking, "consider splitting," named sibling concepts
     suggested, quote the operations/scenarios that led to the finding).
     This check works from Tier 1's prose alone and applies even to a
     concept-only plugin with no Tier 2/Tier 3 yet — unlike check 10,
     it doesn't need any realization or contract to exist first. As a
     softer secondary signal, note (but don't treat as disqualifying on
     its own) an operations list that's unusually long relative to a
     typical concept's 3-6 verbs — high count alone isn't proof of a
     bundled concept, but it's worth a second look alongside the
     coherence question above.

2. **Tier 2 present and is a contract, not an implementation** (only
   required once the plugin has ≥1 realization — see check 4).
   `skills/realization-contract/SKILL.md` exists and defines the
   operations/interface a realization implements and the identifying
   name convention a realization registers under. Flag if this file
   contains actual working implementation logic rather than a
   schema/contract definition — that content belongs in a Tier 3
   realization.

3. **Tier 2 `schema.json` present and valid.**
   `skills/realization-contract/schema.json` exists, parses as valid
   JSON Schema, and includes a `contractVersion` field (blocking if
   missing entirely; non-blocking if present but missing
   `contractVersion`). Per the
   [`schema.json` convention](../../../../docs/architecture.md#the-schemajson-convention-tier-2-and-tier-3),
   this should stay minimal — flag (non-blocking) any field that looks
   provider-specific rather than something every realization would need.
   Also flag (non-blocking) if `skills/realization-contract/SKILL.md`
   contains no example `config` block satisfying the base schema — this
   is what a realization author writing a workspace's own realization
   copies as a starting point.

4. **Realization count determines which checks below apply.** Count
   `skills/realize-<provider>/SKILL.md` directories.
   - **Zero realizations, and no `skills/realization-contract/` either:**
     this is a concept-only plugin (architecture.md §4) — a legitimate,
     permanent-or-transitional end state, not a failure. Report it as
     such (see "Reporting" below) and skip checks 2, 5, 6, 7 and the
     realization-contract half of check 3 entirely; only check 1 (Tier 1)
     applies.
   - **Zero realizations, but `skills/realization-contract/` exists:**
     a contract with nothing yet implementing it. This is unusual —
     per §4 a contract is only expected to exist once a first
     realization is being added — so flag it (non-blocking) as worth
     checking whether the contract was published prematurely, but still
     run checks 2–3 against it. Skip checks 5–7 (nothing to check them
     against).
   - **One or more realizations exist:** run all checks 2–9 as normal;
     `skills/realization-contract/` is now required (blocking if
     missing, per check 2).

5. **Exactly one default realization (only if ≥1 realization exists).**
   Among all `skills/realize-*/` directories, exactly one is marked as
   the default (per whatever marker the contract specifies, e.g.
   `default: true` in frontmatter or an explicit statement in the
   realization's SKILL.md). Flag if zero are marked default (workspace
   has no out-of-the-box option) or if more than one claims to be
   default (ambiguous). Not applicable to a concept-only plugin — there
   is nothing to default to.

6. **Every realization publishes a valid, superset `schema.json`.** Each
   `skills/realize-<provider>/schema.json` exists, parses as valid JSON
   Schema, and is a superset of Tier 2's `schema.json` — every field
   `required` in Tier 2 is still `required` here (never dropped or
   loosened), and field types/meanings aren't changed. Missing entirely
   is blocking; present but not a valid superset (e.g. narrows or drops
   a required field) is also blocking, since it silently breaks the
   contract Tier 2 promises. Also check, non-blocking:
   - every property has a `description`
   - optional fields have a `default` where a sensible one exists
   - the realization's own default status (§4 of the architecture doc)
     is stated in its SKILL.md, not only in the concept skill
   - if the realization implements a direct service integration (e.g.
     calling a provider's REST API itself) rather than binding to an
     existing MCP server or CLI for that provider, its SKILL.md doesn't
     explain why (no adequate MCP/CLI exists, or the marketplace author
     chose it deliberately) — per the Tier 3 best practice in
     architecture.md §7,
     binding to a preexisting MCP/CLI is the recommended first move, so
     an unexplained direct integration is worth flagging for the user
     to confirm was intentional
   - **A6 knob (resilience rule).** A realization that talks to an
     external service exposes an endpoint (base URL) and an API or tool
     version as optional properties in its `schema.json`, and its
     SKILL.md uses them, so that a change in the service can be absorbed
     from configuration. The rule is stated once, in
     [architecture.md §11](../../../../docs/architecture.md#rule-for-realization-authors);
     this bullet is the single definition of the check, which B3 reuses
     for a workspace-authored realization. It is not part of the
     Tier 2 check (check 3), because provider-specific fields belong in
     Tier 3. It is a judgment call. Pass: `schema.json` has a property
     whose name matches `endpoint|base_?url|api_?version`
     (case-insensitive) and the realization's SKILL.md refers to it, or
     SKILL.md says why no such property applies (for example, the
     realization calls no external service). Fail: neither. Report the
     finding as non-blocking, and name the properties you found, if any,
     that SKILL.md does not use.

7. **Realization naming matches provider, not concept.** Flag
   (non-blocking) any `skills/realize-<provider>/` whose name is generic
   or repeats the concept name (e.g. `realize-default`) rather than
   naming the actual provider/technology it implements.

8. **Every realization invokes the activation check first, if installed,
   and no plugin declares a guidance plugin as a dependency.** Two parts.
   - *Invocation.* Each realization's SKILL.md instructs Claude to run
     the activation check (from `guidance-activation-check`), if
     installed, before doing any real work. Inside a marketplace repository
     that check validates the realization against its contract (see
     `guidance-activation-check`); in a consuming workspace it does nothing,
     so the realization's call is harmless there. Flag (blocking) any
     realization missing this step entirely; flag (non-blocking) one where
     the invocation is present but not the literal first instruction (e.g.
     operational steps precede it), or where it is not written as "if
     installed" (a consuming workspace does not install the guidance plugin,
     so an unconditional call would fail there).
   - *No guidance dependency.* No plugin in the marketplace under
     validation declares a guidance plugin as a dependency, and the root
     does not allowlist the guidance marketplace. A guidance plugin is
     `guidance-conventions` or `guidance-activation-check`, from any
     marketplace, or any plugin of the guidance marketplace
     (`claude-plugin-guidance`). Flag (blocking), once per plugin, a
     dependency on one of them in the marketplace entry or in
     `plugin.json`, in object or string form (`name@marketplace`), naming
     the plugin and the dependency. Flag (blocking), once for the
     marketplace, a root whose `allowCrossMarketplaceDependenciesOn` lists
     `claude-plugin-guidance`. Consumers never require guidance, so a
     published marketplace never declares it. This part reads the
     declarations only: it does not
     parse any range, and does not check the README (U4). If the
     marketplace root cannot be found, or a plugin's entry cannot be read,
     report that plugin as "unverified" (non-blocking) and say why. A
     workspace-authored realization is not a plugin and declares no
     dependency, so this part does not apply to set B.

9. **Naming consistency.** The realization identifying names used in each
   `skills/realize-*/SKILL.md` are unique within the plugin and match
   what Tier 2 says the naming convention should be (e.g. matching the
   directory name minus the `realize-` prefix).

10. **Split-signal check (§8 of the architecture doc): does this plugin
    actually hold two concepts?** This is a judgment call, not a hard
    rule — always report findings here as "consider splitting," never as
    a failure, and always show the evidence so the user can decide. All
    three proxies below need a Tier 2 contract and/or Tier 3 realizations
    to exist so there's something to compare — for a concept-only plugin
    (check 4) or one with a single realization so far, check 1's
    operation-group coherence sub-check is what can catch this same drift
    earlier, directly from Tier 1's prose, before a second realization
    ever gets built against an already-too-broad concept.
    Look for these structural proxies of drift:
    - **Branching language in Tier 1.** `skills/concept/SKILL.md`
      contains conditional phrasing keyed on realization type or
      provider category (e.g. "if using a chat-style realization... if
      using an email-style realization...", "for X-type providers... for
      Y-type providers..."). This is the clearest tell — Tier 1 should
      describe one uniform set of operations, not branch on how a
      realization implements them.
    - **Low schema overlap across realizations.** Compare the
      `properties` keys across all `skills/realize-*/schema.json` files
      for this concept. If they share little beyond what Tier 2's base
      schema already requires — i.e. most of what makes each realization
      "work" is realization-specific, not concept-shared — that's
      evidence the concept's single contract is straining to cover two
      different shapes of capability.
    - **Tier 2 itself branches.** `skills/realization-contract/SKILL.md`
      or its `schema.json` describes alternate/optional groups of
      required fields depending on realization "type" (e.g. a
      discriminated union, an `if/then` in the JSON Schema, or prose like
      "chat realizations must also provide... email realizations must
      also provide..."). A single contract needing internal branching to
      describe its own realizations is the same drift as Tier 1
      branching, appearing in Tier 2 instead.
    When any of these appear, report it as: what was found (with the
    quoted text or field list), why it suggests two concepts, and the
    suggested split — a name for each resulting sibling concept and a
    note that the original plugin's Tier 1 should reference the new
    sibling(s) by name (per §5) rather than absorbing their contract.

## Validating a workspace-authored realization (B)

Per §2 of the architecture doc, a consuming workspace can author its own
realization for a concept (in `.claude/skills/`, outside the marketplace
under validation) instead of using one a marketplace offers. Guidance never
runs in that workspace (decision 21). This section therefore runs only in a
plugin marketplace repository, against a realization skill kept there in the
same layout, such as a fixture. It does not check a consuming workspace's own
realization; the workspace runtime does that. Use this check when the author
of such a fixture asks to validate one. It applies to a skill that declares
itself a realization of a concept (it carries a `realizes` block, or
`marketplace-plugin-settings.yml` selects it). Any other skill kept outside
the marketplace, including a local override of an installed plugin or skill,
is outside what guidance validates: say B does not apply and stop.

1. **B1. Identify the target concept.** The skill's `SKILL.md` declares
   the concept and contract version it satisfies in the `realizes` block
   ([architecture.md §10](../../../../docs/architecture.md#the-realizes-declaration),
   required in a workspace-authored realization). Apply E2's rules to the
   block. The workspace runtime treats only a skill with a valid block as
   a candidate realization, so a skill that
   `marketplace-plugin-settings.yml` selects (a `realization:` field that
   names it, by its directory name minus `realize-`) and that has a
   missing or malformed block is **blocking**: the workspace runtime
   cannot find it. For a skill that is not selected, report a missing or
   malformed block as non-blocking. If there is no block, ask the user
   which concept plugin it is meant to realize; do not guess.

2. **B2. Locate that concept's contract.** Find the concept plugin's
   `skills/realization-contract/schema.json` and `SKILL.md` (in the
   marketplace under validation, or wherever the concept plugin is
   installed). If the concept plugin isn't available to inspect, report
   that this check can't complete and say what's needed (the concept
   plugin installed or its contract files provided).

3. **B3. Run the same checks as Tier 3 realizations in set A**, applied
   to this workspace skill instead of a `skills/realize-<provider>/`
   directory:
   - it publishes its own `schema.json` (blocking if missing)
   - that `schema.json` is a valid superset of the concept's Tier 2
     `schema.json` (blocking if it drops/narrows a required field)
   - every property has a `description` (non-blocking)
   - it invokes the activation check, if installed, as its first
     instruction (non-blocking if present-but-not-first, blocking if
     entirely absent)
   - the A6 knob (non-blocking): if the skill talks to an external
     service, it exposes and uses an endpoint and an API or tool version
     property, as the [A6 knob](#checks-a-concept-plugin-structure) in
     check 6 defines once

   Giving the skill the same name as a realization an installed
   marketplace offers is not a finding: the workspace's own wins
   ([architecture.md §10](../../../../docs/architecture.md#defaults-and-collisions)).
   Do not flag it, and do not ask whether it was intended.

4. **B4. Location.** A workspace-authored realization lives at
   `.claude/skills/realize-<name>/` in the workspace root, directly under
   `.claude/skills/`, with `SKILL.md` and a sibling `schema.json`
   ([architecture.md §2](../../../../docs/architecture.md#where-a-workspace-authored-realization-lives)).
   That is the location the workspace runtime reads for the realization use
   case; a realization kept elsewhere is not a candidate it can find.
   - **Blocking:** the skill, which B covers because it carries a
     `realizes` block or is selected in `marketplace-plugin-settings.yml`,
     is not at that location (another directory, a nested subdirectory,
     or a name that does not start with `realize-`). Name the required
     path in the finding.
   - **Non-blocking:** the directory carries a `.claude-plugin/plugin.json`.
     That makes it a plugin rather than a workspace skill, which §2 says it
     is not.

   B4 is the only location rule, and where the workspace keeps anything
   else is not checked. A workspace realization also needs no
   `default: true` marker: it is opted into through
   `marketplace-plugin-settings.yml`'s `realization:` field, never as an
   implicit default. The A-set rules on markers and naming are about the
   concept plugins of the marketplace under validation.

Report the same way as set A: blocking vs. non-blocking, file and fix
suggestion per finding.

## Cross-concept reference check (C)

Per §5 of the architecture doc, one concept's instructions may reference
another concept by name only — written as that concept's name in
backticks (e.g. `` `secrets` ``), the required reference style, or as
`` `name@marketplace` `` where the bare name is ambiguous — never a
specific realization, and never assuming one is active. This check runs
**proactively as part of set A**, automatically, any time a Tier 1
(`skills/concept/SKILL.md`) or Tier 3 (`skills/realize-*/SKILL.md`) file
is authored or edited and mentions another concept — it is not gated
behind an explicit "audit cross-concept references" request, though a
user can still ask for it standalone (e.g. to sweep the whole
marketplace at once).

1. **C1. Scan for other concepts' realization names.** For each concept
   plugin found, collect the full set of realization identifying names
   registered by every *other* installed concept plugin (from their
   `skills/realize-*/SKILL.md` files), including those offered by a
   realization marketplace and the workspace's own realizations when they
   are on disk. A realization is also written qualified,
   `realization@marketplace`; collect both forms.

2. **C2. Check for leaked references.** Search this concept's `skills/concept/`
   and `skills/realize-*/` files for any of those other concepts'
   realization names appearing in the instruction text. A reference to
   another concept by its **concept name** (e.g. "use the `secrets`
   concept") is correct and expected — flag only references to a
   specific *realization* of another concept (e.g. "use
   `aws-secrets-manager`" instead of "use the `secrets` concept"). A
   qualified form such as `aws-secrets-manager@acme-aws-realizations` is a
   realization reference, and is flagged the same way; the qualifier does
   not make it a concept reference.

3. **C3. Check the reference is in the required style.** Even when a
   reference correctly names the concept and not a realization, check
   (non-blocking) its form against
   [architecture.md §5](../../../../docs/architecture.md#5-cross-concept-references-stay-abstract):
   - **Bare, backticked** (`` `secrets` ``) is the default and is correct
     whenever the bare name is unique among the concepts you can see. Flag
     prose like "use the secrets capability" or "use Secrets" instead of
     "use the `secrets` concept", which reads as ordinary prose rather
     than as a reference to a term defined elsewhere (that concept's own
     Tier 1).
   - **Qualified, backticked** (`` `secrets@acme-concepts` ``) is accepted
     only when two concepts share the bare name. The qualifier must be the
     defining marketplace's `name` of the concept meant. Flag one whose
     qualifier is not the marketplace that defines a concept of that name.
     For a qualified reference whose bare name is unique among the
     concepts you can see, §5 judges ambiguity over everything a teammate
     may have enabled, so qualifying is not wrong in itself. If any
     source of concept plugins could not be read (a declared dependency's
     marketplace or an enabled plugin that is not on disk, or a settings
     scope you could not read), report it as "unverified" and name what
     could not be read, not as a style finding. Report the finding ("not
     ambiguous in everything visible; use the bare name") only when every
     source you could enumerate was read and the bare name is unique
     across all of them, and still say what you could not see.
   - **Bare, but ambiguous.** Flag a bare reference when two concepts
     share the name and the binding rule in §5 does not settle it (inside
     a plugin's own text, the plugin's own marketplace first, then the
     marketplaces it declares dependencies on); say which qualified forms
     would disambiguate.

   Judge ambiguity over the concept plugins you can see: those of the
   marketplace under validation, those of the marketplaces it declares
   dependencies on that are on disk. Say which of those you could not read.
   When you cannot tell whether a name is ambiguous, report the form
   check as "unverified" rather than as a finding. This is a mechanical,
   low-risk check (unlike check 2's judgment call on leaked realization
   names): a correct-but-unquoted reference is a style fix, not a coupling
   problem.

4. **C4. Check for hardcoded assumptions.** Flag (non-blocking) any
   instruction phrased as though a particular realization is always
   active for another concept (e.g. "since this uses AWS, assume the
   region config is set") rather than resolving it generically through
   that concept's own activation check.

Checks 2 and 4 are inherently best-effort text matching — report those
findings as suggestions to review, not certainties, since
natural-language text can mention a provider name for reasons unrelated
to a hard dependency (e.g. a comparison in documentation). Always show
the matched text so the user can judge intent. Check 3 is closer to
mechanical (does the reference use backticks around the concept name,
and is the form the one its ambiguity calls for) and can be reported more
confidently, except where ambiguity could not be determined.

## Realization marketplaces (E)

Run set E only on a marketplace classified as a realization marketplace
(see "How to classify a marketplace and detect a Concept plugin"); on any
other marketplace say it does not apply. A realization marketplace
contains realization plugins and nothing that defines a concept. What it
may contain, how it targets a contract and how it declares its
dependency are in
[architecture.md §10](../../../../docs/architecture.md#10-realization-marketplaces);
this section only checks them, and does not restate them.

**Applicability for a realization plugin.** Each plugin is checked on its
own, and what runs is:

| Check | Realization plugin |
|---|---|
| A1–A3 (Tier 1, Tier 2) | Skipped: the plugin has neither (E1 requires that). |
| A4, A5 (realization count, default) | Skipped: they are scoped to a plugin that has `skills/concept/`. E5 replaces A5. |
| A6 (valid, superset `schema.json`, and the A6 knob) | Runs. The superset comparison is made against the Tier 2 `schema.json` of the defining plugin, resolved through E3, when that plugin is on disk; otherwise report the superset comparison as "unverified" (non-blocking) and run the rest of A6 locally. The A6 sub-check on stating default status does not apply, because the realization is never the default. |
| A7, A9 (naming) | Run locally. For A9, the naming convention comes from the resolved Tier 2 when it is on disk, and otherwise is the directory name minus `realize-`. |
| A8 (activation check first, no guidance dependency) | Applies, as written in check 8: the invocation, and the ban on a guidance dependency. |
| C (cross-concept references) | Runs as written on the `realize-*` files. |
| D (split signal) | Does not apply: it judges whether a concept's contract needs splitting, and a realization marketplace holds no Tier 1 or Tier 2. |

Set E reads each realization's declaration, a fenced `realizes` block in
its `SKILL.md` (architecture.md §10, "The `realizes` declaration"). The
dependency declarations themselves (object form, placement in the
marketplace entry, allowlist) are checked by `validate-marketplace`
set U, not repeated here.

| Id | Pass | Fail | Severity |
|---|---|---|---|
| **E1** Shape | Every plugin has at least one `skills/realize-*/` and has neither `skills/concept/` nor `skills/realization-contract/` | A plugin with a Tier 2 contract, a Tier 1 skill, or no `skills/realize-*/` | Blocking |
| **E2** `realizes` block | Each `skills/realize-*/SKILL.md` has the `realizes` fenced block; `concept` is `<concept>@<marketplace>` (both parts present); `contractVersion` is a semantic-version range, written as in a dependency's [`version` field](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint), with no pre-release suffix; every skill in the plugin names the same `concept` | A skill with no block, a `concept` with no qualifier, a `contractVersion` that is missing, not a valid range or has a pre-release suffix, or skills in one plugin that name different concepts | Blocking |
| **E3** Defining plugin | The marketplace entry's dependency whose `marketplace` equals the `concept` qualifier is a plugin whose concept name matches the `concept` in the block, and which has a Tier 2 (`skills/realization-contract/`) | No entry dependency on that marketplace, a dependency whose derived concept name differs from the block's, or (when the defining plugin is on disk) a defining plugin with no Tier 2, reported as "no contract to realize" | Blocking |
| | | The defining plugin is not on disk, so its Tier 2 cannot be looked for ("unverified") | Non-blocking |
| **E4** Unique names | Each pair (concept, realization name) occurs once in the marketplace; a realization name is its directory name minus `realize-` | Two skills, in one plugin or two, with the same pair | Blocking |
| **E5** Never default | No realization carries a default marker | A realization carries one: `default: true` in its frontmatter, an explicit statement that it is the default, or the marker the resolved Tier 2 names (check 5) | Blocking |

For E3 the concept name is the defining plugin's name without its prefix,
the first hyphen-delimited segment, as `validate-marketplace` M2 defines
it (`secrets` for `acme-secrets`); it is read from the entry, so it needs
no copy on disk. Only the Tier 2 lookup does. The defining plugin is on disk when
the user gives you the defining marketplace's directory, or when Claude
Code has a local copy of it; read the copy exactly as `validate-marketplace`
describes for set AD ([how a marketplace is found on disk](../validate-marketplace/SKILL.md#additive-only-chains-set-ad)),
and use it only if its `marketplace.json` `name` equals the qualifier.
Do not fetch it. E3 compares names and looks for a Tier 2; it does not
compare `contractVersion` against the declared range, because Claude Code
and the activation check own version resolution.

Set E is blocking, unlike the sets that report on declarations an
existing marketplace may already have made, because it only ever runs on
a marketplace of the new project type: no marketplace that passes today
can start failing because of it.

## Reporting

State which check set(s) ran (A, B, C, D, E, or a combination) before
listing findings, so the user knows what was and wasn't covered.

If check 4 found zero realizations and no `skills/realization-contract/`,
say so plainly and stop there for set A: *"This is a concept-only plugin
(0 realizations) — a valid, permanent-or-transitional state per
architecture.md §4. Only Tier 1 applies; checks 2, 5, 6, 7 and 3's
contract half don't apply here."* This is not a finding to fix — do not
list it under Blocking or Non-blocking.

Otherwise, group findings within each set as:

- **Blocking** — missing Tier 1, missing Tier 2 (when the plugin has
  ≥1 realization), missing or invalid Tier 2 `schema.json`, a
  realization or workspace-authored skill missing `schema.json` or
  whose `schema.json` isn't a valid superset of Tier 2's, zero or
  multiple default realizations among plugins that have ≥1 realization
  (set A only — not applicable to a workspace-authored realization or
  to a concept-only plugin), a realization/workspace skill missing the
  activation-check invocation entirely, a plugin that declares a guidance
  plugin as a dependency, or a root whose allowlist names
  `claude-plugin-guidance` (A8), a
  workspace-authored realization that is not at the location B4 defines,
  a workspace skill selected in
  `marketplace-plugin-settings.yml` whose `realizes` block is missing or
  malformed (B1), and any set-E failure (E1, E2,
  E3 other than "unverified", E4, E5). These mean the plugin/skill
  cannot be used as documented, or silently breaks the contract, and
  should be fixed before merging/publishing/using it.
- **Non-blocking** — a `skills/realization-contract/` published with
  zero realizations yet to satisfy it, missing `contractVersion`,
  missing example config block, missing field descriptions/defaults,
  undocumented default status, an unexplained direct service
  integration where a preexisting MCP/CLI binding was preferred and no
  rationale is given, generic realization naming, activation check
  present but not first, naming drift, un-enumerated operations,
  non-abstract failure modes, or a bundled/incoherent operations group
  (check 1's breadth heuristic) in Tier 1, any set-C cross-concept
  reference finding (leaked realization name, unquoted reference style,
  a qualified reference with the wrong qualifier or whose bare name is
  unique in every source you could read, an ambiguous bare reference, or
  hardcoded realization assumption), a malformed or missing `realizes`
  block in a workspace skill that is not selected (B1) or a
  `.claude-plugin/plugin.json` in a workspace realization's directory
  (B4), a qualified reference reported "unverified" (C3), and any set-D split-signal
  finding (all always non-blocking — they're evidence-based judgment
  calls for the user to weigh, never certainties), the A6 knob finding
  (also a judgment call), and an E3 "unverified" or an A6 superset
  comparison reported "unverified" because the defining plugin is not on
  disk, and an A8 dependency check reported "unverified" because the
  marketplace entry could not be read. These degrade the
  guarantees the architecture doc promises (clear config errors,
  swappability, self-explanatory config, loose coupling, one contract
  per concept) but don't make the plugin unusable outright.

For each finding, give the file and a one-line fix suggestion. Do not
silently modify files — report and let the user decide, unless they've
explicitly asked you to fix issues found.
