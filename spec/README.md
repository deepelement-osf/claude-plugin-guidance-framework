# Concept graph spec

This directory states the concept graph standard in a form a program can
read. The rules are written once, here and in the check catalog. The
compliance script in the `guidance-conventions` plugin implements the
mechanical checks for marketplace repositories. Any implementation of the
workspace-side checks may run the conformance cases described below.

The concept graph standard is experimental. It stays marked experimental
until at least two marketplaces other than the one that defines the root
graph use it, and one release has passed with no MAJOR schema change.

## What is here

- `schemas/` holds one JSON Schema for each file a graph participant
  writes:
  - `concept-declaration.schema.json`: the `graph:` frontmatter of a
    concept skill.
  - `graph-contract.schema.json`: the Tier 2 graph contract file,
    `skills/realization-contract/graph-contract.json`.
  - `realization-declaration.schema.json`: the `graph:` frontmatter of a
    `realize-*` skill.
  - `realizes-block.schema.json`: the `realizes` block of a realization of
    an inherited concept.
  - `compiled-graph.schema.json`: `concept-graph.json` at a marketplace
    repository root.
  - `conformance-expect.schema.json`: the `expect.json` of a conformance
    case.
- `checks.md` is the check catalog. For each check id it states the pass
  and fail conditions, the severity, whether the check is mechanical or a
  judgement call, its scope (`marketplace`, `workspace` or `both`), and
  what implements it (`script` or `skill`).
- `conformance/` holds the conformance cases, one directory per check id.

A schema says what shape a file has. Rules that need more than one file,
the role of a neighboring concept, or a file on disk are not in the
schema. Each schema's `description` says which rules the compliance script
checks instead.

## The graph spec version

- Every graph declaration and every compiled graph carries
  `graphSpecVersion`. The current value is `"1.0"`.
- The field is the graph spec's own version. It is separate from the
  plugin's version and from `contractVersion`.
- The compliance script declares the range of `graphSpecVersion` it
  supports. A workspace runtime declares its own range too.
- A file outside a declared range is refused. The message names the
  upgrade that is needed.

## The JSON Schema subset

The schemas use JSON Schema draft 2020-12, and only these keywords:

- `$schema`, `title`, `description`, `$defs`
- `$ref`, and only to `#/$defs/...` in the same file
- `type`, `properties`, `required`, `additionalProperties`
- `enum`, `const`, `items`, `minItems`, `pattern`
- `oneOf`

Rules that follow from the subset:

- A schema has no `$id`, no remote `$ref`, and no `allOf`, `anyOf`, `not`,
  `if`, `then` or `else`. A role-dependent rule is a `oneOf` with one
  branch per role.
- Every object sets `additionalProperties` to `false`. These are the
  exceptions, and each one is named in its schema's `description`:
  - `when` in a concept declaration and in a compiled graph. Its keys are
    call parameters, which are open, so its `additionalProperties` is a
    string schema.
  - `plugins` in an upstream of a compiled graph. Its keys are plugin
    names, so its `additionalProperties` is a version schema.
  - `frame`, `input` and `result` in a graph contract. These hold JSON
    Schema documents written by the concept's author. They are typed only
    as objects, and the script checks them against this subset.
- Patterns use only regular-expression syntax that means the same in
  Python and in ECMA-262.
- `description` is prose. Nothing reads it as a rule.

## The YAML subset

A concept declaration and a realization declaration are YAML frontmatter.
A `realizes` block is a fenced YAML block. The compliance script reads
them with the standard library only, and it reads this subset:

- block-style maps and block lists;
- flow lists of scalars, such as `[a, b]`;
- flow maps of scalars, such as `{role: phase}`;
- plain or double-quoted scalars.

Anchors and aliases, tags, multi-line strings (`|` and `>`), and flow
collections nested inside other flow collections are outside the subset.
Compiled graphs are JSON, so the subset does not apply to them.

## Conformance cases

A conformance case tests one check id. Each case is a directory:

```
spec/conformance/<check-id>/pass/<case-name>/
spec/conformance/<check-id>/fail/<case-name>/
```

A case contains:

- `marketplace/`: a complete marketplace directory, with
  `.claude-plugin/marketplace.json` and, if it has graph concepts, its
  `concept-graph.json`.
- `upstreams/<name>/`: optional. Each is a marketplace directory with its
  own `concept-graph.json`.
- `previous/concept-graph.json`: optional. The compiled graph at the
  previous release tags. Version checks use it.
- `expect.json`: the expected result, `{"exit": 0|1|2, "checks": ["<id>", ...]}`,
  which must validate against `schemas/conformance-expect.schema.json`.

The expectation is:

- For a `fail` case, the exit code is as stated, and each listed check id
  appears as a blocking finding.
- For a `pass` case, no blocking finding carries the case's own check id.

Run a case from the repository root:

```
python3 plugins/guidance-conventions/scripts/guidance_check.py <case>/marketplace --upstreams <case>/upstreams --previous <case>/previous --no-official --no-pin --json
```

Leave out `--upstreams` or `--previous` when that directory is absent.
`--no-official` skips the official structure check, which needs the Claude
Code command-line tool. `--no-pin` skips the pin check, which needs a
committed pin. A case has neither, so it turns both off.

Guidance's continuous integration runs the script on every case and
compares the result with `expect.json`.

Cases are domain-free. Every name in a case is synthetic, such as
`acme-core`, `acme-web` and `build@acme-core`.

## Workspace-side implementations

- Any implementation of the workspace-side checks may run the cases whose
  scope in `checks.md` is `workspace` or `both`.
- Such an implementation must agree with the compliance script on those
  cases.
- Checks that apply only to marketplaces have no workspace counterpart.
  These are the graph semver checks, the check that the guidance
  marketplace is not a dependency, the pin check, and the checks of
  recorded upstream versions. Their scope in `checks.md` is `marketplace`.
- The script writes `concept-graph.json` only under `--compile`. It never
  edits any other file.
