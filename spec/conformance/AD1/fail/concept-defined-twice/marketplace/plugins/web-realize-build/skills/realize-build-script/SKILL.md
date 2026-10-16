---
name: realize-build-script
description: Script realization of the build phase. Runs the workspace build script.
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Script build realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: no

```realizes
concept: build@acme-core
name: build-script
contractVersion: "^1.0.0"
```

Runs the workspace build script and reports passed or failed.
