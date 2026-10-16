# acme-web

Synthetic downstream marketplace used by the conformance cases.

It holds one realization of the `build` phase of acme-core.

## Required marketplaces

Register these in your consuming workspace before installing plugins from this
marketplace. Settings are not transitive; nothing registers them for you. Register
each marketplace under exactly its name below.

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-core` | `acme/acme-core` (GitHub) | `acme-build` `^1.0.0` | The realization builds on the build phase |

## License

It is licensed under the terms in the LICENSE file.
