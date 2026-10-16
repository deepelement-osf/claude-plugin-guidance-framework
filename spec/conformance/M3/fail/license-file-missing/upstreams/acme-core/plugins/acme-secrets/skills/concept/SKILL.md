---
name: secrets
description: Secrets capability. Stores and retrieves a secret by name. Use when a step needs a named secret.
graph:
  graphSpecVersion: "1.0"
---

# Secrets

Secrets stores a value under a name and returns it on request. A caller asks for a secret by name and never sees where it is kept.

## Operations

- Store a value under a name.
- Retrieve the value for a name, or report that the name is unknown.
