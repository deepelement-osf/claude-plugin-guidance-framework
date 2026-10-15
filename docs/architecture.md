# How the guidance marketplace works

This document explains the strategy behind `claude-plugin-guidance` in
plain terms: what problem it solves, how the pieces fit together, and
what a consuming workspace actually gets from a marketplace built this
way. For the base Claude Code plugin/marketplace standard this builds
on, see the official docs linked from the [README](../README.md) — this
document does not restate that standard.

## The four roles

Four roles come up throughout these docs, each named by what it does. A
repo plays a role relative to what it publishes or uses, so one repo can
play more than one — a marketplace that also uses its own plugins is both
a published marketplace and a consuming workspace.

| Role | What it is |
|---|---|
| **guidance marketplace** | `claude-plugin-guidance` itself (`DeepElement/claude-plugin-guidance-framework`): authoring tooling for marketplace authors (`guidance-conventions`, `guidance-activation-check`). It ships no concept plugins. Guidance runs only in a marketplace repository, and a consuming workspace never registers or runs it (§6). |
| **published marketplace** | A marketplace authored with the guidance marketplace that publishes concept plugins (§1). Each concept plugin makes its marketplace that concept's **defining marketplace**. |
| **realization marketplace** | A marketplace that offers realizations for concepts owned by an existing published marketplace (§10). |
| **consuming workspace** | The workspace (a repository or project) that registers and uses marketplaces, selects and configures realizations in `marketplace-plugin-settings.yml` (§3), and may author realizations of its own (§2). |

Bare "workspace" in these docs means a consuming workspace. "Tier" is
reserved for Tier 1/2/3, the three parts inside one concept plugin (§1);
it never names a role or a relationship between roles.

A published marketplace can also build on another one; §9 covers how
those chains are declared and what they may and may not do. §10 covers
realization marketplaces, which offer realizations for a concept someone
else defines. §11 covers what a workspace can do when a realization
breaks.

## The problem

Plugin marketplaces tend to accumulate one plugin per provider: a
Slack-notifications plugin, a Teams-notifications plugin, an
AWS-secrets plugin, a Vault-secrets plugin. Two things go wrong as that
grows:

1. **Duplication.** Every provider-specific plugin re-explains the same
   underlying concept ("send a notification," "fetch a secret") in its
   own words, with its own conventions, its own quality bar.
2. **Lock-in by convenience.** A consuming workspace picks whichever
   provider plugin it installed first. Nothing in the plugin's own
   instructions distinguishes "what this concept does" from "how this
   one provider happens to do it" — so other skills that need the
   concept end up coupled to that one provider's plugin by name, and
   switching providers means rewriting every caller.

The guidance marketplace recommends that a published marketplace be
organized to avoid both, by treating **the concept** — not the provider
— as the unit of distribution.

## The strategy: concepts over providers

Every concept plugin represents one capability, named for what it does
(`acme-secrets`, not `acme-aws-secrets-manager`). Inside that one
plugin, three parts separate "what" from "how":

```
<prefix>-<concept>/
├── concept              (Tier 1 — abstract: what this capability does)
├── realization-contract (Tier 2 — the schema a provider must satisfy)
└── realize-<provider>   (Tier 3 — one or more concrete providers)
```

Examples use `acme-` as a published marketplace's own plugin prefix;
`guidance-` names only the guidance marketplace's own plugins.

- **Anything that needs this capability references the concept by
  name** — never a specific provider. A deployment skill that needs
  secrets says "use the `secrets` concept," full stop. It has no idea,
  and doesn't need one, whether that resolves to AWS Secrets Manager,
  1Password, or a workspace's own internal vault.
- **The realization contract is the seam.** It's a published schema —
  what operations a provider must expose, what configuration it needs
  from the workspace — that any provider implementation must satisfy to
  plug in. This is what makes providers swappable: they're not
  compatible by convention, they're compatible by contract.
- **Providers are interchangeable and extensible.** Where the defining
  marketplace ships a working provider for a concept, a workspace is
  never left with an abstraction and nothing to run — and a workspace
  isn't limited to what the defining marketplace ships, either: it can
  write its own provider skill, satisfy the same contract, and it works
  identically to one the defining marketplace ships. A concept can also
  be published with no provider yet at all (see §4) — a deliberate
  exception, not a gap, for a capability worth naming before anyone has
  built something to back it.

## Where the workspace fits in

A consuming workspace using a published marketplace's concepts makes
exactly one kind of decision, in exactly one file —
`marketplace-plugin-settings.yml` at its root: for each concept, *which
provider* to use, and *what configuration that provider needs*
(credentials, endpoints, account IDs, whatever the provider's contract
calls for).

That's the entire integration surface. Nothing about the workspace's own
skills needs to know which provider is selected — they keep referencing
the concept by name, and the settings file is what resolves that
reference to a concrete implementation at the point of use.

## Why this is safe to adopt: the activation check

The one place this pattern could go wrong quietly is configuration drift
— an update to the defining marketplace renames a provider, or a
workspace never filled in a required credential, and a skill fails deep
inside a provider implementation with a confusing error, or worse,
silently does the wrong thing.

The safeguard is an activation check that runs before any provider does
real work: it reads the workspace's settings, confirms the selected
provider still exists and matches what's configured, and validates every
required configuration value is present. If anything is wrong, the
workspace gets a specific, actionable message — "concept X's selected
provider Y needs config field Z" — instead of a failure buried in
provider-specific logic. This is what makes the pattern trustworthy to
adopt broadly: a missing or stale configuration comes with a clear,
early, blocking message instead of a failure buried in provider logic.
It checks configuration against a schema and nothing more; §6 says what it
cannot catch.

The workspace runtime runs this check before every step in a consuming
workspace. Guidance does not run in a workspace. The guidance skill does
nothing outside a marketplace repository (§6), a consuming workspace never
registers the guidance marketplace to get the check, and a realization
that does not find the guidance skill installed runs its own short inline
config check instead (§7, Tier 3). So the safeguard holds whether or not
guidance is present.

## What adopting this produces

For a consuming workspace:

- One configuration file to manage every marketplace capability it uses,
  regardless of how many concepts or providers are involved.
- The ability to switch providers for any concept — or replace a
  provider shipped by the defining marketplace with an internal one —
  without touching any skill that references the concept.
- A guaranteed default for every concept that ships a realization: it's
  usable immediately after install, with at most some configuration
  values left to fill in, and a clear signal when they're missing. A
  concept published with no realization yet is usable as a stable name
  to reference and build against, even before anything backs it.

For a marketplace author:

- New provider support is additive — one new Tier 3 skill against an
  existing contract, not a new plugin with its own conventions to learn.
- The abstract and contract parts (Tier 1 and 2) rarely change once a
  concept is established, so the surface that could break workspace
  integrations is small and stable.
- Quality and documentation standards apply once, per concept, rather
  than being re-litigated per provider.

## What this is not

This pattern applies to *concept plugins* distributed through a
published marketplace — plugins meant to represent a capability with
swappable providers. It is deliberately more structure than a small,
single-purpose plugin needs, and shouldn't be forced onto one. Whether a
given plugin in a published marketplace should follow this pattern,
versus being a simple, single-tier plugin, is a judgment call made when
the plugin is proposed, not a rule applied universally.

## Detailed design

This section is the precise technical specification for the pattern
described above: how a concept plugin is structured internally, how
realizations are supplied and configured, how the activation check
works, and how one published marketplace may build on another (§9). It
governs the internal design of concept plugins in a published
marketplace — it does not redefine the Claude Code plugin/marketplace
standard itself (directory layout, `plugin.json` schema, skill file
format); see the official docs linked from the README for that.

### 1. A concept plugin represents one "Concept"

Every plugin in a published marketplace's `plugins/` directory that
follows this pattern is a concept plugin and represents one abstract
capability ("Concept"), named for what it does, not for how it's
implemented — e.g. `acme-secrets`, not `acme-aws-secrets-manager`. A
concept's name is its plugin's name without the marketplace's
single-segment prefix: `secrets` for `acme-secrets`. Concepts are
siblings: none depends on another's internal structure. A concept may
*reference* another concept by name alone (see §5) without knowing or
caring which realization backs it in a given workspace.

Each concept plugin contains, as skills within that single plugin:

- **Tier 1 — Concept skill** (`skills/concept/SKILL.md`)
  Describes the capability in provider-agnostic terms: what problem it
  solves, what operations it exposes, when to use it. This is the file
  other concepts' skills reference by name. It contains no knowledge of
  any specific realization.

- **Tier 2 — Realization contract** (`skills/realization-contract/SKILL.md`
  plus a sibling `skills/realization-contract/schema.json`)
  Defines what a realization *must* provide to satisfy this concept:
  - the operations/interface a realization implements (described in the
    SKILL.md prose)
  - the **base input configuration schema** a realization requires from
    the consuming workspace (see §3), as a JSON Schema document in
    `schema.json` — versioned, so both realizations shipped by the
    defining marketplace and workspace-authored realizations can declare
    conformance and be
    validated against it mechanically (see §7 for the schema.json
    convention)
  - the identifying name a realization registers under (used in
    `marketplace-plugin-settings.yml`, see §3)

  This tier is a contract, not an implementation. It never runs on its
  own.

- **Tier 3 — Realizations** (`skills/realize-<provider>/SKILL.md` plus a
  sibling `skills/realize-<provider>/schema.json`, one per concrete
  provider, zero or more — see §4)
  Each is a concrete implementation satisfying the Tier 2 contract for
  one specific provider/technology. Each realization:
  - declares which concept + contract version it satisfies (in SKILL.md)
  - publishes its own `schema.json`, a superset compatible with Tier 2's
    base `schema.json` (see §3, §7)
  - begins its instructions by calling the activation check (§6), if it is
    installed, before doing any real work; otherwise it runs its own inline
    config check (§7, Tier 3)

### 2. Realizations may come from three sources

A concept's usable realizations are the union of:

- **Realizations shipped by the defining marketplace** — Tier 3 skills
  bundled directly in the concept plugin, pre-built bridges for known
  providers.
- **Workspace-authored realizations** — skills living in the consuming
  workspace's own skill collection (e.g. `.claude/skills/`; see
  [where skills live](https://code.claude.com/docs/en/skills#where-skills-live)),
  which declare conformance to a specific concept + Tier 2 contract
  version by name, without needing to live in or be known to the
  defining marketplace.
- **Realizations offered by a realization marketplace** (§10) — Tier 3
  skills in plugins that depend on a concept another published
  marketplace defines.

All three are referenced from `marketplace-plugin-settings.yml` by a
realization name (§3 covers the qualified form) — the settings file
doesn't care where a realization physically lives.

#### Where a workspace-authored realization lives

A workspace-authored realization lives at `.claude/skills/realize-<name>/`
in the consuming workspace: a `SKILL.md` with a sibling `schema.json`,
and the same `realizes` block as any other realization (§10). It is a
skill in the workspace, not a plugin, so it has no `plugin.json` and no
`dependencies`. It never declares guidance. Its first instruction (§6)
calls the activation check if that skill happens to be installed, and
otherwise runs the realization's own inline config check.

This is the location a workspace runtime reads for the realization use
case, and only one level deep: `realize-<name>/` directly under
`.claude/skills/`. It is not a restriction on any other local override
(§10): a workspace may keep whatever else it likes elsewhere, and
guidance does not look. A realization kept elsewhere is simply not a
candidate a workspace runtime will find, so a selection that names it is
reported as stale (§6). `validate-concept-plugin` check B4 reports a
workspace-authored realization outside this location as an error, and B1
does the same for a selected skill whose `realizes` block is missing or
malformed, which the check cannot find either. It checks nothing else
about where a workspace keeps its skills.

A workspace-authored realization with the same name as an installed one
wins; see "Defaults and collisions" in §10.

### 3. Workspace configuration: `marketplace-plugin-settings.yml`

A consuming workspace declares its bindings in a single root-level file:

```yaml
# marketplace-plugin-settings.yml
secrets:
  realization: aws-secrets-manager
  config:
    region: us-east-1
    profile: default

notifications:
  realization: my-custom-slack-bridge   # workspace-authored realization
  config:
    webhook_env_var: SLACK_WEBHOOK_URL
```

- Top-level keys are **concept names**.
- `realization` selects which Tier 3 realization is active for that
  concept in this workspace, by the realization's registered name.
- `config` is validated against **that realization's `schema.json`**
  (which must be compatible with — a superset of — the concept's Tier 2
  base `schema.json`). Realizations are responsible for publishing this
  schema (§1, Tier 3; conventions in §7) so tooling and the activation
  check (§6) can validate a workspace's `config` block without
  inspecting the realization's implementation.
- `realization` is the bare name, or `realization@marketplace` when the
  bare name matches more than one candidate (below).

This is the one file guidance defines for a workspace's binding. Other
binding files a workspace may keep are outside what guidance validates.

#### Register, enable, select

A realization offered by a realization marketplace (§10) reaches a
consuming workspace in three steps, plus a qualification when needed:

| Step | Where | Rule |
|---|---|---|
| 1. Register every marketplace involved | `.claude/settings.json` [`extraKnownMarketplaces`](https://code.claude.com/docs/en/settings-reference#extraknownmarketplaces), under a key equal to the marketplace's `name` | Settings are not transitive; §9 says what the workspace must register. Registering makes realizations available and turns none on. |
| 2. Enable the plugins | `enabledPlugins`, or `claude plugin install` | §9 explains install versus enable. An enabled realization is a candidate for selection. |
| 3. Select | `marketplace-plugin-settings.yml`, `<concept>: realization: <name>` | The one binding file. |
| 4. Qualify, only when ambiguous | `realization: aws-secrets-manager@acme-aws-realizations` | Needed only if the bare name matches more than one candidate. The qualifier is the marketplace that ships the realization. |

```yaml
secrets:
  realization: aws-secrets-manager@acme-aws-realizations
  config:
    region: us-east-1
```

Each step does one thing, so a newly added marketplace never silently
replaces a working realization: it adds candidates and selects none. The
one way it can change what runs is by making a bare name ambiguous, and
that surfaces as a halt that prints the qualified forms to copy, not as a
quiet switch. The collision rules are in "Defaults and collisions" (§10).

**Safe sequence** when a second marketplace will offer a realization name
you already use:

1. Qualify the existing selection first, with the marketplace that ships
   it (for a realization shipped by the defining marketplace, that
   marketplace's own `name`).
2. Register and enable the new marketplace.
3. Only then, if you want the new realization, change the selection to its
   qualified name.

A workspace may rebind which realization serves a concept at any time,
including to one it authored itself (§2). Rebinding is the whole of what
guidance defines for a workspace's use of a concept; anything else a
workspace overrides or defines locally is outside what guidance validates
(§10).

### 4. A concept may be published with no realization at all

A concept plugin is not required to ship a realization to be a valid,
finished plugin. **A concept-only plugin — Tier 1 alone, describing a
capability with no contract and no implementation yet — is a legitimate
end state**, not a half-finished one. This covers two distinct cases,
both valid:

- **Transitional.** The concept is worth naming and standardizing now,
  and a first realization is expected later — from the defining
  marketplace or from a consuming workspace.
- **Permanent.** The concept exists to establish shared vocabulary and
  (once added) a shared contract for an ecosystem of realizations no
  single marketplace author expects to write themselves — e.g.
  published so other plugins, or workspaces, have a stable name to
  reference and build against.

A concept-only plugin needs only its Tier 1 `skills/concept/SKILL.md`.
**Tier 2 (the realization contract) is not required until a first
realization is being added** — writing a contract with nothing yet
implementing it is premature; the contract exists to describe what a
realization must satisfy, so it earns its place at the same time as
that first realization. A concept-only plugin is a complete unit to
publish on its own: add Tier 2 and a first Tier 3 realization in a later
change, whenever one is ready. `validate-concept-plugin` recognizes a
concept-only plugin and doesn't ask for a Tier 2 or Tier 3 you haven't
written.

If a concept *does* ship one or more Tier 3 realizations, the existing
rules still apply in full: Tier 2 must exist and be published, and
exactly one realization must be marked as the default (e.g. via a
`default: true` marker in the contract or an explicit note in the
concept skill), so a workspace that installs a concept with any shipped
realizations can use it immediately, without first having to author or
select one — they may still need to fill in required `config` values,
which is the activation check's job to surface (§6), not a reason the
concept fails to have a usable default. The default belongs to the
defining marketplace; a realization marketplace never ships one (§10).

A concept-only plugin has no default realization and no activation
check to run — there is nothing yet for a workspace to configure or
activate. Anything that references this concept by name (§5) must
handle "no realization currently backs this concept" as an expected
outcome, not an error, until either the defining marketplace ships one or
a workspace authors its own.

### 5. Cross-concept references stay abstract

When one concept's instructions need another concept's capability
(e.g. a deployment concept needing secrets), they reference the other
concept **by name** (its Tier 1 skill) only. They never reference a
specific realization or assume one is active. Resolution of "which
realization backs `secrets` in this workspace" happens the same way for
every caller: consult `marketplace-plugin-settings.yml`, then run the
activation check (§6) before use.

**Required reference style.** Write a cross-concept reference as the
concept name in backticks, exactly as it appears in that concept's
`plugin.json`/directory naming (e.g. `` `secrets` ``) — the same way this
document backtick-quotes concept and realization names throughout. The
bare name is the default, and it is the form for every reference unless
the name is ambiguous (below). A reference is always a concept name in
backticks, never a realization name, and never the concept name dressed
up as a realization-sounding phrase. Treat it like a defined term
referencing an appendix entry: the backticked name is the whole
reference, resolved elsewhere (by the activation check, §6), not a
description of how it's currently resolved.

| Situation | Form |
|---|---|
| The bare name is unique among the concepts enabled in the workspace | Bare: `` `secrets` `` |
| Two enabled concepts share the bare name | Qualified: `` `secrets@acme-concepts` `` |

- Use the qualified form only when the bare name is ambiguous. The
  qualifier is the defining marketplace's `name`, so the reference says
  which concept without naming a realization.
- `secrets@acme-concepts` is a concept name, not a plugin id: the plugin
  that defines it is `acme-secrets@acme-concepts`.
- Ambiguity is judged over every plugin enabled in the workspace, across
  settings scopes. A skill committed to a shared repo therefore cannot
  assume what a teammate has enabled, and qualifying a reference that is
  ambiguous for anyone is the safe choice.
- A bare reference inside a plugin's own text binds to a concept of that
  plugin's own marketplace first, then to concepts of the marketplaces it
  declares dependencies on (§9).
- A realization's `realizes` block (§10) is a declaration and is always
  qualified; this table is about references in instruction text.

For example, a `deploy` concept's Tier 1 or a realization's SKILL.md
should say:

> ✅ To store the value, use the `secrets` concept.

never

> ❌ To store the value, use `aws-secrets-manager` (or "since this
> project uses AWS, save it in Secrets Manager").

The second form leaks a specific realization into a concept that should
have no idea which one is active — it fails even if
`aws-secrets-manager` genuinely is the workspace's configured
realization today, because that binding is exactly what
`marketplace-plugin-settings.yml` and the activation check exist to
resolve, and it can change without this instruction text being updated
to match. `validate-concept-plugin`'s cross-concept reference check
(check C) scans for this pattern and runs proactively any time a Tier 1
or Tier 3 file is authored or edited, not only on an explicit audit
request — see that skill for the mechanical check. Its check C3 accepts
the qualified form where the bare name is ambiguous, reports it as
"unverified" where ambiguity could arise from plugins it cannot see, and
reports any other departure from the table above as a non-blocking style
finding.

### 6. Activation check: a shared convention, not a hook

A dedicated plugin, `guidance-activation-check`, provides a shared skill
that any Tier 3 realization's instructions call first, if it is installed,
before doing real work, passing the concept, the realization's own name and
its own skill directory. A caller that passes names only still works,
without the contract-version gate or the no-entry fallback. The skill's
steps are:

1. Reads `marketplace-plugin-settings.yml` for the concept in question.
2. Confirms which realization applies and that it matches the
   realization currently running: the one the workspace selected, or, with
   no entry for the concept, the defining marketplace's default (see "No
   entry for the concept"). This catches a stale selection after an
   update to the defining marketplace renames or removes a realization.
3. Checks that the installed Tier 2 `contractVersion` satisfies the range
   the realization declares in its `realizes` block (§10, "Version axes").
4. Validates the `config` block against the active realization's
   `schema.json` (§3, §7), reporting specific missing/invalid fields.
5. If anything fails, halts with a clear, actionable message (what's
   missing, which file to edit, which schema to satisfy) **instead of**
   letting the realization proceed and fail deeper or silently
   misbehave.

This is implemented as a shared skill convention (every realization's
SKILL.md is expected to call it, if installed, as its first step) rather
than a Claude Code hook, so it works the same way regardless of how a given
realization is triggered, and doesn't depend on hook mechanics that may
change independently of this pattern.

#### Where the check runs

- **Inside a marketplace repository**, the check is an authoring aid. It
  checks a realization being authored against that repository's own Tier 2
  schema and contract range, and it reads the author's test selection from
  a `marketplace-plugin-settings.yml` at the repository root. With no test
  settings, it reports that there is nothing to check.
- **Outside a marketplace repository, the check does nothing.** It runs no
  check and prints nothing. A directory is a marketplace repository only
  when both of these hold:
  - `${CLAUDE_PROJECT_DIR}/.claude-plugin/marketplace.json` exists;
  - and `git rev-parse --show-toplevel`, run in `${CLAUDE_PROJECT_DIR}`,
    prints `${CLAUDE_PROJECT_DIR}`.

  A `marketplace.json` anywhere else never qualifies, including one in a
  submodule, one in a subdirectory, one in a fixture directory, and one in
  the target of a `git -C <dir>` command.
- **In a consuming workspace, guidance does not run.** The workspace runtime
  runs the activation checks, as this section states them, before every
  step, including command realizations. The workspace runtime implements
  these checks itself, and it does not depend on the guidance marketplace
  being registered, installed or enabled.

A realization plugin never declares `guidance-activation-check`, or any
other guidance plugin, as a dependency. A realization calls the check if it
is installed, and otherwise runs its own short inline config check (§7,
Tier 3). A workspace-authored realization has no plugin, and it follows the
same rule (§2).

#### No entry for the concept

With no entry in `marketplace-plugin-settings.yml`, the defining
marketplace's default (§4) is what applies, but only if it can run
unconfigured:

- A default whose `schema.json` has no required fields runs. The check
  says it is running the default because nothing was selected, so the
  workspace sees that it is relying on one.
- A default whose schema requires config halts, and the message names the
  missing fields. There is no way to run it without values for them.
- A realization that is not the default, and a concept with no default
  (§10), halts as "not selected" or "select one".

A broken or unsuitable default is therefore silent unless the workspace
selects explicitly: the check validates the default's config, not whether
the default is any good for this workspace. A workspace that cares which
realization runs should select it.

#### What the activation check does not do

- It validates `config` against a schema only: required fields and
  declared types. It never calls a live API.
- It does not detect that an external API, CLI or MCP server changed
  behaviour after the realization was written. That breakage first shows
  when the realization runs (§11 covers what to do about it).
- It does not verify credentials, reachability or the realization's own
  logic.
- It does not authenticate its caller; a skill can pass it any
  realization name. It shows consistency, not authenticity.
- It does not gate a skill that merely references a concept (§5). Only a
  realization's own first instruction calls it.
- It cannot always find a workspace's realizations from a linked git
  worktree that has no `.claude/skills` of its own, because Claude Code
  then loads the main checkout's skills. It compares directories after
  resolving real paths, and labels a result **BEST-EFFORT** when the
  workspace root and the caller's directory differ.

The skill needs Claude Code v2.1.196 or later, the version that
substitutes `${CLAUDE_PROJECT_DIR}` in a skill
([substitutions](https://code.claude.com/docs/en/skills#available-string-substitutions)).

### 7. Best practices per tier

These are recommendations, checked (where mechanical) by
`validate-concept-plugin` in `guidance-conventions`. They describe what a
*good* Tier 1/2/3 looks like, beyond the structural minimum in §1–§6.

Run `validate-concept-plugin` against a concept plugin before publishing
a change to it. It checks structure, contract/schema validity, naming,
activation-check invocation and cross-concept reference style, and flags
(non-blocking) any sign the plugin should be split or has drifted from
these conventions.

#### Tier 1 — Concept skill

- State the capability as an action a caller wants, not as a technology
  category — "store and retrieve a secret by name," not "a secrets
  manager." This keeps it easy for another concept to reference without
  absorbing implementation vocabulary.
- Enumerate the operations a realization must support as a short list
  (verbs, inputs, outputs), not prose — this list is what Tier 2 turns
  into a contract.
- Name failure modes the concept can have in the abstract (e.g. "secret
  not found," "not authorized") without naming how any one provider
  reports them. Tier 3 realizations map their provider's actual errors
  onto this vocabulary.
- Never mention a specific provider, SDK, or vendor API in the body
  text. A reader should not be able to guess which realization is the
  default from reading Tier 1 alone.
- **Keep the operations list to one coherent capability, not several.**
  This is a different axis from the bullets above — a Tier 1 skill can
  avoid every provider name and still be too broad, by bundling
  operations for things a reader would naturally call by different
  names (e.g. "post a chat message" and "send an email," the same
  `notifications` example §8 resolves into two sibling concepts, are two
  nouns, not two variations on one capability).
  Ask whether every operation in the list is a variation on the *same*
  verb+object, and whether the concept's "when to use this" reads as one
  scenario or several unrelated ones. Either sign means Tier 1 has
  already drifted into needing more than one contract — see §8 — and the
  fix is to split it into sibling concepts before writing Tier 2, not
  after a second, incompatible realization forces the issue. This check
  works from Tier 1's own prose alone: it doesn't require any
  realization or contract to exist yet, unlike the split-signal check in
  §8, which mainly detects drift once realizations are already there to
  compare.

#### Tier 2 — Realization contract

- Keep the SKILL.md prose focused on the *interface*: which operations
  from Tier 1 map to which required behavior, and what a realization is
  allowed to vary (e.g. performance characteristics, error detail) versus
  required to guarantee (e.g. idempotency, the shape of a returned
  value).
- The `schema.json` sibling file is the base configuration contract —
  keep it minimal. Only include a field here if *every* realization,
  regardless of provider, would need something in that shape (for
  example, most secrets providers need some notion of a "scope" or
  "namespace," even if the field name a given provider uses differs
  after mapping). Provider-specific fields belong in Tier 3's schema,
  not here.
- Version the contract explicitly (a `contractVersion` field in
  `schema.json`, e.g. `"1.0.0"`). Bump it on any breaking change to the
  base schema or required operations, so realizations and the activation
  check can detect incompatibility instead of failing confusingly. What
  counts as breaking, and how this number relates to the plugin's own
  version, is in §10 ("Version axes").
- Write at least one realistic example `config` block satisfying the
  base schema, even though Tier 2 has no concrete provider — this is
  what a workspace-authored realization's author copies as a starting
  point.

#### Tier 3 — Realizations

- Before writing a direct service integration, check whether an
  existing public MCP server or CLI for that provider already covers
  the operations Tier 1 requires, and prefer binding the realization to
  that MCP/CLI over reimplementing the provider's API calls. A
  realization's job is to translate the concept's contract into calls
  against *something* that already speaks to the provider — it doesn't
  need to be the thing that speaks to the provider first. Only fall
  back to a direct integration (e.g. calling GitHub's REST API
  directly instead of binding to an existing GitHub MCP/CLI) when no
  adequate MCP or CLI exists, or when the marketplace author
  deliberately chooses a direct integration for their own reasons
  (tighter control, no extra runtime dependency, etc.) — that choice is
  theirs to make, but binding to a preexisting MCP/CLI is the
  recommended first move, not an equal alternative.
- Name the realization after the provider/technology, not after the
  concept (`realize-aws-secrets-manager`, not `realize-provider-a`) —
  the identifying name in `marketplace-plugin-settings.yml` should be
  recognizable to someone who already knows the provider.
- `schema.json` here must validate as a strict superset of Tier 2's
  base schema: every field Tier 2 requires stays required (or is
  narrowed, never removed or loosened), and provider-specific fields are
  added as needed (e.g. `region`, `vault_address`, `profile`). Never
  reuse a field name from Tier 2's schema with a different meaning.
- Every field in `schema.json` should have a `description` explaining
  what it's for and, where relevant, an example value — this is the text
  a workspace owner reads when filling in `marketplace-plugin-settings.yml`
  for the first time, often with no other documentation in hand.
- Mark optional-but-recommended fields with sensible defaults in the
  schema (`default:`) rather than making everything required — a
  realization should need the smallest config that actually works,
  deferring advanced options to optional fields.
- Call the activation check (§6) as literally the first instruction in the
  realization's SKILL.md, before any operational logic, so it's unambiguous
  that nothing else runs first. Name the skill as
  `guidance-activation-check:check-realization-config`, and pass the
  concept, the realization's own name and `${CLAUDE_SKILL_DIR}`. Call it if
  it is installed. Otherwise run the realization's own short inline check,
  which validates the `config` block against this realization's
  `schema.json`. A realization plugin never declares
  `guidance-activation-check` as a dependency (§10), and a workspace-authored
  realization has no plugin to declare it in (§2).
- If a realization is the concept's pinned default (§4), say so
  explicitly in its SKILL.md (not only in the concept skill), so anyone
  reading the realization file directly still knows its status.

#### The `schema.json` convention (Tier 2 and Tier 3)

A plain [JSON Schema](https://json-schema.org/) document, one per
`skills/realization-contract/` and per `skills/realize-<provider>/`
directory:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "contractVersion": "1.0.0",
  "type": "object",
  "properties": {
    "region": {
      "type": "string",
      "description": "AWS region the secret lives in.",
      "examples": ["us-east-1"]
    },
    "profile": {
      "type": "string",
      "description": "Named AWS CLI profile to use for credentials.",
      "default": "default"
    }
  },
  "required": ["region"]
}
```

Tooling (the activation check, `validate-concept-plugin`) reads this file
directly rather than parsing prose, which is why it exists as a sibling
file instead of embedded narrative in SKILL.md.

### 8. One concept, one realization contract — the split rule

**Every concept plugin has exactly one Tier 2 realization contract.** If
a concept's realizations don't all naturally satisfy one shared
`schema.json`, that isn't a reason to add a second contract to the same
plugin — it's a sign the plugin is actually two concepts.

The tell shows up in Tier 1 before it shows up in Tier 2 — often before
any Tier 2 or Tier 3 exists at all, which is why §7's Tier 1 best
practices already ask you to check operation-list coherence while
Tier 1 is the only thing you've written. A Tier 1 concept skill is
supposed to describe one capability in provider-agnostic terms with a
single, uniform set of operations. If, while writing or extending it,
you find yourself branching — "if the realization is chat-style, do X;
if it's email-style, do Y" — or describing two noticeably different
shapes of configuration a realization might need, Tier 1 has drifted
into realization space. That drift is what eventually forces a second,
incompatible `schema.json` onto the plugin, which breaks the guarantee
every other check in this document relies on (one contract per concept
plugin, checked by `validate-concept-plugin`).

**The fix is to split, not to accommodate.** Pull the diverging part out
into its own sibling concept plugin — its own Tier 1 concept, Tier 2
contract, and Tier 3 realizations — and have the original concept
reference the new one **by name**, exactly as §5 already describes for
any cross-concept dependency. For example, a single `notifications`
concept whose Tier 1 starts describing both "post a chat message" and
"send an email" is two concepts: `notifications-chat` and
`notifications-email`, each with its own contract. A caller that
genuinely needs both keeps referencing each by name; it does not gain
that by one plugin holding two contracts.

This keeps the DRY property of the whole pattern intact: a concept
either has one clean contract every realization satisfies, or it isn't
one concept yet.

### 9. Chains of published marketplaces

A published marketplace B can build on a published marketplace A: a plugin
in B lists a plugin of A in its `dependencies`. A is then **upstream** of
B, and B is **downstream** of A. These two words are used only between
published marketplaces — never for the guidance marketplace, a
realization marketplace, or a plugin-to-plugin relationship.

Claude Code already provides the mechanics: dependencies resolved against
`<plugin>--v<version>` release tags, an allowlist on the root marketplace
for cross-marketplace dependencies, and `claude plugin tag` (see
[Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies)).
It has no manifest field that says "register marketplace X", so a chain
needs a human-readable list of what to register, which lives in the
README (below). Nothing at runtime reads another marketplace's README; the
allowlist is the machine-readable list of names and the README is the
list with registration sources.

#### The additive-only rule

Chains are additive only. B may add new concept plugins with new, unique
concept names, may have its skills reference A's concepts by name (§5),
and may carry realizations of its own concepts. B may not override,
extend or realize a concept defined in A, and may not reuse an A plugin
name, concept name or prefix. What tells B's plugins apart from A's is
B's own prefix: `acme-secrets` in A, `beacon-key-rotation` in B.

Providing realizations for a concept that another published marketplace
defines is a separate project type, the realization marketplace. A
published marketplace has no way to do it, and this section does not
cover it.

#### Authoring recipe: published marketplace B with upstream A

Use official fields only; a custom manifest field is not an option (an
unknown key warns and fails `claude plugin validate --strict`, see the
[marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference#top-level-fields)).

1. Declare each cross-marketplace dependency in B's **marketplace entry**,
   in object form (`name`, `marketplace`, `version`) with a semver range,
   not in `plugin.json`. Only a refusal raised on the entry fails loudly; see
   [depending on a plugin from another marketplace](https://code.claude.com/docs/en/plugins/dependencies#depend-on-a-plugin-from-another-marketplace).
2. Name every marketplace an entry depends on in B's root
   `allowCrossMarketplaceDependenciesOn`. Only the root marketplace's list
   applies to the whole chain.
3. Add the README section below.
4. Default to a caret range on a tested floor (for example `^1.2.0`); see
   [version constraints](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint).
5. Run `claude plugin validate --strict` on the marketplace root and on
   each plugin directory ([CLI reference](https://code.claude.com/docs/en/plugins/cli-reference#plugin-validate)),
   then `validate-marketplace`. An invalid range is reported by Claude Code
   only when it is resolved, so this step does not catch it.

For example, `beacon-concepts` (B) adds `beacon-key-rotation`, which uses
the `secrets` concept of upstream `acme-concepts` (A):

```json
{
  "name": "beacon-concepts",
  "allowCrossMarketplaceDependenciesOn": ["acme-concepts"],
  "plugins": [
    {
      "name": "beacon-key-rotation",
      "source": "./plugins/beacon-key-rotation",
      "dependencies": [
        { "name": "acme-secrets", "marketplace": "acme-concepts", "version": "^1.2.0" }
      ]
    }
  ]
}
```

(Other required manifest fields are omitted here.)

**Upstream duty (A's author).** Tag every released plugin version, as
described in
[releasing a plugin that others depend on](https://code.claude.com/docs/en/plugins/dependencies#tag-plugin-releases-for-version-resolution).
Adding a dependency on a marketplace A did not previously require is a
MAJOR bump of that plugin, because it breaks every downstream allowlist.

#### README template: `## Required marketplaces`

A published marketplace with cross-marketplace dependencies carries this
section. The heading text and column order are exact. Write one row per
marketplace in the root allowlist, with marketplace and plugin names in
backticks. Link, rather than restate, the registration mechanics:
[`extraKnownMarketplaces`](https://code.claude.com/docs/en/settings-reference#extraknownmarketplaces)
and [marketplace sources](https://code.claude.com/docs/en/plugins/marketplace-reference#marketplace-sources).

~~~markdown
## Required marketplaces

Register these in your consuming workspace before installing plugins from this
marketplace. Settings are not transitive; nothing registers them for you. Register
each marketplace under exactly its name below.

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-concepts` | `acme/acme-concepts` (GitHub) | `acme-secrets` `^1.2.0` | Key rotation references the `secrets` concept |
~~~

The section is the author's own statement: nothing verifies that a
registration source is the right one, and the consuming workspace decides
what it registers.

#### What the consuming workspace must do

1. **Register every marketplace in the chain itself**, under a key equal to
   the marketplace's own `name` (see
   [requiring a marketplace](https://code.claude.com/docs/en/plugins/org#require-a-marketplace-and-its-plugins)).
   That means the marketplace the plugin comes from and every upstream
   published marketplace, plus any other marketplace its entries name.
   Settings are not transitive (the guidance marketplace's own statement,
   not the platform's): registering B does not register A. A dependency
   whose marketplace is not registered stays unresolved until you add that
   marketplace (see
   [dependency errors](https://code.claude.com/docs/en/plugins/troubleshooting#dependency-errors)).
2. **Install, not only enable.** Enabling a plugin in `enabledPlugins` and
   installing it are different (see
   [enabled in project settings but not installed](https://code.claude.com/docs/en/plugins/loading#enabled-in-project-settings-but-not-installed)).
   `claude plugin install <plugin>@<marketplace> --scope project` installs a
   plugin together with its dependencies
   ([installing plugins with dependencies](https://code.claude.com/docs/en/plugins/install#plugins-with-dependencies)),
   after which `/reload-plugins` picks them up. Do not assume that a
   committed `enabledPlugins` entry alone brings a plugin's cross-marketplace
   dependencies along for every teammate: observed on Claude Code 2.1.286,
   enabling a relative-path plugin in settings did not by itself install its
   cross-marketplace dependencies, and the docs do not promise either
   behaviour. Treat that as an empirical caveat, not a guarantee, and check
   it on the version you use. A plugin whose dependency is not satisfied is
   reported with a dependency error (see
   [dependency errors](https://code.claude.com/docs/en/plugins/troubleshooting#dependency-errors)).
   A dependency the user already has installed and enabled at the same
   scope skips the allowlist check (see
   [depend on a plugin from another marketplace](https://code.claude.com/docs/en/plugins/dependencies#depend-on-a-plugin-from-another-marketplace)),
   so installing a plugin of an upstream marketplace yourself is the
   workspace's own trust decision.
3. **Select realizations in `marketplace-plugin-settings.yml`** (§3).
   Registering and installing a marketplace never selects a realization.

**Minimum Claude Code version.** Object-form `dependencies` entries and
`name@marketplace` references need a Claude Code release that supports
plugin dependencies. The [plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies)
page states a minimum version beside each behaviour that has one, and this
section does not restate them. One that matters when you test a chain
locally: a dependency entry that names a marketplace also matches a
`--plugin-dir` copy of that plugin on v2.1.242 or later (see
[test a plugin and its dependency locally](https://code.claude.com/docs/en/plugins/dependencies#test-a-plugin-and-its-dependency-locally)).

#### Validator severity and migrating a chain

`validate-marketplace` checks what this section describes in two sets:
set U (U1-U4, the declarations: placement, form, allowlist and the README
section) and set AD (AD1-AD3, the additive-only rule). The first
`guidance-conventions` release after the warnings shipped reported every
finding in them as a warning. The release that makes them block (see the
release tags) can fail a published marketplace, or a realization
marketplace (set U only), that an earlier release passed.
Three findings stay non-blocking: an open-ended version range (U2), a
README range that differs from the entry's (U4), and an upstream
published marketplace that is not on disk (AD2, "unverified"), because
they report a range the validator does not parse, README wording, or
something it could not read.

To migrate, fix what the finding names:

| Finding | Fix |
|---|---|
| U1: a cross-marketplace dependency in `plugin.json` | Move it to the marketplace entry. |
| U2: a string form, or an object with no `version` | Write the object form with `name`, `marketplace` and a `version` range (recipe step 1). |
| U3: a marketplace an entry names is not in the root allowlist | Add it to `allowCrossMarketplaceDependenciesOn` (recipe step 2). |
| U4: no `## Required marketplaces` section, or no row for an allowlisted marketplace | Add the section from the template above. |
| AD1: two plugins define one concept name | Rename one under the marketplace's own prefix. |
| AD2: a plugin name, concept name or prefix equals an upstream's | Rename with the marketplace's own prefix. |
| AD3: a plugin with realizations and no concept of its own, or a `realizes` block naming another marketplace's concept | Move the realizations to a realization marketplace (§10). |

Renaming a published plugin is a breaking change for the consuming
workspaces that use it (see Consequences).

### 10. Realization marketplaces

A realization marketplace offers realizations (Tier 3 only) for concepts
owned by an existing published marketplace. §9 explains why a published
marketplace cannot do this for a concept it does not define; this section
covers the project type that can.

#### Definition and purpose

- It exists so a provider can be added for someone else's concept without
  that concept's defining marketplace having to ship or accept it.
- It targets a contract that is already published: a qualified concept
  name plus a `contractVersion` range (see "The `realizes` declaration").
- It never overrides or extends a concept, and never edits Tier 1 or
  Tier 2. Those stay with the defining marketplace.
- Its realizations are never the default (see "Defaults and collisions").
- A concept-only plugin (§4) cannot be targeted, because there is no Tier 2
  contract to satisfy; the author asks the defining marketplace to publish
  one first. A plugin with a contract and no realizations can be targeted.
  It has no default, so a workspace must select a realization for it.
- A realization plugin targets one concept. A plugin may ship several
  realizations of it.

#### Who provides realizations

| Source of realizations | May provide | Never |
|---|---|---|
| The concept's defining marketplace | The default (exactly one, in the concept plugin; see §4) and any other realizations | n/a |
| A realization marketplace | Non-default realizations targeting the published contract | Override or extend a concept; edit Tier 1 or Tier 2; ship the default |
| The consuming workspace | Its own realizations of a published contract (§2) | n/a |
| Another published marketplace | Nothing for a concept it does not define | Any realization of that concept (§9) |

Guidance does not police what a consuming workspace overrides locally:
it may reuse the name of a plugin or skill it has installed, or define
concepts of its own, in whatever way it likes, and those local choices are
outside what guidance validates. The Tier 1 and Tier 2 parts of a
published marketplace's concept plugin are still never edited by a
realization marketplace or by a downstream published marketplace.

#### Directory layout and naming

```
acme-aws-realizations/                       # marketplace name
├── .claude-plugin/marketplace.json
├── README.md                                # includes ## Required marketplaces
└── plugins/
    └── acme-aws-realize-secrets/            # <prefix>-realize-<concept>
        ├── .claude-plugin/plugin.json
        └── skills/
            └── realize-aws-secrets-manager/
                ├── SKILL.md                 # `realizes` block; activation check first, if installed
                └── schema.json              # superset of the defining plugin's Tier 2 schema
```

- There is no `skills/concept/` and no `skills/realization-contract/`. A
  second copy of the contract would be a second contract (§8).
- A plugin targets exactly one concept and may ship several `realize-*`
  skills for it.
- `<prefix>-realize-<concept>` is the recommended plugin name, with the
  realization marketplace's own prefix. It is a recommendation, and it
  never starts with `guidance-`, which names only the guidance
  marketplace's own plugins.
- Skills are namespaced by their plugin, for example
  `/acme-aws-realize-secrets:realize-aws-secrets-manager`
  ([where skills live](https://code.claude.com/docs/en/skills#where-skills-live)).
- Each realization follows the Tier 3 conventions in §7: named after the
  provider, a `schema.json` that is a strict superset of the Tier 2
  schema, and the activation check (§6) called first, if installed.

#### The `realizes` declaration

Each realization's `SKILL.md` carries a fenced block, in the same
"declared in SKILL.md" convention as §1. It is not a manifest field.

~~~markdown
```realizes
concept: secrets@acme-concepts
contractVersion: "^1.1.0"
```
~~~

- `concept` is `<concept>@<marketplace>`. The concept name is as defined
  in §1, and the qualifier is the defining marketplace's own `name`.
  The block is a declaration, not a cross-concept reference in instruction
  text, so the bare-name style of §5 does not apply to it.
- `contractVersion` is a semantic-version range, written as in a
  dependency's `version` field (see
  [declaring a version constraint](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint)),
  with no pre-release suffix. A realization is compatible when the Tier 2
  `contractVersion` of the concept it targets satisfies the range (see
  "Version axes").
- The block is required in a realization marketplace and in a
  workspace-authored realization. It is recommended in the realizations
  the defining marketplace ships in its own concept plugin.
- There is no default marker. The defining plugin is the entry dependency
  (next section) whose marketplace equals the qualifier in `concept`.

#### Dependency, allowlist and README

A realization plugin's marketplace entry declares one dependency: the
concept plugin it implements, in the object form of §9 with a semver range.
A realization never declares the guidance marketplace or any guidance
plugin (§6). The root marketplace allowlists the defining marketplace, and
the README lists it:

```json
{
  "name": "acme-aws-realizations",
  "allowCrossMarketplaceDependenciesOn": ["acme-concepts"],
  "plugins": [
    {
      "name": "acme-aws-realize-secrets",
      "source": "./plugins/acme-aws-realize-secrets",
      "dependencies": [
        { "name": "acme-secrets", "marketplace": "acme-concepts", "version": "^1.2.0" }
      ]
    }
  ]
}
```

(Other required manifest fields are omitted here.)

The README carries the `## Required marketplaces` section from §9, with a
row for each:

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-concepts` | `acme/acme-concepts` (GitHub) | `acme-secrets` `^1.2.0` | Defines `secrets`; the realizations here target it |

A concept plugin that ships realizations of its own (§4) follows the same
rule: its realizations declare no guidance dependency, and the root does not
allowlist the guidance marketplace.

The authoring recipe, placement rules and what the consuming workspace
must register are those of §9; the dependency is declared on the entry
and not in `plugin.json`, exactly as there. On the consuming workspace's
side, registration is the defining marketplace under its `name`, and
nothing for guidance. Installing a realization plugin with
`claude plugin install` also installs the concept plugin it depends on,
including the realizations the defining marketplace ships in it; §9 says
what enabling alone does not do. Installing is not selecting: a realization
marketplace never turns a realization on for a workspace.

Whether or not `guidance-activation-check` is installed, a realization runs
a config check before its operational logic (§6, §7 Tier 3). Neither path
depends on a guidance plugin being present.

`validate-concept-plugin` check A8 refuses the declaration. No plugin with a
`skills/realize-*/`, whether in a realization marketplace or a concept
plugin that ships realizations of its own, may declare
`guidance-activation-check` or any other guidance plugin on its marketplace
entry, and no root may list the guidance marketplace in
`allowCrossMarketplaceDependenciesOn`. Either is blocking. A8 reads the
declarations only, and `validate-marketplace` set U still checks the range's
form and the README section for the dependencies that remain. A
workspace-authored realization is not a plugin and has nothing to declare
(§2).

#### What a realization marketplace must not contain

- No Tier 1: no `skills/concept/`, and so no concept plugin. The concept
  belongs to its defining marketplace.
- No Tier 2: no `skills/realization-contract/`. The contract is the
  defining marketplace's, referenced by `realizes`, never copied.
- No default realization, and no marker of one. The default of a concept
  is owned by its defining marketplace (see §4).

#### Defaults and collisions

The default of a concept is the one realization its defining marketplace
marks (§4), and only that marketplace can mark one. A workspace's
selection overrides the default for that workspace and never makes
another realization "the default". A realization is identified by the
pair (concept, realization name).

| Case | Rule |
|---|---|
| The same realization name for different concepts | Not a collision. |
| The same name for the same concept from two installed marketplaces | Ambiguous: a bare name cannot say which is meant. The workspace uses the qualified form `realization@marketplace`, whose qualifier is the marketplace that ships it. |
| The same name in two plugins of one realization marketplace | Not allowed: within a marketplace, each (concept, realization name) is unique, so a qualified name resolves to exactly one source. |
| A workspace-authored realization with the same name as an installed one | The workspace's own wins. It is not ambiguous and does not halt. |
| A realization marketplace that wants to replace the default | Not possible by design. The workspace selects the realization explicitly. |

Skills are namespaced by plugin, so a same-named skill never replaces
another by itself
([resolving skills that share a name](https://code.claude.com/docs/en/skills#resolve-skills-that-share-a-name)).
"Wins" in the fourth row is the pattern's own order of
resolution (workspace first, then installed realizations), not a Claude
Code feature.

A newly installed marketplace therefore cannot silently replace a working
realization. If a bare name that was unique becomes ambiguous, the
workspace qualifies it. Qualify the existing selection before installing a
second marketplace that offers the same name.

#### Version axes

Two version numbers are involved, and each has one job.

| Axis | Declared in | Compared by | Job |
|---|---|---|---|
| Plugin version range | The entry's `dependencies[].version` | Claude Code | Installation, and a guard against a MAJOR break in the concept plugin. It does not promise a contract version. A workspace-authored realization has no plugin version. |
| `contractVersion` | Tier 2 `schema.json`; a range in each realization's `realizes` block | The activation check | Compatibility between a realization and the contract. It works the same for all three sources of realizations. |

Rules for `contractVersion`:

1. It is a plain `MAJOR.MINOR.PATCH` string, with no pre-release suffix.
2. A realization declares a range, and is compatible when the installed
   Tier 2 version satisfies it.
3. A breaking change under the superset rule of §7 is a MAJOR bump: a new
   required property or operation, or a narrowed, retyped, removed or
   renamed required element. A new optional element is MINOR. A change
   to descriptions only is PATCH.
4. A plugin release that bumps `contractVersion` MAJOR should also bump
   the plugin's own MAJOR, so the plugin range protects dependents as well.
   This is guidance for the defining marketplace's author, not something
   a tool checks.

### 11. Resilience: when a realization breaks

An external service changes (an endpoint moves, an API version retires,
a CLI renames a flag) and a realization that worked yesterday fails. The
activation check does not see this coming (§6), so the pattern gives
realization authors a rule that keeps the breakage fixable from
configuration, and gives the workspace paths to get unblocked.

#### Rule for realization authors

A realization that talks to an external service exposes, as optional
properties in its `schema.json`, an endpoint (a base URL) and an API or
tool version, and its operations use them. The `default` of each property
is the value the realization was tested against. A knob the realization
ignores does not help, so honouring the property is part of the rule.
Provider-specific fields belong in Tier 3, not in the Tier 2 base schema
(§7), which is why this is a rule for realizations and not part of the
contract. Where a realization has no such external service, its SKILL.md
says so.

#### The workspace's unblock paths

| Path | Where | Needs |
|---|---|---|
| Change config | `marketplace-plugin-settings.yml`, `<concept>.config` | The realization honours the endpoint and version properties |
| Author its own realization against the unchanged contract | `.claude/skills/realize-<name>/` (§2), then select it | The published Tier 2 only |
| Register a realization marketplace that ships a fix | `extraKnownMarketplaces`, enable, select (§3) | Such a marketplace exists |
| Pick another realization of the same concept | Select a different candidate (§3) | Another one is enabled |
| Take the patch from the marketplace that ships the realization | Update the plugin | A released fix inside its dependents' ranges |

If two installed plugins constrain a shared dependency to ranges that do
not overlap, Claude Code fails the later install and auto-update leaves
the dependency where it is, with an entry on the `/plugin` Errors tab
(see [combining constraints from several plugins](https://code.claude.com/docs/en/plugins/dependencies#combine-constraints-from-several-plugins)).
The last three paths can then be blocked: the workspace owner removes or
disables the plugin whose range blocks the update, or asks its author to
widen the range. A realization marketplace's author publishes a new
plugin version promptly after a contract MAJOR (§10, "Version axes").

#### When the contract itself breaks

Breakage in the contract is the defining marketplace's to handle: it
publishes a new Tier 2 `contractVersion` MAJOR (§10, "Version axes"), and
a realization whose declared range excludes that version is incompatible
with it. A workspace that cannot wait defines a new, uniquely named
concept and its own realization, in whatever way it likes; guidance has no
convention for it, and it serves only new callers, since existing skills
keep referencing the old concept.

### Consequences

- Adding a new provider for an existing concept means adding one Tier 3
  skill to the concept plugin (or to a consuming workspace's own
  skills) — Tier 1 and Tier 2 don't change.
- Consuming workspaces get one predictable file
  (`marketplace-plugin-settings.yml`) and one predictable failure mode
  (a clear activation-check block) regardless of which concept or
  realization is involved.
- This pattern adds structure/ceremony that a single-purpose plugin
  doesn't need — it applies to concept plugins in a published
  marketplace, not to every plugin anyone ever writes.
- Publishing a concept ahead of any realization (§4) is a valid way to
  stake out shared vocabulary for a capability before anyone — the
  defining marketplace or a consuming workspace — has built something
  to back it.
- Naming discipline matters: concept names, realization names,
  marketplace names, qualified names (`realization@marketplace`,
  `concept@marketplace`) and contract versions are the join keys across
  settings.yml, Tier 2, Tier 3 and the `realizes` blocks. Renaming any
  of these is a breaking change for consuming workspaces (consistent
  with the plugin-name stability rule in the official plugin standard).
  A mirror or fork of a marketplace must keep its `name`, since the
  qualifiers refer to it.
- The one-contract-per-concept rule (§8) means growth in a published
  marketplace looks like more sibling plugins, not fewer, bigger ones.
  That's a deliberate trade: more plugins to browse, in exchange for
  every installed one staying small enough to reason about and swap
  freely.
