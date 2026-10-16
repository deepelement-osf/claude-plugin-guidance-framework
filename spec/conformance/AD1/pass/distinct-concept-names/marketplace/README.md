# acme-web

Synthetic downstream marketplace used by the conformance cases. It is licensed under the terms in the LICENSE file.

It refines the `build` phase of acme-core, adds a lint refinement and an observer.

## Required marketplaces

Register these in your consuming workspace before installing plugins from this
marketplace. Settings are not transitive; nothing registers them for you. Register
each marketplace under exactly its name below.

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-core` | `acme/acme-core` (GitHub) | `acme-build` `^1.0.0`, `acme-deliver` `^1.0.0` | The web refinements refine the build phase, and the observer watches the core phases |
