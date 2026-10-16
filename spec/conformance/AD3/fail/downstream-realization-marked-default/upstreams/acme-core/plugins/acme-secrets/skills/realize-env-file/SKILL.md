---
name: realize-env-file
description: Environment-file secrets realization. Reads named secrets from environment variables that the run's environment file defines.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Environment-file secrets realization

Default realization: yes

Looks up a secret name as an environment variable, with the configured prefix. Reports the value, or that the name is unknown.
