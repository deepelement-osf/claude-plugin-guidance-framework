# claude-plugin-guidance

Claude's default plugin guidance tells you the mechanics, not how to
design a plugin that extends well — the guidance marketplace offers the
concept/realization pattern so a plugin realizes cleanly into real-world
variation.

## Why this exists

Anthropic's plugin/marketplace standard defines the mechanics — manifest
schema, directory layout, component types — but says nothing about how
to structure a marketplace repo well as you build it: what naming to
use, what docs are expected, how to shape a plugin whose capability has
more than one possible implementation. Without that guidance, every
marketplace author either reinvents these conventions from scratch or
drifts into inconsistency one plugin at a time, and a mistake surfaces
only as a confusing failure later, far from the change that caused
it.

The guidance marketplace is that missing authoring toolkit. Install its
plugins into your marketplace repo and they'll guide you toward good
structure as you write it, and give you a clear, specific notice when
something's off — instead of leaving you to remember the rules yourself.
It is **not** a general-purpose plugin collection. Two roles use it, for
different reasons:

- **Published and realization marketplace authors** install its
  authoring tooling into the marketplace repo they are building (a
  `.claude-plugin/marketplace.json` plus a `plugins/` directory),
  authored so its checks run *as you write*, not after.
- **A consuming workspace** registers it so the activation check can run
  before a realization does real work. That is a runtime dependency of
  using concept plugins, not authoring; the
  [architecture](./docs/architecture.md#6-activation-check-a-shared-convention-not-a-hook)
  says what the check does and does not do.

## Four roles

The docs name four roles, each by what it does. A repo plays a role
relative to what it publishes or uses, so one repo can play more than
one.

| Role | What it is |
|---|---|
| **guidance marketplace** | This repo (`claude-plugin-guidance`): authoring tooling for marketplace authors, and the marketplace a consuming workspace registers so the activation check can run. It ships no concept plugins. |
| **published marketplace** | A marketplace authored with the guidance marketplace that publishes concept plugins. |
| **[realization marketplace](./docs/architecture.md#10-realization-marketplaces)** | A marketplace that offers realizations for concepts owned by an existing published marketplace. |
| **consuming workspace** | The workspace that registers and uses marketplaces, the guidance marketplace among them, and selects and configures realizations in `marketplace-plugin-settings.yml`. |

"Tier 1/2/3" names the three parts inside one concept plugin and is
never used for these roles.

## The two plugins, together

Neither plugin here is more foundational than the other. A marketplace
author installs both; a consuming workspace needs
**guidance-activation-check**. **guidance-conventions** enforces the
structure your marketplace repo should have; **guidance-activation-check**
is the runtime helper any plugin built with that structure can call on to
fail predictably instead of confusingly.

- **[guidance-conventions](./plugins/guidance-conventions)** — checks
  your marketplace repo's naming, required docs, and structure as you
  author it, including a deeper check for any plugin that adopts the
  [concept/realization pattern](./docs/architecture.md) described below.
  This is where the marketplace-authoring rules live.

- **[guidance-activation-check](./plugins/guidance-activation-check)** —
  a shared pre-flight check your plugins can call before doing real
  work. It validates `marketplace-plugin-settings.yml` against the
  active realization's published config schema, so a missing or outdated
  configuration produces one clear, actionable message instead of a
  confusing failure deep in unrelated logic.

## Install

**Marketplace authors** (published or realization marketplace): run these
from inside your marketplace project:

```
/plugin marketplace add DeepElement/claude-plugin-guidance-framework
/plugin install guidance-conventions@claude-plugin-guidance
/plugin install guidance-activation-check@claude-plugin-guidance
```

**Consuming workspaces**: register the guidance marketplace and install
the activation check, from inside the workspace:

```
/plugin marketplace add DeepElement/claude-plugin-guidance-framework
/plugin install guidance-activation-check@claude-plugin-guidance
```

Registration is by the marketplace's own `name`, `claude-plugin-guidance`.
Registering and installing select no realization. To have a teammate who
clones the workspace get the guidance marketplace too, install at project
scope as
[what the consuming workspace must do](./docs/architecture.md#what-the-consuming-workspace-must-do)
describes. The architecture also covers
[register, enable, select](./docs/architecture.md#register-enable-select)
and [where a workspace-authored realization lives](./docs/architecture.md#where-a-workspace-authored-realization-lives).
A workspace can also override an installed realization with its own, which
the activation check reports, or extend one, which it guards against an
update that breaks the extension
([extending an installed realization](./docs/architecture.md#extending-an-installed-realization)).
A workspace that authors realizations of its own can add
`guidance-conventions` to validate them.

## The concept/realization pattern

If a plugin you're building represents a capability with more than one
possible implementation (e.g. secrets, notifications — something with
swappable providers), the guidance marketplace recommends a specific
pattern for it: an abstract concept, a contract concrete providers must
satisfy, one or more provider realizations, and a single settings file
where a consuming workspace selects and configures a provider.

Read **[How the guidance marketplace works](./docs/architecture.md)**
for the full explanation and the detailed spec — this README stays
intentionally short.

If your published marketplace builds on another published marketplace's
concepts, [§9 of that document](./docs/architecture.md#9-chains-of-published-marketplaces)
covers how to declare the dependency and what a consuming workspace must
register. To offer realizations for a concept that another published
marketplace defines, see
[§10](./docs/architecture.md#10-realization-marketplaces), which also
says what a consuming workspace registers to use one.

## The base standard

This repo doesn't redefine the Claude Code plugin/marketplace standard
itself (directory layout, manifest schema, component types) — that's
owned by Anthropic and documented at:

- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Create plugins](https://code.claude.com/docs/en/plugins)
- [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the PR workflow and the
conventions your plugin needs to follow.

## License

Apache 2.0, with an added requirement: any public use of this project
("claude-plugin-guidance") or a derivative must visibly credit
"DeepElement" and link back to its source repository,
[DeepElement/claude-plugin-guidance-framework](https://github.com/DeepElement/claude-plugin-guidance-framework).
See [LICENSE](./LICENSE) for the exact terms.

## Acknowledgments

This project's use of Claude and other pay-for-use models was supported
by a donation from [joelunger.com](https://joelunger.com).
