# Check catalog

This catalog is the one statement of the checks. Guidance's compliance script
(`plugins/guidance-conventions/scripts/guidance_check.py`) runs the mechanical
`marketplace` and `both` rows. The authoring skills, [validate-marketplace](../plugins/guidance-conventions/skills/validate-marketplace/SKILL.md)
and [validate-concept-plugin](../plugins/guidance-conventions/skills/validate-concept-plugin/SKILL.md),
run the judgement rows and link here for the rest. Nothing else restates a
check's pass, fail, severity or kind.

Any implementation of the workspace-side checks runs the `workspace` rows and
the `both` rows, and must agree with the script on the `both` rows.

## How to read the tables

- **Severity.**
  - `block` fails the run. The script exits `1`.
  - `warn` is reported, and the run still passes. The script exits `0`.
  - A run that cannot finish exits `2`. Such a row says so in its fails-when
    column.
- **Kind.**
  - `mechanical` rows are decided by the script.
  - `judgement` rows are read by a skill. Every judgement row is `warn`, so no
    judgement row blocks a commit.
- **Scope.**
  - `marketplace` rows run on a marketplace repository only. [SCOPE](#set-scope-where-the-checks-run)
    defines that test.
  - `both` rows run on a marketplace repository and in a consuming workspace.
  - `workspace` rows run in a consuming workspace only. The script and the
    skills do not run them.
- **Implemented by.** `script` or `skill`. A `workspace` row is implemented by
  an implementation of the workspace-side checks.
- **Split checks.** A check split into parts has one row per part. The id repeats.
  Where a part needs its own label, the label is in brackets, such as
  `A6 (knob)`.
- **Conformance.** Each id that has cases lists them under
  `spec/conformance/<check-id>/pass/` and `spec/conformance/<check-id>/fail/`.
  [spec/conformance/README.md](conformance/README.md) lists the ids that have cases.

## Shared rules

Each rule below is stated here once. The rows refer to it.

- **Default marker.** A concept's default realization carries `default: true`
  in the frontmatter of its `realize-*` SKILL.md. When a concept has
  realizations, exactly one of them is marked (A5). A realization of a concept
  the marketplace does not define is never the default, and carries no marker
  (AD3). A realization marketplace marks none (E5).
- **Realization name.** A realization's name is its directory name minus
  `realize-`. Within a concept, each name occurs once in a marketplace (A9, E4).

## Set F: declaration files and schemas

Set F reads the graph declarations, the Tier 2 graph contracts, the compiled
graph and the schemas that validate them. The graph rules are in
[architecture.md §12](../docs/architecture.md).

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| F-official | `.claude-plugin/marketplace.json` and every `plugin.json` pass `claude plugin validate --strict`. | Either fails the official validator. The finding quotes the validator. Guidance does not restate that schema. If the validator cannot run, the run exits `2`. | block | mechanical | marketplace | script |
| F-files | Every concept with a graph role has `skills/concept/SKILL.md` and `skills/realization-contract/graph-contract.json`, with `schema.json` beside it. A capability needs only `skills/concept/SKILL.md`, unless it has realizations. | A required file is missing. | block | mechanical | both | script |
| F-agree | The `## Graph participation` section has one bullet per declared field, except `graphSpecVersion`. The bullets are in declaration order, each in the form `- **<field>:** <value>`, and each value is written as the field reference defines it. | A bullet is missing, extra, out of order, or differs from the frontmatter. | block | mechanical | both | script |
| F-tier2 | `graph-contract.json` has `graphSpecVersion`, and each key its role requires: `outcomes` for a phase, entry or refinement; `frame` for a concept that accepts refinements; `input` for a concept that accepts hand-offs; `result` for a refinement or observer. `selection` is optional, and defaults to `one`. | A required key is missing. | block | mechanical | both | script |
| F-tier3 | Each `skills/realize-*/SKILL.md` has a `graph:` block with `graphSpecVersion` and `runs`. `command` appears only when `runs` is `command`, and it names a file that exists relative to the skill directory. `builds_on`, when present, names another realization of the same concept. `effects` holds only `push`, `pull-request`, `deployment` or `external-message`, or is empty. | Any of those is missing or wrong. | block | mechanical | both | script |
| F-capability | A capability has no `role`, `interaction` or `edges`, and no `## Graph participation` section. | A capability declares any of them. | block | mechanical | both | script |
| F-binding | Every `realizes` block has a qualified `concept`, a `name` and a `contractVersion` range. Every `handoff` names a target that has an input contract. Every capability a concept refers to by name in backticks is listed in its `uses:`. | A `realizes` block lacks one of the three parts, or its `concept` is not qualified. A `handoff` target has no input contract. A capability named in backticks is not in `uses:`. | block | mechanical | both | script |
| F-compiled | `concept-graph.json` exists at the marketplace root, validates against the compiled-graph schema, and is byte-identical to a fresh `--compile` of the committed files. | The file is missing, invalid or stale. The fix is `guidance_check.py --compile`. | block | mechanical | marketplace | script |
| F-schema | Every graph declaration, `graph-contract.json` and `concept-graph.json` validates against guidance's JSON Schemas with no extra keys. Its `graphSpecVersion` is one the script supports. A `metadata.pluginPrefix` in `marketplace.json`, when set, is lowercase letters and digits with single hyphens between them. | A key is unknown, a value has the wrong type or form, or a `metadata.pluginPrefix` is malformed. A file's `graphSpecVersion` that is malformed is a block. One outside the supported range exits `2`, with a message that names the supported range and the upgrade. | block | mechanical | both | script |
| F-selection | A phase or entry contract has `selection: one`, or no `selection`. `fold` appears only with `selection: many`. | A phase or entry has `selection: many`. Or `fold` is present with `one`, or missing with `many`. | block | mechanical | both | script |
| F-interaction | `interaction` is `autonomous`, `pause`, `conversational`, or absent, on a node. | `interaction` has any other value. | block | mechanical | both | script |
| F-interaction | `interaction` is not `conversational`. | A concept declares `conversational`. The workspace runtime refuses that value, so the script warns until the round trip is proven. | warn | mechanical | both | script |

## Set X: upstream chain

Set X checks the upstream chain. It reads the versions and hashes the compiled
graph records, and it resolves each upstream. Each upstream resolves in this
order, and the first step that finds it is used:

1. Claude Code's registered copy, if it is at the recorded version.
2. The script's cache under `${CLAUDE_PLUGIN_DATA}` (or
   `~/.cache/guidance-conventions` when unset).
3. A git fetch of the `<plugin>--v<version>` tag from the source in the
   committed settings.

An author may pass `--upstreams DIR`. The directory is then the only source,
and the three steps above are not tried. The chain is walked: each resolved
upstream's own recorded upstreams are resolved the same way. The same
resolution gives the defining marketplace that E3 reads and the upstream that
AD2 compares against.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| X-versions | Each upstream version recorded in `concept-graph.json` satisfies the range the marketplace declares for it. | A recorded version lies outside its declared range. | block | mechanical | marketplace | script |
| X-newer | No newer version within a declared range is known to Claude Code or the script's cache. | A newer in-range version exists. Recompiling would pick it up. If tags cannot be listed, the script skips this warning and says so. It never exits `2` on its own. | warn | mechanical | marketplace | script |
| X-resolve | Every direct and transitive upstream resolves by one of the steps above. | An upstream cannot be resolved by any step. The run cannot finish, so it exits `2`. | block | mechanical | both | script |
| X-resolve | Every `builds_on` target is a realization of the same concept, in this marketplace or in an ancestor reached through a declared dependency. | A `builds_on` target is missing, or is a realization of the same concept in a sibling or downstream marketplace. | block | mechanical | both | script |
| X-placement | Every target of `refines`, `observes`, `handoff`, `realizes` and `after:` exists. It is in this marketplace, or in an ancestor reached through a declared dependency. Every `uses:` target exists and may be in a sibling marketplace. | A target is missing. A `refines`, `observes`, `handoff`, `realizes` or `after:` target is in a sibling or downstream marketplace. A `uses:` target is downstream. | block | mechanical | both | script |
| X-roles | A `refines` target is a phase, entry, refinement or capability. An `observes` target is a phase or an entry, `all`, or a role filter naming only `phase`, `entry` or `refinement`. A `handoff` target is a phase. | A `refines` target has another role. An `observes` target is another role, or a filter naming another role. A `handoff` target is not a phase. The input contract of a hand-off target is checked by F-binding. | block | mechanical | both | script |
| X-roles | No wildcard observer runs a session at every node. A wildcard observer is one with `observes: all` or a role filter. | A wildcard observer whose realization is a session. In a marketplace, that is the default realization. The run warns, because the session would run at every node in scope. | warn | mechanical | both | script |
| X-contracts | Each `contractVersion` range is satisfied by its target contract. A realization's `schema.json` is a superset of the upstream Tier 2 `schema.json`. A hand-off's output validates against the target's input contract. A refinement's result is accepted by its parent's frame. | Any of those comparisons fails. | block | mechanical | both | script |
| X-additive | AD1 to AD3 run with every upstream resolved. Remove from the composed graph every refinement, observer and entry chain this marketplace contributes, and keep the targets of its hand-offs. What remains equals the union of the upstream compiled graphs in node ids, roles, edges, interaction values and input contracts. | Any difference in that remainder, naming the node or edge. Also: a phase inserted between upstream phases, an edge removed or redirected, or an ancestor's realization marked as the default. | block | mechanical | both | script |
| X-order | The `after:` relations across the whole chain form no cycle. | A cycle. The finding names its members. | block | mechanical | both | script |
| X-depth | A refinement chain is no deeper than 4. | A refinement chain is deeper than 4. | warn | mechanical | both | script |
| X-depth | A `refines` chain does not loop, so its depth is defined. | A `refines` chain loops. Its depth has no value, so it blocks. | block | mechanical | both | script |
| X-hashes | Each upstream `graphHash` recorded in `concept-graph.json` equals the `graphHash` of the upstream resolved for that version. | A recorded hash differs from the resolved upstream's hash. The upstream changed without a version change, or the recorded hash was edited. Check the upstream, then recompile. | block | mechanical | marketplace | script |
| X-lifecycle | Every name the marketplace uses resolves to a concept, an alias, or a deprecated concept. | A name that was removed upstream. | block | mechanical | both | script |
| X-lifecycle | The marketplace uses no deprecated concept, and no alias. | A use of a deprecated concept, or of an alias. The finding names the `replaced_by` target when one is declared. | warn | mechanical | both | script |

## Set V: graph semver

Set V compares each plugin's part of the graph with its compiled graph at the
plugin's previous `<plugin>--v<version>` release tag. A plugin's part is the
nodes, edges, contracts and declarations of the concepts it defines. A plugin
with no previous tag has nothing to compare, so it passes.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| V-major | A MAJOR graph change has a MAJOR version bump. | A MAJOR change, with no MAJOR bump. MAJOR changes are: removing a phase or concept; renaming one without an alias; dropping an alias; removing an edge; narrowing an input, frame or result contract; making an optional refinement or observer required; adding or narrowing a `when:` on a published refinement or observer; changing a contract from `selection: many` to `one`. | block | mechanical | marketplace | script |
| V-bump | A plugin whose directory changed since its previous release tag has a version bump. | Its directory changed, and its version did not. | warn | mechanical | marketplace | script |

MINOR changes have no check of their own. A MINOR change still moves the
version, and V-bump covers the case where it does not.

## Set A8 and AD3: amended checks

A8 forbids a guidance dependency. AD3 covers the defaults of realizations of
an ancestor's concept.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| A8 | No plugin declares a guidance plugin as a dependency. The script runs this on every marketplace, realization marketplaces included. A guidance plugin is `guidance-conventions` or `guidance-activation-check`, from any marketplace, or any plugin of the guidance marketplace. The root `allowCrossMarketplaceDependenciesOn` does not list the guidance marketplace. | A dependency on one of them, in a marketplace entry or a `plugin.json`, in object or string form. Or the allowlist names the guidance marketplace. A marketplace entry that cannot be read stops the run, which exits `2`. | block | mechanical | marketplace | script |
| A8 (invocation) | Each realization calls the activation check, if installed, as its first instruction. | The call is missing entirely. | block | mechanical | marketplace | script |
| A8 (invocation) | The call is the first instruction, and it is written as "if installed". | The call is present but not first, or it is not written as "if installed". | warn | mechanical | marketplace | script |
| AD3 | No realization of an ancestor's concept is marked as the default. | A realization of a concept this marketplace does not define carries `default: true` (see Shared rules). | block | mechanical | marketplace | script |
| AD3 | Each `realizes` block names a concept this marketplace defines, or a concept of an ancestor reached through a declared dependency. A plugin that holds only realizations of an ancestor's concept is accepted. | A `realizes` block names a concept that is neither defined here nor reached through a declared dependency. Reachability is reported as X-placement, which names a sibling or downstream target, or a missing one. A `builds_on` target outside the chain is reported as X-resolve. | block | mechanical | marketplace | script |

## Set PIN: guidance pin

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| PIN | The committed `.claude/settings.json` sets `extraKnownMarketplaces.<guidance marketplace name>.source.ref` to `guidance-conventions--v<version>`, where the version is the running script's own plugin version. | The ref names another version. The script halts, names the pinned version and gives the update commands: `claude plugin marketplace update`, then `claude plugin update`. The run exits `2`. | block | mechanical | marketplace | script |
| PIN | A pin is set. | No pin is set. The script warns that results can differ between authors. A marketplace takes up new checks by moving its pin in a pull request. | warn | mechanical | marketplace | script |

## Set SCOPE: where the checks run

SCOPE defines the marketplace-repository test. Every rule that says
"marketplace" means this test.

A repository is a marketplace repository only when both hold:
- `${CLAUDE_PROJECT_DIR}/.claude-plugin/marketplace.json` exists;
- `git rev-parse --show-toplevel`, run in `${CLAUDE_PROJECT_DIR}`, equals
  `${CLAUDE_PROJECT_DIR}`.

A `marketplace.json` in a subdirectory, a submodule, a fixture, or the target
of `git -C <dir>` never qualifies.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| SCOPE | In a repository that is not a marketplace repository, the hook and the activation check do nothing: exit `0`, no output, and no check run. The conformance cases are a repository with no `marketplace.json`, one with a `marketplace.json` only in a subdirectory, and one with a `marketplace.json` only in a submodule. | A non-marketplace repository runs a check, or a `marketplace.json` in a subdirectory, a submodule, a fixture or a `git -C` target qualifies. The script, run on a directory whose marketplace cannot be loaded, exits `2` with a SCOPE message. | block | mechanical | marketplace | script |

## Set M: marketplace conventions

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| M1 | Each plugin entry with a relative-path source resolves to a directory inside the repository. Entries with another source type are skipped, and the report says so. | An entry with a relative-path source resolves to no directory. | block | mechanical | marketplace | script |
| M1 | The marketplace `name` describes the marketplace's own identity. | The name does not describe what the repository is for. | warn | judgement | marketplace | skill |
| M2 | Every plugin name starts with the marketplace's prefix and a hyphen. The prefix is `metadata.pluginPrefix` in `.claude-plugin/marketplace.json`, written without a trailing hyphen (`acme-aws`, not `acme-aws-`). When that key is absent, the prefix is the first hyphen-delimited segment of the marketplace `name`. `guidance-` is reserved for the guidance marketplace. | A plugin name does not start with `<prefix>-`, or uses `guidance-` outside the guidance marketplace. The plugin's concept name is then its full plugin name. A malformed `pluginPrefix` is an F-schema block. Non-blocking. | warn | mechanical | marketplace | script |
| M3 | `README.md` and `LICENSE` exist at the repository root, and the README refers to the `LICENSE` file. | Either file is missing, or the README does not refer to the license. | block | mechanical | marketplace | script |
| M3 | The README describes the marketplace, says how to add it (`/plugin marketplace add`), and states the plugin naming convention. | The README is missing one of those. | warn | judgement | marketplace | skill |
| M4 | The README and docs link to the official docs for the base plugin and marketplace schema, and do not restate them. | The text restates the base schema, for example as a hand-written list of `plugin.json` fields or a layout that mirrors the official reference. | warn | judgement | marketplace | skill |
| M5 | When the license has a public-attribution clause, the README states the attribution requirement in plain language. | The license has the clause, and the README gives only a reference to a LICENSE section number. | warn | judgement | marketplace | skill |

## Set U: upstream declarations

A cross-marketplace dependency is one that names a marketplace other than the
one under validation, in object form or as `name@marketplace`. The rules for
writing dependencies are in [architecture.md §9](../docs/architecture.md). A
dependency on the guidance marketplace is reported by A8, not by U.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| U1 | Every cross-marketplace dependency is in a marketplace entry. | One is in a `plugin.json`. | block | mechanical | marketplace | script |
| U2 | Each cross-marketplace dependency is an object with `name`, `marketplace` and `version`. | A string form, or an object with no `version`. | block | mechanical | marketplace | script |
| U2 | Each `version` is bounded. | A `version` is textually open-ended: `*`, `x`, empty, `latest`, or a bare `>=`. The range is not parsed. Non-blocking. | warn | mechanical | marketplace | script |
| U3 | Every marketplace named by an entry's dependencies, direct dependencies only, is in the root `allowCrossMarketplaceDependenciesOn`. | A named marketplace is missing from the allowlist, or the root has no allowlist. | block | mechanical | marketplace | script |
| U4 | The README has a `## Required marketplaces` section in the template of [architecture.md §9](../docs/architecture.md). It has the template's column order, and a row for each allowlisted marketplace that gives its registration source. The plugin names in each row match the entries. | The section is missing, or a row for an allowlisted marketplace is missing. Nothing verifies the registration source. | block | mechanical | marketplace | script |
| U4 | Each row's range text equals the entry's `version`. | The range text differs from the entry's `version`. Non-blocking. | warn | mechanical | marketplace | script |

## Set AD: additive-only chains

AD1 compares plugin and concept names within the marketplace. AD2 compares them
with every upstream that Set X resolves for the run. An upstream that cannot be
resolved stops the run with exit `2`, under X-resolve. AD3 is in the set above.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| AD1 | Each concept name is defined by one plugin in the marketplace. | Two plugins define the same concept name. | block | mechanical | marketplace | script |
| AD2 | No plugin name, concept name or prefix equals one in an upstream marketplace resolved for this run. | An overlap. The finding names both plugins and the shared name or prefix. | block | mechanical | marketplace | script |

## Set A: concept plugin structure

Set A applies to each concept plugin of a published marketplace. A plugin is a
concept plugin when it has `skills/concept/SKILL.md`. Rows that count
realizations apply only to a plugin with `skills/concept/`.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| A1 | A plugin with `skills/realization-contract/`, or with a `realize-*` skill that has no `realizes` block, also has `skills/concept/SKILL.md`. | Such a plugin has no Tier 1 skill. | block | mechanical | marketplace | script |
| A1 | Tier 1 describes the capability without naming one provider. Its operations are a short list of verb, inputs and outputs. Failure modes are named in the abstract. | Tier 1 reads like documentation for one provider, buries its operations in prose, or names one provider's error codes. | warn | judgement | marketplace | skill |
| A1 | Tier 1's operations form one verb and object group, and its "when to use" reads as one scenario. | The operations split into groups a reader would name differently, or the scenarios are unrelated. A long operation list is a secondary signal. The finding quotes the evidence and suggests sibling concept names. | warn | judgement | marketplace | skill |
| A2 | `skills/realization-contract/SKILL.md` exists when the concept has at least one realization, and defines the operations. | The file is missing. | block | mechanical | marketplace | script |
| A2 | The contract file is a schema and a contract, not working implementation logic. | The file contains implementation logic, which belongs in a realization. | warn | judgement | marketplace | skill |
| A3 | `skills/realization-contract/schema.json` exists and parses as JSON Schema. | The file is missing, or does not parse. | block | mechanical | marketplace | script |
| A3 | The `schema.json` includes a `contractVersion` field. | The field is missing. | warn | mechanical | marketplace | script |
| A3 | The fields are ones every realization needs, not provider-specific ones. | A field looks provider-specific. | warn | judgement | marketplace | skill |
| A3 | The contract's SKILL.md has an example config block that satisfies the base schema. An example config block is a fenced block whose info string is `config`. Its body is a JSON object, or a mapping in the guidance YAML subset, and it satisfies the base schema when it validates against `schema.json`. | The example is missing, or no config block validates. | warn | mechanical | marketplace | script |
| A4 | With no realizations and no contract, the plugin is a concept-only plugin. That is a valid state and produces no finding. | There are no realizations, but a contract exists. The finding asks whether the contract was published early. The warning is expected while a contract is written ahead of its first realization. A2 and A3 still run. | warn | mechanical | marketplace | script |
| A5 | When a concept has at least one realization, exactly one `realize-*` skill is the default (see Shared rules). | Zero or several realizations carry `default: true`. A concept-only plugin is not checked. | block | mechanical | marketplace | script |
| A6 | Each realization's `schema.json` exists, parses as JSON Schema, and keeps every Tier 2 required field required, with the same types and meanings. | The file is missing, or it is not a superset of Tier 2. The superset comparison is skipped when the concept or its Tier 2 schema is absent; A3 and X-placement report those cases. | block | mechanical | marketplace | script |
| A6 | Every property has a `description`. | A property has no `description`. | warn | mechanical | marketplace | script |
| A6 | The realization's SKILL.md body has a line `Default realization: yes` or `Default realization: no`, and it agrees with the `default` key in the front matter. | The line is missing, or it disagrees with the front matter. | warn | mechanical | marketplace | script |
| A6 | Optional fields have a `default` where a sensible one exists. | An optional field with a sensible default has none. | warn | judgement | marketplace | skill |
| A6 | A realization that calls a provider's API directly says why in its SKILL.md, instead of binding to an existing MCP server or command-line tool. | A direct integration gives no reason. | warn | judgement | marketplace | skill |
| A6 (knob) | A realization that talks to an external service has an endpoint property and an API or tool version property (names matching `endpoint`, `base_?url`, `api_?version`, case-insensitive), and its SKILL.md uses them, or says why none applies. | Neither property is present, or the SKILL.md does not use them. The finding names the properties it found that are not used. | warn | judgement | marketplace | skill |
| A7 | A realization directory names the provider or technology it implements. | The name is too vague to tell which provider or technology it is. | warn | judgement | marketplace | skill |
| A7 | The directory name, minus `realize-`, is not one of `default`, `generic`, `basic`, `common`, `standard`, `simple` or `main`, and does not repeat the bare name of its concept. | The name is one of those words, or repeats the concept's bare name. | warn | mechanical | marketplace | script |
| A9 | Realization names are unique within the plugin, and match the name rule in Shared rules. | Two realizations share a name, or a name differs from the rule. | warn | mechanical | marketplace | script |

## Set B: workspace-authored realization

Set B applies to a realization skill kept outside the marketplace under test,
such as a fixture, and to a realization a consuming workspace authors. A skill
is in scope when it has a `realizes` block, or when
`marketplace-plugin-settings.yml` selects it by its `realization:` field.

These rows run in a consuming workspace only. The script and the skills in
this repository do not run them.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| B1 | A selected skill has a valid `realizes` block. | The selected skill's block is missing or malformed. The workspace runtime cannot find it. | block | mechanical | workspace | an implementation of the workspace-side checks |
| B1 | An unselected skill has a valid `realizes` block, or none. | An unselected skill's block is missing or malformed. Non-blocking. | warn | mechanical | workspace | an implementation of the workspace-side checks |
| B2 | The concept plugin's `skills/realization-contract/schema.json` and `SKILL.md` are found, in the marketplace under test or where the concept is installed. | The concept is available, and its contract is not found. | block | mechanical | workspace | an implementation of the workspace-side checks |
| B2 | The concept's contract can be read. | The contract cannot be read, so the run cannot finish, and it exits `2`. The report says what is needed: the concept plugin installed, or its contract files. | block | mechanical | workspace | an implementation of the workspace-side checks |
| B3 | The skill publishes a `schema.json`, and it is a valid superset of the concept's Tier 2 `schema.json`. | The file is missing, or drops a required field, or changes its type or meaning, as A6 compares them. | block | mechanical | workspace | an implementation of the workspace-side checks |
| B3 | Every property has a `description`. | A property has no description. | warn | mechanical | workspace | an implementation of the workspace-side checks |
| B3 | If the skill calls an external service, it has the endpoint and version properties of the A6 knob, and uses them. The first-instruction rule is A8's. | The knob is missing or unused. | warn | judgement | workspace | an implementation of the workspace-side checks |
| B4 | The skill sits at `.claude/skills/realize-<name>/`, directly under `.claude/skills/`, with `SKILL.md` and a sibling `schema.json`. | The skill is in another directory, nested, or named without the `realize-` prefix. The finding names the required path. | block | mechanical | workspace | an implementation of the workspace-side checks |
| B4 | The skill's directory has no `.claude-plugin/plugin.json`. | The directory has one, which makes it a plugin rather than a workspace skill. | warn | mechanical | workspace | an implementation of the workspace-side checks |

## Set C: cross-concept references

One concept refers to another by its concept name only, in backticks. It
never names a realization, and never assumes one is active. The rule is in
[architecture.md §5](../docs/architecture.md).

These rows run in a consuming workspace only. The script and the skills in
this repository do not run them.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| C1 | Not applicable. C1 produces no finding of its own. It collects, from every visible concept, the realization names in bare and qualified form, for C2 and C3. | Not applicable. The severity is `warn` only because every row carries one. | warn | mechanical | workspace | an implementation of the workspace-side checks |
| C2 | The Tier 1 and Tier 3 text of a concept names no realization of another concept, bare or qualified. | A match is listed with its matched text. Whether the match is a coupling is the judgement row below. | warn | mechanical | workspace | an implementation of the workspace-side checks |
| C2 | A match of another concept's realization name is a mention for an unrelated reason, such as a comparison in documentation. | A match couples this concept to a specific realization. Refer to the concept by name instead. The matched text is shown, because the match is a suggestion, not a certainty. | warn | judgement | workspace | an implementation of the workspace-side checks |
| C3 | A concept reference is the bare name in backticks, where the bare name is unique among the concepts visible. Or it is `name@marketplace`, where the bare name is shared, and the qualifier names the marketplace that defines the concept. | An unquoted reference. A qualified reference whose bare name is unique in every readable source. A qualifier that is not the defining marketplace. A bare reference to a shared name. Where a source cannot be read, the run cannot finish, and it exits `2`. | warn | mechanical | workspace | an implementation of the workspace-side checks |
| C4 | The instructions resolve another concept through that concept's own activation check, and do not assume one realization is active. | An instruction assumes a particular realization is always active, for example "since this uses AWS, assume the region is set". | warn | judgement | workspace | an implementation of the workspace-side checks |

## Set D: split signal

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| D | A concept's Tier 1 describes one uniform set of operations. Its Tier 2 has one set of required fields. Its realizations share most of their schema properties. | Tier 1 branches on realization type or provider category. Tier 2 has alternate groups of required fields. Or the realizations share little beyond the required base. The finding says "consider splitting", shows the evidence, and suggests a name for each sibling concept. | warn | judgement | marketplace | skill |

## Set E: realization marketplace

Set E applies to a realization marketplace, which holds realizations and
nothing that defines a concept. The rules are in
[architecture.md §10](../docs/architecture.md). Set E's rows check those rules;
they do not restate them.

| Id | Passes when | Fails when | Severity | Kind | Scope | Implemented by |
|---|---|---|---|---|---|---|
| E1 | Each plugin has at least one `skills/realize-*/` skill, and has neither `skills/concept/` nor `skills/realization-contract/`. | A plugin has a contract, a Tier 1 skill, or no `realize-*` skill. | block | mechanical | marketplace | script |
| E2 | Each `skills/realize-*/SKILL.md` has the `realizes` fenced block, with a `name`. Its `concept` is `<concept>@<marketplace>`, with both parts present. Its `contractVersion` is a semantic-version range with no pre-release suffix. Every skill in the plugin names the same concept. | A skill has no block, or no `name`. The `concept` has no qualifier. `contractVersion` is missing, is not a valid range, or has a pre-release suffix. Skills in one plugin name different concepts. | block | mechanical | marketplace | script |
| E3 | The entry dependency whose marketplace equals the `concept` qualifier exists, and is a plugin whose concept name, its name minus its marketplace's prefix, matches the block's `concept`. The defining marketplace resolves under Set X, and its Tier 2 for the concept is read. | No entry dependency names that marketplace. The derived concept name differs. Or the defining marketplace has no Tier 2 for the concept, which is "no contract to realize". | block | mechanical | marketplace | script |
| E4 | Each pair of concept and realization name occurs once in the marketplace. The realization name is the one defined in Shared rules, the directory name minus `realize-`. | Two skills, in one plugin or two, share a pair. | block | mechanical | marketplace | script |
| E5 | No realization is marked as the default. | A realization carries `default: true`. | block | mechanical | marketplace | script |

Set E is blocking, unlike the sets that report on declarations an existing
marketplace may already have made. It runs only on a realization marketplace.
No marketplace that passes today can start failing because of it.
