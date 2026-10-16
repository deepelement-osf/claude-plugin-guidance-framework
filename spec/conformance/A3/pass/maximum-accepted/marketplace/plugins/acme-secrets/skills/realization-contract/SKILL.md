---
name: realization-contract
description: Realization contract for the secrets capability. Not invoked directly; realizations of secrets load it.
---

# Secrets realization contract

A realization of secrets must store and retrieve values by name. It must not return a value for a name it does not hold.

## Example config

```config
{"scope": "acme-vault", "limit": 3}
```
