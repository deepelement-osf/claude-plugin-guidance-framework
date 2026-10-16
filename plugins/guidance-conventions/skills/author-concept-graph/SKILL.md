---
name: author-concept-graph
description: Author a concept's place in a plugin marketplace's concept graph. Use when adding a phase, entry, refinement, observer or capability to a published marketplace, when changing a concept's graph fields or its realizations, or when the compliance check reports a graph finding (an F, X or V check id). It runs the steps in order - read the upstream compiled graphs, choose the role, write the declaration and its participation section, write the graph contract, declare realizations, recompile, then check. Only for a plugin marketplace repository.
---

# Author a concept in the concept graph

This skill is the authoring path for a concept's graph role. It says which
document to read at each step and what to check before moving on. It does not
restate the rules.

- [architecture.md section 12](../../../../docs/architecture.md#12-concept-graphs)
  defines the graph: roles, the frame, support and conclude steps, entries and
  hand-offs, observers, run facts, capability refinements, lifecycle and
  compiled graphs.
- [spec/checks.md](../../../../spec/checks.md) gives every check id, what it
  passes and fails on, its severity, and whether the script or a skill runs it.

Do the steps in order. Each step ends before the next one starts.

## 1. Read the upstream graphs

- Find the `concept-graph.json` of each direct upstream marketplace. The upstream
  chain checks (set X in [spec/checks.md](../../../../spec/checks.md)) say where
  each upstream is read from.
- Read the `nodes` and `capabilities` of each upstream. Note the ids this
  concept will use, extend, refine, observe or hand off to.
- Note each upstream's version and `graphHash`. Never edit an upstream.

## 2. Choose the role

- Pick one role from architecture section 12. A concept with no role is a
  capability: other concepts use it by name, and it never runs on its own.
- A capability has no `## Graph participation` section.
- If the new node would sit between two upstream phases, stop and reconsider.
  The standard has no role for that.

## 3. Write the declaration

- In the concept's `skills/concept/SKILL.md`, add one top-level `graph:` key to
  the YAML frontmatter.
- Use block-style YAML only, as in the templates below. Use no anchors and no
  multi-line strings.
- Set `graphSpecVersion` first. Use only the field names and values that
  architecture section 12 and the schemas in `spec/` define.
- Every reference is qualified: `<concept>@<marketplace>`. Use `workspace` only
  for a consuming workspace's own concepts.

## 4. Write the participation section

- In the same file, add `## Graph participation` after the frontmatter.
- Write one bullet for each declared field except `graphSpecVersion`, in the
  order the frontmatter declares them. Use the form `- **<field>:** <value>`.
- The bullets must match the frontmatter. The check F-agree blocks any
  difference.

### README template: a phase concept

````markdown
---
name: build
description: What the build phase delivers, and when to use it.
graph:
  graphSpecVersion: "1.0"
  role: phase
  edges:
    - outcome: passed
      to: deliver@acme-core
    - outcome: failed
      to: plan@acme-core
---

# Build

What the phase delivers, in the abstract. Name no realization.

## Graph participation

- **role:** phase
- **edges:** passed → deliver@acme-core, failed → plan@acme-core
````

### README template: a refinement concept

````markdown
---
name: nextjs-lint
description: Lint obligations for a Next.js build. Use when a build refinement needs them.
graph:
  graphSpecVersion: "1.0"
  role: refinement
  refines: build@acme-core
  after: [format@acme-web]
  optional: true
  when: {path_exists: package.json}
---

# Next.js lint

What the refinement adds to its parent. It adds obligations and returns its
declared result. It never changes the parent.

## Graph participation

- **role:** refinement
- **refines:** build@acme-core
- **after:** format@acme-web
- **optional:** true
- **when:** path_exists=package.json
````

## 5. Write the graph contract

- Create `skills/realization-contract/graph-contract.json`, beside
  `schema.json`.
- Every concept with a role needs one. A capability may stay concept-only.
- Its keys, and which of them each role requires, are in architecture section 12
  and the contract schema under `spec/`.
- Do not put `contractVersion` in this file. It stays only in `schema.json`.

## 6. Declare realizations

- Each Tier 3 realization is `skills/realize-<name>/SKILL.md`. Its `graph:` key
  holds `graphSpecVersion`, `runs`, and `command` when `runs` is `command`.
  Add `builds_on` and `effects` when they apply.
- A command realization's `command` path is relative to its own skill directory.

  ```yaml
  graph:
    graphSpecVersion: "1.0"
    runs: command
    command: scripts/check.sh
    effects: [push]
  ```

- A realization that targets a concept of another marketplace carries a
  `realizes` block. The block has a required `name` line, which matches the
  directory name without `realize-`:

  ````markdown
  ```realizes
  concept: build@acme-core
  name: next-build-monorepo
  contractVersion: "^1.1.0"
  ```
  ````

- Only the defining marketplace marks a default, with `default: true` in the
  frontmatter of the `realize-*` SKILL.md. The rule is in
  [spec/checks.md](../../../../spec/checks.md#shared-rules).
  [architecture.md section 10](../../../../docs/architecture.md#10-realization-marketplaces)
  says which realization kinds may be shipped, and where.

## 7. Recompile

Run this from the repository root:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance_check.py" --compile .
```

- It writes `concept-graph.json` at the root, and nothing else.
- Never edit `concept-graph.json` by hand. A stale file is a finding, and the
  fix is to recompile.

## 8. Run the check

Run this from the repository root:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance_check.py" .
```

- Exit `0`: passed, possibly with warnings. Read the warnings.
- Exit `1`: blocking findings. Fix each one, recompile if the file changed, and
  run the check again.
- Exit `2`: the check could not run. Read the message. A pin mismatch (PIN) is
  fixed by moving the guidance pin first. The update commands are in
  [spec/checks.md](../../../../spec/checks.md#set-pin-guidance-pin).
- Look up any check id you do not recognise in
  [spec/checks.md](../../../../spec/checks.md). Do not guess at its meaning.
- When the script passes, run `validate-concept-plugin` for the judgement
  checks, and `validate-marketplace` for the marketplace as a whole.
