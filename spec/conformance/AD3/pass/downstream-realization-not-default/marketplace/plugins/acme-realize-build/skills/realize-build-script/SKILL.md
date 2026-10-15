---
name: realize-build-script
description: Script realization of the build phase. Runs the workspace build script.
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Script build realization

Default realization: no

```realizes
concept: build@acme-core
name: build-script
contractVersion: "^1.0.0"
```

Runs the workspace build script and reports passed or failed.
