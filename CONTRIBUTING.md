# Contributing

Thanks for considering a contribution to `claude-plugin-guidance`. This
repo is the guidance marketplace — an authoring toolkit for marketplace
authors building their own Claude Code plugin marketplaces. See the
[README](./README.md) for what it is, and
[docs/architecture.md](./docs/architecture.md) for the four role names
used here and the concept/realization pattern the tooling implements.

## Before you start

- For anything beyond a small fix (typo, broken link, small doc
  clarification), please open an issue first to discuss the change.
  This is especially true for anything touching the architecture in
  `docs/architecture.md` — it's a deliberate design, and changes to it
  affect every plugin built against it.
- This repo does not redefine the official Claude Code plugin/marketplace
  standard (directory layout, manifest schema, component types). If your
  change would restate or duplicate that standard rather than linking to
  it, it will need to be reworked before merge — see "No restated
  standard" below.

## Pull request workflow

All changes land through a pull request into `main` — direct pushes
aren't accepted (branch protection requires at least one approving
review). To contribute:

1. Fork the repo and create a branch for your change.
2. Make your change.
3. Run the relevant validation skill (see below) and fix anything it
   flags.
4. Open a PR describing what changed and why.
5. A guidance maintainer reviews and merges.

Keep PRs focused — one plugin, one doc change, or one fix per PR, rather
than bundling unrelated changes together.

## Conventions for the guidance marketplace

Every plugin here follows a small set of conventions, checked by the
`guidance-conventions` plugin's `validate-marketplace` skill:

- Plugin names are prefixed `guidance-<name>`, matching the guidance
  marketplace's own name.
- Every plugin has a `.claude-plugin/plugin.json` per the
  [official plugin reference](https://code.claude.com/docs/en/plugins-reference).
- The repo root keeps `README.md` and `LICENSE` up to date and
  cross-referenced.
- Nothing here restates the official plugin/marketplace standard — link
  to the [official docs](https://code.claude.com/docs/en/plugins-reference)
  instead of describing schema or directory layout that Anthropic
  maintains and can change independently of this repo.

If you have `guidance-conventions` installed, ask Claude to run
`validate-marketplace` against your change before opening a PR.

## Naming the roles

Use the role names defined in
[docs/architecture.md](./docs/architecture.md#the-four-roles): guidance
marketplace, published marketplace, realization marketplace, and
consuming workspace. "Tier" is reserved for Tier 1/2/3 inside one concept
plugin; never use "tier", "level" or "layer" for a role or for a
relationship between roles.

## What belongs here

The guidance marketplace ships authoring tooling for marketplace authors,
not concept plugins — see [the four roles](./docs/architecture.md#the-four-roles).
The tooling runs only in marketplace repositories, and a consuming workspace
never registers it.
A contribution is usually one of:

- A new `guidance-<name>` tooling plugin, or a new skill in an existing
  one (`guidance-conventions`, `guidance-activation-check`).
- A change to how an existing skill checks or guides authors, including
  `validate-concept-plugin` and the activation check, which implement the
  concept/realization pattern. Keep them consistent with
  [docs/architecture.md](./docs/architecture.md); a change that alters the
  pattern itself is an architecture change (open an issue first).
- A docs change.

If you're authoring concept plugins for your own published marketplace
rather than changing this repo, start from the architecture doc: it
covers how a concept plugin is structured (§1), concept-only plugins
(§4), referencing another concept (§5), per-tier best practices (§7),
the one-contract split rule (§8), building on another published
marketplace (§9) and offering realizations for another marketplace's
concepts (§10). Those plugins live in your marketplace,
not in a pull request here.

## Adding a plugin

1. Create `plugins/guidance-<name>/.claude-plugin/plugin.json` following
   the [official plugin reference](https://code.claude.com/docs/en/plugins-reference).
2. Add an entry to `.claude-plugin/marketplace.json`'s `plugins` array
   pointing at `./plugins/guidance-<name>`.
3. Run `validate-marketplace` (from `guidance-conventions`) to check it
   against the conventions above.

## Plugin versions and releases

Other marketplaces resolve a plugin's version range against release tags,
so each plugin here is versioned and tagged on its own. The mechanism
(tag format, how ranges resolve) is documented in
[Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies);
this section covers only what this repo does with it.

### Version policy

- Set `version` in the plugin's `.claude-plugin/plugin.json` only. Do not
  also set it on the entry in `.claude-plugin/marketplace.json`.
- Every pull request that changes anything inside a plugin's directory
  (behaviour, skill prose or the manifest) bumps that plugin's `version`.
  A change only outside `plugins/` (README, docs, CONTRIBUTING, CI) does
  not. Wording-only changes made before a plugin's first tag need no bump.
- Pick the bump by what a dependent can observe:
  - **MAJOR** — a change a dependent can fail on: a check that newly
    halts, a skill renamed or removed, or a change to a skill's arguments.
  - **MINOR** — additive: a new skill, check or option that leaves
    existing use working.
  - **PATCH** — fixes, and prose or manifest edits inside a plugin.

### Releasing

Tags are per plugin, named `<plugin>--v<version>` (for example
`guidance-activation-check--v1.0.0`). A tag of any other shape is not a
plugin release tag, and this policy ignores it.

After the pull request merges, the guidance maintainer tags the merge commit
from a clean working tree:

```sh
git checkout main && git pull
claude plugin tag plugins/guidance-<name> --push
```

`claude plugin tag` derives the tag from `plugin.json`; see the
[CLI reference](https://code.claude.com/docs/en/plugins/cli-reference#plugin-tag)
for its options. The plugins are relative-path sources, so their tags live
in this repo.

### Release schedule

- `guidance-conventions` and `guidance-activation-check` are first tagged
  `0.1.0`, by the guidance maintainer, on the merge commit of the pull
  request adding this section. The `0.1.0` tag holds exactly the plugin
  contents at that commit; any later change to either plugin bumps its
  `version` under the policy above and is not part of `0.1.0`.
- `guidance-activation-check` is tagged `1.0.0` when the guidance
  maintainers decide it is ready. Nothing depends on that tag: no plugin
  declares a guidance plugin as a dependency, and a realization calls the
  check only if it is installed (see [the architecture](./docs/architecture.md#6-activation-check-a-shared-convention-not-a-hook)).
- `guidance-conventions` is authoring-time tooling and is not a documented
  dependency target.

## Reporting bugs and requesting features

Open a GitHub issue. Include:

- What you expected vs. what happened (for a bug), or what you're trying
  to accomplish (for a feature request).
- Which plugin/skill is involved, if applicable.

## Security issues

Please do not open a public issue for a security concern. See
[SECURITY.md](./SECURITY.md) for how to report one privately.

## Licensing of contributions

This repository is licensed under Apache 2.0 with an added public
attribution requirement — see [LICENSE](./LICENSE). By submitting a
pull request, you agree that your contribution is licensed under the
same terms.
