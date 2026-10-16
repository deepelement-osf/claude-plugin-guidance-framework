# acme-web

Synthetic downstream marketplace used by the conformance cases.

## Required marketplaces

Register these in your consuming workspace before installing plugins from this
marketplace. Settings are not transitive; nothing registers them for you. Register
each marketplace under exactly its name below.

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-core` | `acme/acme-core` (GitHub) | `acme-core-build` `^1.0.0` | The web refinement refines the build phase |

## License

It is licensed under the terms in the LICENSE file.
