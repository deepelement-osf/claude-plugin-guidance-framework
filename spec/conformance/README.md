# Conformance cases

Each case is a directory `<check-id>/{pass,fail}/<case>/` holding `marketplace/`, optional `upstreams/<name>/`, optional `previous/concept-graph.json`, and `expect.json` (`{"exit": n, "checks": [...]}`). The optional `args` key of `expect.json` replaces the default flags of the script run (it must include `--json`), and the optional `warnings` key lists the check ids that must appear as warn findings. The runner applies both, and the cases `PIN/pass/pin-matches`, `PIN/fail/pin-mismatch` and `M2/pass/plugin-outside-prefix` use them.

Every case is one change from a hand-written passing base: an upstream marketplace `acme-core` and a downstream marketplace `acme-web`. Source edits in fail cases are not recompiled, so F-compiled can also fire where it is not the id under test; `expect.json` lists only the id under test.

## Coverage

The table lists each check id that has at least one case, with its case names.
An id that has no row has no case yet. The workspace-side rows (B and C in
[checks.md](../checks.md)) have no case here. Update the table in the same
change that adds or removes a case.

| Id | Pass cases | Fail cases |
|---|---|---|
| A1 | `published-base` | `contract-without-concept` |
| A2 | `published-base` | `realization-without-contract-skill` |
| A3 | `published-base` | `schema-unparseable` |
| A5 | `published-base` | `two-defaults` |
| A6 | `published-base` | `schema-drops-required` |
| A8 | `no-guidance-dependency` | `declares-guidance-dependency`, `invocation-missing` |
| AD1 | `distinct-concept-names` | `concept-defined-twice` |
| AD2 | `distinct-prefix-and-names` | `prefix-equals-upstream-prefix` |
| AD3 | `downstream-realization-not-default` | `downstream-realization-marked-default` |
| E1 | `realization-base` | `plugin-holds-contract` |
| E2 | `realization-base` | `missing-contract-version` |
| E3 | `realization-base` | `no-entry-dependency` |
| E4 | `realization-base` | `duplicate-realization` |
| E5 | `realization-base` | `default-marked` |
| F-agree | `prose-outside-graph-section` | `role-bullet-differs` |
| F-binding | | `realizes-without-name` |
| F-capability | | `role-less-graph-participation` |
| F-compiled | `description-only-change` | `stale-after-source-edit` |
| F-files | `capability-without-realization` | `missing-graph-contract` |
| F-schema | | `unknown-graph-field`, `bad-plugin-prefix`, `plugin-prefix-in-marketplace-metadata`, `guidance-json-unknown-key`, `graph-spec-version-out-of-range` |
| F-selection | | `phase-contract-many` |
| F-tier2 | | `refinement-contract-without-result` |
| F-tier3 | `builds-on-upstream-realization` | `builds-on-missing` |
| M1 | `present-plugin-directory` | `plugin-directory-missing` |
| M3 | `license-and-readme-reference` | `license-file-missing` |
| U1 | `dependency-in-entry` | `dependency-in-plugin-json` |
| U2 | `bounded-object-dependency` | `string-form-dependency` |
| U3 | `marketplace-allowlisted` | `marketplace-not-allowlisted` |
| U4 | `required-section-complete` | `allowlisted-row-missing` |
| V-major | | `phase-removed-without-major` |
| X-additive | | `downstream-copies-upstream-edge` |
| X-hashes | | `upstream-hash-wrong` |
| X-order | | `after-cycle` |
| X-placement | `uses-ancestor-capability` | `refines-sibling-marketplace` |
| X-resolve | `multi-word-prefix` | `refines-missing-concept` |
| X-roles | `observes-refinement-role` | `observes-capability-role` |

- `A8/pass/no-guidance-dependency`: the downstream declares no dependency on the guidance marketplace.
- `A8/fail/declares-guidance-dependency`: the downstream declares a dependency on the guidance marketplace.
- `A8/fail/invocation-missing`: a realization does not call the activation check, if installed, at all.
- `AD1/pass/distinct-concept-names`: every concept name in the marketplace is defined by one plugin.
- `AD1/fail/concept-defined-twice`: two plugins in the marketplace define the same concept name.
- `AD2/pass/distinct-prefix-and-names`: the marketplace's prefix and its plugin and concept names share nothing with the upstream's.
- `AD2/fail/prefix-equals-upstream-prefix`: the marketplace declares, in `.claude-plugin/guidance.json`, the same `pluginPrefix` as an upstream it resolves.
- `AD3/pass/downstream-realization-not-default`: a downstream realization of an upstream phase is not marked default.
- `AD3/fail/downstream-realization-marked-default`: a downstream realization of an upstream phase is marked default.
- `F-agree/pass/prose-outside-graph-section`: prose outside the Graph participation section does not change the graph role.
- `F-agree/fail/role-bullet-differs`: the role in the Graph participation bullets differs from the frontmatter role.
- `F-binding/fail/realizes-without-name`: a realizes block omits the realization name.
- `F-capability/fail/role-less-graph-participation`: a capability's Graph participation section names no role.
- `F-compiled/pass/description-only-change`: a description-only edit leaves the compiled graph valid.
- `F-compiled/fail/stale-after-source-edit`: a source edit to an edge leaves the compiled graph stale.
- `F-files/pass/capability-without-realization`: a capability with no realization directory is valid.
- `F-files/fail/missing-graph-contract`: a graph node has no graph-contract.json.
- `F-schema/fail/unknown-graph-field`: the graph frontmatter has a field the spec does not define.
- `F-schema/fail/bad-plugin-prefix`: the `pluginPrefix` in the marketplace's `.claude-plugin/guidance.json` is malformed, so it is a block.
- `F-schema/fail/plugin-prefix-in-marketplace-metadata`: the marketplace's `.claude-plugin/marketplace.json` still carries `metadata.pluginPrefix`, which is no longer read, so it is a block whose fix moves the value to `.claude-plugin/guidance.json`.
- `F-schema/fail/guidance-json-unknown-key`: the marketplace's `.claude-plugin/guidance.json` has a key that the guidance marketplace schema does not define, so it is a block.
- `F-schema/fail/graph-spec-version-out-of-range`: a file's `graphSpecVersion` is outside the range the script supports, so the run exits `2`.
- `F-selection/fail/phase-contract-many`: a phase contract uses selection "many".
- `F-tier2/fail/refinement-contract-without-result`: a refinement contract has no result shape.
- `F-tier3/pass/builds-on-upstream-realization`: a realization builds on a realization of the same concept in an upstream.
- `F-tier3/fail/builds-on-missing`: a realization's `builds_on` names a realization that does not exist.
- `M1/pass/present-plugin-directory`: each relative-path plugin entry resolves to a directory inside the repository.
- `M1/fail/plugin-directory-missing`: a relative-path plugin entry resolves to no directory.
- `M3/pass/license-and-readme-reference`: `README.md` and `LICENSE` exist at the root, and the README refers to the license.
- `M3/fail/license-file-missing`: the repository root has no `LICENSE` file.
- `U1/pass/dependency-in-entry`: a cross-marketplace dependency is declared in a marketplace entry.
- `U1/fail/dependency-in-plugin-json`: a cross-marketplace dependency is declared in a `plugin.json`.
- `U2/pass/bounded-object-dependency`: each cross-marketplace dependency is an object with a bounded `version`.
- `U2/fail/string-form-dependency`: a cross-marketplace dependency is written in string form.
- `U3/pass/marketplace-allowlisted`: every marketplace a dependency names is in the root allowlist.
- `U3/fail/marketplace-not-allowlisted`: a dependency names a marketplace missing from the root allowlist.
- `U4/pass/required-section-complete`: the README's `## Required marketplaces` section has a row for each allowlisted marketplace.
- `U4/fail/allowlisted-row-missing`: the README's `## Required marketplaces` section has no row for an allowlisted marketplace.
- `V-major/fail/phase-removed-without-major`: a phase present in the previous compiled graph is gone without a major version bump.
- `X-additive/fail/downstream-copies-upstream-edge`: a downstream compiled graph re-declares an upstream node with an edge removed.
- `X-hashes/fail/upstream-hash-wrong`: the recorded upstream graphHash does not match the upstream compiled graph.
- `X-order/fail/after-cycle`: two refinements declare after edges that form a cycle.
- `X-placement/pass/uses-ancestor-capability`: a downstream node uses a capability from an ancestor marketplace.
- `X-placement/fail/refines-sibling-marketplace`: a downstream node refines a node in a marketplace it does not inherit from.
- `X-resolve/pass/multi-word-prefix`: an upstream whose `pluginPrefix` in `.claude-plugin/guidance.json` is multi-word (`acme-core`) resolves, and its plugins are named under that prefix.
- `X-resolve/fail/refines-missing-concept`: a refinement names a concept that does not exist upstream.
- `X-roles/pass/observes-refinement-role`: an observer observes the refinement role.
- `X-roles/fail/observes-capability-role`: an observer observes the capability role, which the spec does not allow.
