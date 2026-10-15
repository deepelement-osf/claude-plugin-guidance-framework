---
name: realize-next-cli
description: Next.js command-line build realization. Runs the project's own build tooling for the nextjs-build refinement.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Next.js command-line build realization

Default realization: yes

```realizes
concept: nextjs-build@acme-web
contractVersion: "^1.0.0"
```

Runs the project's build tooling in the run's repository and returns the notes the build produced.
