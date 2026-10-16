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

Graph terms name what a concept does in a run, not a role of a repository.
A **node** is a concept with a graph role: a phase, an entry, a refinement
or an observer. A **capability** has no graph role, is never a node, and is
used by name. A **refinement** adds obligations to the one concept it names.
An **observer** runs after nodes and cannot change them. §12 defines them.

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
concept's name is its plugin's name without the marketplace's prefix and its hyphen: `secrets` for `acme-secrets`. The prefix is `metadata.pluginPrefix` in the marketplace's `.claude-plugin/marketplace.json`, written without a trailing hyphen (`acme-aws`, not `acme-aws-`). A malformed value is a block under the F-schema check. When that key is absent, the prefix is the first hyphen-delimited segment of the marketplace's `name`. A plugin whose name does not start with the prefix keeps its full plugin name as its concept name. Whether `claude plugin validate --strict` accepts the `metadata.pluginPrefix` key is not yet verified against the CLI. Concepts are
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

#### Graph fields

A concept may declare its place in a concept graph (§12) in its Tier 1
frontmatter, under one `graph:` key:

- its graph role, and the concept it refines or observes;
- `uses:`, the capabilities it references by name (§5);
- the lifecycle fields, `deprecated`, `replaced_by` and `aliases` (§12).

Its Tier 2 adds the graph contract, and each Tier 3 realization declares how
it runs (§7). Declared references are always qualified,
`<concept>@<marketplace>`.

### 2. Realizations may come from four sources

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
- **Realizations offered by a downstream published marketplace** (§9) —
  non-default realizations and layers of an ancestor's concept. They carry a
  `realizes` block and are never the default.

All four are referenced from `marketplace-plugin-settings.yml` by a
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
reported as stale (§6). The workspace-side check B4 (see [spec/checks.md](../spec/checks.md), Set B) reports a workspace-authored realization outside this location as an error, and B1 does the same for a selected skill whose `realizes` block is missing or malformed, which the workspace cannot find either. Nothing else about where a workspace keeps its skills is checked.

A workspace-authored realization with the same name as an installed one
wins; see "Defaults and collisions" in §10.

#### Workspace concepts, layers and names

- A consuming workspace may keep concepts and refinements of its own in
  `.claude/skills/`, beside its realizations. Their rules are in §12.
- A workspace concept is skills, not a plugin:
  - `.claude/skills/<concept>-concept/` holds its Tier 1 concept;
  - `.claude/skills/<concept>-realization-contract/` holds its Tier 2 contract;
  - each of its realizations is `.claude/skills/realize-<name>/`, with a
    `realizes` block whose `concept` is `<concept>@workspace`.
- `workspace` is a reserved qualifier, so a workspace name never clashes with
  a marketplace's.
- A realization's name comes from its `realizes` block, not from its
  directory. The directory is `realize-<name>`. When two workspace
  realizations share a name for different concepts, the directory of each is
  `realize-<concept>-<name>`.
- A workspace realization may build on another realization of the same
  concept with `builds_on` (§12).

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

#### Switches, several realizations and scopes

Each form extends one concept's entry in the binding file, keyed by the
concept name.

- **Switch off an optional refinement.** Under the refinement's own concept
  key, set `enabled: false`. Only an optional refinement can be switched off.
  A required refinement goes away only when its plugin is disabled (§12).

  ```yaml
  type-check:
    enabled: false
  ```

- **Several realizations at once.** A contract with `selection: many` takes a
  list. For a refinement, each listed realization runs as its own step. For a
  capability, all of them load (§12).

  ```yaml
  notify:
    realization: [email-notify, sms-notify]
  ```

- **Scoped selection.** A concept's entry has a base selection and optional
  scoped selections. The first scope whose `when:` holds wins. Otherwise the
  base applies. Scopes key on run facts only (§12).

  ```yaml
  secrets:
    realization: sops-age
    config: {profile: dev}
    scoped:
      - when: {environment: production}
        realization: vault
        config: {profile: prod}
      - when: {node: deliver}
        realization: sops-age-ci
        config: {profile: ci}
  ```

The workspace runtime checks each listed realization, and the scope that
applies, before every step (§6).

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

**Only a capability may be concept-only.** A concept with a graph role (§12)
always publishes Tier 2, the realization contract, because its frame, input
or result contract is declared there. It may still ship no realization.

A concept-only plugin, which is always a capability, needs only its Tier 1
`skills/concept/SKILL.md`.
**For a capability, Tier 2 (the realization contract) is not required until a first
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
exactly one realization must carry `default: true` in the frontmatter of its `realize-*` SKILL.md (§7), so a workspace that installs a concept with any shipped
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
- A reference by name to a capability is also declared with `uses:` in the
  concept's frontmatter (§12). The prose and the declaration name the same
  concept.
- A declared reference is always qualified, for example
  `uses: [secrets@acme-core]`.

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
to match. The workspace-side checks in [spec/checks.md](../spec/checks.md), Set C, scan for this pattern in a consuming workspace. Check C3 accepts the qualified form where the bare name is ambiguous, and reports any other departure from the table above as a non-blocking style finding.

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

A selection may be scoped, or list several realizations (§3). The check
resolves the scope that applies, and it checks every realization a multiple
selection lists.

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
  realization's own first instruction calls it, in a marketplace repository.
  In a consuming workspace, the workspace runtime calls it before every step
  instead (above).
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
- For a concept with a graph role, add `skills/realization-contract/graph-contract.json`
  beside `schema.json`. It holds `graphSpecVersion`; `selection` (`one`, the
  default, or `many`); `fold` (required with `many`: `all`, `collect` or
  `worst-outcome`); `outcomes` (what the conclude step of a phase, entry or
  refinement can produce); and the JSON Schemas `frame` (when the concept
  accepts refinements), `input` (when it accepts hand-offs) and `result`
  (refinements and observers). A phase or entry must use `selection: one`.
  `contractVersion` stays only in `schema.json`, its one source (§12).
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
  base schema: every field Tier 2 requires stays required, with the same
  type and meaning, and provider-specific fields are added as needed (e.g. `region`, `vault_address`, `profile`). Never
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
- `default: true`, on the one realization that is the concept's default (§4). A realization of an ancestor's concept never carries it.

- Each realization's `SKILL.md` frontmatter declares a `graph:` key (§12):
  - `graphSpecVersion: "1.0"`;
  - `runs: agent` or `runs: command`. `command:` is required only when `runs`
    is `command`, and it is a path relative to the skill directory;
  - `builds_on:`, optionally, the name of another realization of the same
    concept (a layer, §12);
  - `effects:`, optionally, the effects outside the repository: `push`,
    `pull-request`, `deployment` or `external-message`. The default is `[]`.
- The `realizes` block gains a required `name` line (§10).

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

**A concept plugin has at most one Tier 2 realization contract.** If
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
and may carry realizations of its own concepts. B may also define a concept
that refines or observes a concept of A, and may add entry chains that hand
off into A's phases (§12). B may ship non-default realizations and layers of
A's concepts, under §10's rules. None of these changes A's concept: nothing
of A's changes, and nothing runs until a workspace selects it. B may never
replace, redirect or edit a concept defined in A, mark A's default, or reuse
an A plugin name, concept name or prefix. What tells B's plugins apart from
A's is B's own prefix: `acme-secrets` in A, `beacon-key-rotation` in B.

A published marketplace may provide realizations only for concepts of its
ancestors, and only as non-default realizations (§10). For any other concept,
the project type is the realization marketplace (§10).

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
Two findings stay non-blocking: an open-ended version range (U2), and a README range that differs from the entry's (U4), because they report a range the validator does not parse, or README wording.

To migrate, fix what the finding names:

| Finding | Fix |
|---|---|
| U1: a cross-marketplace dependency in `plugin.json` | Move it to the marketplace entry. |
| U2: a string form, or an object with no `version` | Write the object form with `name`, `marketplace` and a `version` range (recipe step 1). |
| U3: a marketplace an entry names is not in the root allowlist | Add it to `allowCrossMarketplaceDependenciesOn` (recipe step 2). |
| U4: no `## Required marketplaces` section, or no row for an allowlisted marketplace | Add the section from the template above. |
| AD1: two plugins define one concept name | Rename one under the marketplace's own prefix. |
| AD2: a plugin name, concept name or prefix equals an upstream's | Rename the plugin or concept under the marketplace's own prefix. If the prefix itself is the overlap, set a `metadata.pluginPrefix` that differs from the upstream's, and rename its plugins to match. |
| AD3: a realization of an ancestor's concept is marked as the default | Remove the default marker. Only the defining marketplace marks a default. A non-default realization of an ancestor's concept is allowed. |

Renaming a published plugin is a breaking change for the consuming
workspaces that use it (see Consequences).

### 10. Realization marketplaces

A realization marketplace offers realizations (Tier 3 only) for concepts
owned by an existing published marketplace. A published marketplace may
realize only its ancestors' concepts (§9). This section covers the project
type for every other concept.

#### Definition and purpose

- It exists so a provider can be added for someone else's concept without
  that concept's defining marketplace having to ship or accept it.
- It targets a contract that is already published: a qualified concept
  name plus a `contractVersion` range (see "The `realizes` declaration").
- It never overrides or extends a concept, and never edits Tier 1 or
  Tier 2. Those stay with the defining marketplace.
- Its realizations are never the default (see "Defaults and collisions").
- A concept-only plugin (§4, which is always a capability) cannot be targeted, because there is no Tier 2
  contract to satisfy; the author asks the defining marketplace to publish
  one first. A plugin with a contract and no realizations can be targeted.
  It has no default, so a workspace must select a realization for it.
- A realization plugin targets one concept. A plugin may ship several
  realizations of it.
- It may ship layered realizations (`builds_on:`, §12). A layer is never the
  default.

#### Who provides realizations

| Source of realizations | May provide | Never |
|---|---|---|
| The concept's defining marketplace | The default (exactly one, in the concept plugin; see §4) and any other realizations | n/a |
| A realization marketplace | Non-default realizations and layers targeting the published contract | Override or extend a concept; edit Tier 1 or Tier 2; ship or mark the default |
| The consuming workspace | Realizations and layers of any concept in the stack, and of its own concepts (§2, §12) | n/a |
| Another published marketplace, downstream (§9) | Non-default realizations and layers of an ancestor's concept, with a `realizes` block | Replace, redirect or edit an ancestor's concept; mark its default; realize a concept that no ancestor defines |

Guidance does not police what a consuming workspace overrides locally:
it may reuse the name of a plugin or skill it has installed, or define
concepts of its own, in whatever way it likes, and those local choices are
outside what guidance validates. The Tier 1 and Tier 2 parts of a
published marketplace's concept plugin are still never edited by a
realization marketplace or by a downstream published marketplace.

#### Directory layout and naming

```
acme-aws-realizations/                       # marketplace name
├── .claude-plugin/marketplace.json          # metadata.pluginPrefix: "acme-aws"
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
- `<prefix>-realize-<concept>` is the recommended plugin name, with the realization marketplace's own prefix (§1). It is a recommendation, and it
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
name: aws-secrets-manager
contractVersion: "^1.1.0"
```
~~~

- `concept` is `<concept>@<marketplace>`. The concept name is as defined
  in §1, and the qualifier is the defining marketplace's own `name`.
  The block is a declaration, not a cross-concept reference in instruction
  text, so the bare-name style of §5 does not apply to it.
- `name` is the realization's name within its concept. The concept and the
  name together identify the realization. A concept plugin's own
  realizations need no block; their name is the directory name minus
  `realize-`.
- `contractVersion` is a semantic-version range, written as in a
  dependency's `version` field (see
  [declaring a version constraint](https://code.claude.com/docs/en/plugins/dependencies#declare-a-dependency-with-a-version-constraint)),
  with no pre-release suffix. A realization is compatible when the Tier 2
  `contractVersion` of the concept it targets satisfies the range (see
  "Version axes").
- The block is required in a realization marketplace and in a
  workspace-authored realization. It is recommended in the realizations
  the defining marketplace ships in its own concept plugin.
- The block carries no default marker. A realization here is never the default (§4). The defining plugin is the entry dependency (next section) whose marketplace equals the qualifier in `concept`.

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

The mechanical check A8, run by the guidance script on every marketplace, refuses the declaration. No plugin with a
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

### 12. Concept graphs

**Experimental.** This section and the graph fields it defines may still
change. It stays experimental until at least two marketplaces other than the
one that defines the root graph use it, and one guidance release has passed
with no MAJOR schema change.

A concept graph is the set of steps a run performs in a consuming workspace,
the order they run in, and what each may do. Each marketplace declares its
part in its own concepts. The declaration format, the JSON Schemas and the
checks are in [`spec/`](../spec/README.md). This section states the rules.

#### Graph roles

- Each concept declares one graph role, or none. A concept with no role is a
  **capability**.
- **phase:** a node with edges. Its outcome picks the next node.
- **entry:** a phase that starts a chain. The chain may run the marketplace's
  own phases and end in one hand-off into an upstream phase.
- **refinement:** `refines: <concept>` names the one concept it adds to. The
  target is a phase, entry, refinement or capability, in its own marketplace
  or an ancestor. A refinement has one parent. Shared behavior belongs in a
  capability that refinements use by name.
- **observer:** `observes:` names what it watches: a phase or entry, `all`, or
  a role filter.
- **capability:** not a node. It never runs on its own. Phases, refinements
  and observers use it by name and declare it with `uses:`.
- A **node** is any concept with a graph role. Capabilities are never nodes.
- There is no role for a phase placed between two upstream phases. It would
  redirect an upstream edge.

#### Frame, support and conclude

Each node runs three steps, in this fixed order:

1. **Frame.** The node's selected realization states what the phase is doing.
   A concept that accepts refinements declares the shape of its frame.
2. **Support.** Each refinement runs in order. It receives the frame, the
   phase input and the results of earlier refinements. A refinement's own
   realization may frame, support and conclude over its own refinements.
3. **Conclude.** The node's realization receives everything and produces the
   deliverable and the outcome. The outcome picks the outgoing edge.

Observers of the node run after conclude. They cannot change anything above.

- The workspace runtime schedules every step, so a model never chooses the
  order. A required refinement always runs.
- Each frame, refinement and conclude step is its own agent session, or a
  command (see runs and declared effects).
- A refinement with no selected realization uses its concept and contract
  skills as the session's instructions.
- A refinement returns its declared result shape, not free text, so the
  parent's context stays bounded. The parent sees results by shape, never by
  who supplied them.
- A refinement's result may be absent, because its `when:` was false. A
  parent's conclude step must accept that.
- A refinement adds obligations and returns its result. It never tightens,
  loosens or replaces what it extends.

#### Recursion and order

- A refinement may itself be refined. Its own refinements run the same frame,
  support and conclude steps.
- A refinement chain more than four levels deep warns.
- A concept's refinements run in this order: upstream depth first, then
  marketplace name, then concept name. Workspace refinements run last.
- `after:` on a refinement or observer names one it can see. A cycle in
  `after:` is an error.
- When two refinements cannot see each other and need another order, the
  workspace pins that order in its own graph.

#### Entries and hand-offs

- An entry chain is its own sequence of phases. Its last phase may hand off
  once, with `handoff:`, into the start of an upstream phase.
- The receiving phase must declare an input contract that covers everything
  it reads from the run's state, not only one payload. A hand-off's output
  validates against that contract.
- A phase with no input contract accepts no hand-offs.
- A chain with no hand-off runs as its own workflow.
- A call names the entry it starts from.

#### Observers

- An observer runs after the node it observes concludes, and before the edge
  is followed. `on:` names the outcomes it runs on: `concluded`, or a list
  such as `[passed, failed]`. It follows the same order, `optional` and
  `when:` rules as a refinement.
- It receives the deliverable, the outcome and the results. It cannot change
  them. Its result is only recorded.
- A failed observer is reported. It never blocks or redirects. A step that
  must be able to block is a gate refinement.
- `observes: all` runs the observer after every phase, entry and refinement
  step in its scope. `observes: {role: phase}` (or `entry`, or `refinement`)
  limits it to one role. Any other role in the filter is refused.
- **Scope.** In a marketplace, the scope is the nodes it could name: its own
  and its ancestors'. It never sees a downstream marketplace's nodes. In a
  workspace, the scope is the whole composed graph.
- **Order.** At each node, observers that name that node run first. Wildcard
  observers run after them, then by the usual order rules.
- **Inputs.** A wildcard observer receives the same inputs as any observer,
  plus the node's id and role. Its `when:` may filter further.
- **Cost.** A wildcard observer runs at every node. The checks and the
  workspace runtime warn when its selected realization is an agent session
  rather than a command.
- An observer never observes another observer.

#### Run facts and when

- `when:` on a refinement or observer lists keys that must all hold. The keys
  `node`, `path_exists` and `setting` are reserved. Any other key is a call
  parameter, such as `environment`.
- Run facts are the call's declared parameters, the node being run, values in
  the workspace's settings file, and whether a path exists in the repository
  at the run's current checkpoint.
- The workspace runtime evaluates them before it schedules a step, and it
  records each value. The same facts always give the same steps.
- When `when:` is false, the step is skipped and recorded as "did not apply".
  A required refinement still runs whenever its condition holds.
- The author sets `when:`. A workspace cannot change it, and can only switch
  off an optional step (§3).
- Run facts never include model judgement. A route chosen by a model-judged
  outcome is not deterministic, so a gate is a command realization.

#### Capability refinements

- A capability is not a node, so its refinements add instructions, not runs.
- A concept declares the capabilities it uses with `uses:`. Its prose
  reference by name is unchanged (§5).
- When a step runs a concept that uses a capability, the workspace runtime
  loads into that session:
  - the capability's skill and its selected realization;
  - every active refinement of it, in the order above, with their selected
    realizations.
- Example: `signing-rules@acme-web` refines `secrets@acme-core` and adds
  signing obligations. Every session that uses `secrets` in a workspace that
  installs `acme-web` loads them.

#### Several realizations at once

- A contract declares `selection: many` and a `fold`: `all`, `collect` or
  `worst-outcome`. The default is `selection: one`.
- The workspace lists several realizations (§3).
- For a refinement, each selected realization runs as its own step, in listed
  order, and the results fold.
- For a capability, every selected realization loads into the session.
- A phase or entry stays `selection: one`, because frame and conclude need one
  owner.
- `worst-outcome` takes the worst outcome, worst first: `failed`, `could-not-be-evaluated`, `passed`, `did-not-apply`. `all` passes only when every selected result passes. `collect` gathers the results, in listed order, for the next step. [spec/README.md](../spec/README.md#fold-values) states each value.

#### Scoped selection

- A concept's settings entry has a base selection and, optionally, scoped
  selections. The first scope whose `when:` holds wins. Otherwise the base
  applies. The form is in §3.
- Scopes key on run facts only.
- The workspace runtime records the resolved selection for each step.

#### Layered realizations

- A realization may declare `builds_on:` the name of another realization of
  the same concept, such as `builds_on: basic-session`.
- A layer satisfies the same contract. The workspace runtime loads the base
  realization's skill first, then the layer's.
- Selecting a layer brings in its base. The base is a realization of the same concept in the same marketplace, or in an ancestor reached through a declared dependency. A base in a sibling or downstream marketplace is refused.
- A layer's own settings sit under its name, against its own schema.
- A layer is allowed wherever a realization is, including a downstream
  marketplace layering on an ancestor's realization. It is never the default
  unless its own marketplace defines the concept.

#### The workspace graph

- A consuming workspace may declare, in its own `.claude/skills/`,
  refinements, observers, entry chains with a hand-off, and capabilities. Their
  layout is in §2.
- The workspace's own concepts are referenced as `<concept>@workspace`.
  `workspace` is reserved for them, so the name never clashes with a
  marketplace's.
- They follow the same rules as a marketplace at the bottom of the stack, and
  they order after every marketplace.
- They are not compiled or committed separately. The workspace runtime
  composes them on each call, and the hash of the composed graph covers them.
- The workspace runtime runs the same checks on them on every call. Guidance's
  own checks never run in a workspace (§6).

#### Lifecycle

Only a concept's own marketplace may change its lifecycle.

- **Deprecate.** The concept declares `deprecated: "reason"`, optionally with
  `replaced_by: <concept>@<marketplace>`. The checks and the workspace runtime
  warn wherever it is named: in refinements, `after:`, hand-offs, `uses:` and
  settings keys. Removing it later is MAJOR.
- **Rename.** The new name declares `aliases: [<old name>]`. Anything that
  names the old name resolves to the new one, with a warning. Dropping an
  alias is MAJOR.
- **Replace.** The owner deprecates the concept with `replaced_by`. A
  downstream marketplace never replaces an upstream concept. It refines the
  concept, or the workspace selects another realization.

#### Interaction values

`interaction:` is declared on a node. It defaults to `autonomous`.

- **autonomous:** the run does not wait for the operator.
- **pause:** the run stops until the operator answers, and the answer is
  validated before the run goes on.
- **conversational:** a live session with the operator. The workspace runtime
  refuses it, and the checks warn, until a deferred session can be resumed
  with the operator's answer.
- A refinement is a scheduled session, so it may use any of the three values. The checks warn on `conversational`, which the workspace runtime refuses. It inherits no interaction limit from its parent.

#### Runs and declared effects

- A realization declares `runs: agent` or `runs: command`.
- `agent`: the step runs as an agent session.
- `command`: the step has no session. The workspace runtime runs the command
  at `command:`, a path relative to the skill directory, and records its exit
  status and output. The activation checks still run first.
- An automated gate is a refinement of the gate phase with a command
  realization. The gate's conclude step folds the results worst-outcome.
- `effects:` lists effects outside the repository: `push`, `pull-request`,
  `deployment` or `external-message`. The default is `[]`. A realization that
  sends a message declares `external-message`.
- The workspace runtime checkpoints each step in git, so a rewind restores the
  files. It cannot undo a declared effect.
- A run has time and token limits. The workspace runtime records what was
  spent.

#### Declaration format

- The declaration is one top-level `graph:` key in the frontmatter of
  `skills/concept/SKILL.md`. Its YAML is the subset in [spec/README.md](../spec/README.md#the-yaml-subset): block-style maps and lists, flow lists and flow maps of scalars, and plain or double-quoted scalars. It has no anchors, tags, aliases, multi-line strings or nested flow collections.
- `graphSpecVersion: "1.0"` is required whenever `graph:` is present.
- Omitting `role` makes the concept a capability.
- A reference in a declaration is always qualified, `<concept>@<marketplace>`,
  except `builds_on`, which names a realization of the same concept, and `when.node`, which may be the bare concept name. `workspace` is reserved for a consuming workspace's own concepts.
- The `## Graph participation` section repeats the declaration. It has one
  bullet per declared field, except `graphSpecVersion`, in declaration order,
  in the form `- **<field>:** <value>`:
  - a scalar is written as it is;
  - a list is its items joined by `, `;
  - `edges` is `outcome → target` pairs joined by `, `;
  - a role filter is `role: phase`;
  - `when:` is `key=value` pairs joined by `, `.
  The checks report any difference between the section and the frontmatter.
  A capability has no role and no such section.

A phase concept, `build` in the `acme-core` marketplace. Prose is omitted.

```markdown
---
name: build
description: Build the change and report whether the build passed.
graph:
  graphSpecVersion: "1.0"
  role: phase
  interaction: autonomous
  edges:
    - outcome: passed
      to: deliver@acme-core
    - outcome: failed
      to: triage@acme-core
  uses: [secrets@acme-core]
---

## Graph participation

- **role:** phase
- **interaction:** autonomous
- **edges:** passed → deliver@acme-core, failed → triage@acme-core
- **uses:** secrets@acme-core
```

A refinement, `type-check`, in the `acme-web` marketplace. It refines the
phase above. It is optional, so the workspace can switch it off (§3).

```markdown
---
name: type-check
description: Type-check the web build when the project declares TypeScript.
graph:
  graphSpecVersion: "1.0"
  role: refinement
  interaction: autonomous
  refines: build@acme-core
  after: [lint@acme-web]
  optional: true
  when: {path_exists: tsconfig.json}
  uses: [secrets@acme-core]
---

## Graph participation

- **role:** refinement
- **interaction:** autonomous
- **refines:** build@acme-core
- **after:** lint@acme-web
- **optional:** true
- **when:** path_exists=tsconfig.json
- **uses:** secrets@acme-core
```

#### Compiled graphs

- Each marketplace that defines graph concepts commits `concept-graph.json` at
  its repository root. Only `guidance_check.py --compile` writes it.
- It records the `graphSpecVersion` and the marketplace's name. It records
  each direct upstream marketplace, with the plugin versions it was authored
  against and that upstream's `graphHash`. It records the nodes, sorted by id,
  each with its declared fields, its contract and its realizations. It records
  the capabilities, and its own `graphHash`.
- `graphHash` is `sha256:` followed by the SHA-256 digest of the canonical
  JSON of the object without `graphHash`:
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
  The file body is `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)`
  followed by a newline.
- There are no timestamps. The same inputs always write the same bytes.
- The checks confirm the file matches a fresh compile, and that each recorded
  upstream hash matches the upstream that resolves (see `spec/`).

#### graphSpecVersion and graph semver

- Every graph declaration, contract and compiled graph carries
  `graphSpecVersion`. The checks and the workspace runtime each declare the
  range they support. The script exits `2` on a file outside its range, with a message that names the supported range and the upgrade. A malformed value is a block under F-schema. The workspace runtime refuses an out-of-range file the same way.
- A plugin's version follows its part of the compiled graph: the nodes, edges,
  contracts and declarations of the concepts it defines.
- A change is **MAJOR** when it:
  - removes a phase or concept, or renames it without an alias;
  - drops an alias;
  - removes an edge;
  - narrows an input, frame or result contract;
  - makes an optional refinement or observer required;
  - adds or narrows a `when:` on a published refinement or observer;
  - changes a contract from `selection: many` to `selection: one`.
- A change is **MINOR** when it:
  - adds phases, entries, refinements, observers or optional inputs;
  - renames a concept with an alias;
  - deprecates a concept;
  - changes a contract from `selection: one` to `selection: many`.
- The checks compare a plugin's part with the compiled graph at its previous
  `<plugin>--v<version>` tag. A plugin with no previous tag has nothing to
  compare, and passes.
- A compiled graph is valid at run time against any installed upstream version
  that satisfies its declared range. A MINOR upstream release only adds. The
  workspace runtime composes with the installed versions, unless the workspace
  pins exact versions, and it records the versions it used.

#### The active stack

- The active stack is the marketplaces and plugins declared in the committed
  project `.claude/settings.json`, with their inherited chains (§9).
- A plugin enabled only at local or user scope is not in the stack. The
  workspace runtime lists it as a warning.
- Guidance and its plugins are never in the stack. The workspace runtime
  excludes them, with a warning. A consuming workspace never registers
  guidance (§6).

#### What counts as a marketplace repository

- The graph checks run only in a marketplace repository: a git repository
  whose top level holds `.claude-plugin/marketplace.json`. §6 gives the full
  test.
- A `marketplace.json` in a subdirectory, a submodule, a fixture, or the target
  of `git -C <dir>` does not qualify.

#### The stated checks

- Each check, with its id, its severity, whether it is mechanical or judgement,
  and where it runs (`marketplace`, `workspace` or `both`), is in
  [`spec/checks.md`](../spec/checks.md). This section does not restate them.
- The mechanical checks run in the `guidance-conventions` script. Judgement
  checks stay in the skills.
- The conformance cases in `spec/conformance/` are the shared reference. An
  implementation of the workspace-side checks must agree with them on the
  checks it shares.

#### Still forbidden

- Editing an upstream concept, its contract or its realizations.
- Inserting a phase between upstream phases, or redirecting an upstream edge.
- Anyone but the defining marketplace marking or changing a concept's default.
- A refinement or observer tightening, loosening or replacing what it extends.
- Replacing another marketplace's concept. Only its owner deprecates it.

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
