# acme-build-realizations

Synthetic realization marketplace for the E cases.

## Required marketplaces

Register these in your consuming workspace before installing plugins from this
marketplace. Settings are not transitive; nothing registers them for you. Register
each marketplace under exactly its name below.

| Marketplace name | Registration source | Plugins used (range) | Why |
|---|---|---|---|
| `acme-core` | `acme/acme-core` (GitHub) | `acme-build` `^1.0.0` | Defines `build`; the realizations here target it |
