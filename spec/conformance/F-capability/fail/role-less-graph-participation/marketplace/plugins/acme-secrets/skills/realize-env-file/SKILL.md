---
name: realize-env-file
description: Environment-file secrets realization. Reads named secrets from environment variables that the run's environment file defines.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Environment-file secrets realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Looks up a secret name as an environment variable, with the configured prefix. Reports the value, or that the name is unknown.
