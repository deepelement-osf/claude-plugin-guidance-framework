---
name: realize-vault-kv
description: Environment-file secrets realization. Reads named secrets.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# realize-vault-kv

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Looks up a secret name and reports the value, or that the name is unknown.
