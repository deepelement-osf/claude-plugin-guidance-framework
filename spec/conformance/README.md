# Conformance cases

Each case is a directory `<check-id>/{pass,fail}/<case>/` holding `marketplace/`, optional `upstreams/<name>/`, optional `previous/concept-graph.json`, and `expect.json` (`{"exit": n, "checks": [...]}`).

Every case is one change from a hand-written passing base: an upstream marketplace `acme-core` and a downstream marketplace `acme-web`. Source edits in fail cases are not recompiled, so F-compiled can also fire where it is not the id under test; `expect.json` lists only the id under test.

- `A8/pass/no-guidance-dependency`: the downstream declares no dependency on the guidance marketplace.
- `A8/fail/declares-guidance-dependency`: the downstream declares a dependency on the guidance marketplace.
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
- `F-selection/fail/phase-contract-many`: a phase contract uses selection "many" without a fold.
- `F-tier2/fail/refinement-contract-without-result`: a refinement contract has no result shape.
- `V-major/fail/phase-removed-without-major`: a phase present in the previous compiled graph is gone without a major version bump.
- `X-additive/fail/downstream-copies-upstream-edge`: a downstream compiled graph re-declares an upstream node with an edge removed.
- `X-hashes/fail/upstream-hash-wrong`: the recorded upstream graphHash does not match the upstream compiled graph.
- `X-order/fail/after-cycle`: two refinements declare after edges that form a cycle.
- `X-placement/pass/uses-ancestor-capability`: a downstream node uses a capability from an ancestor marketplace.
- `X-placement/fail/refines-sibling-marketplace`: a downstream node refines a node in a marketplace it does not inherit from.
- `X-resolve/fail/refines-missing-concept`: a refinement names a concept that does not exist upstream.
- `X-roles/pass/observes-refinement-role`: an observer observes the refinement role.
- `X-roles/fail/observes-capability-role`: an observer observes the capability role, which the spec does not allow.
