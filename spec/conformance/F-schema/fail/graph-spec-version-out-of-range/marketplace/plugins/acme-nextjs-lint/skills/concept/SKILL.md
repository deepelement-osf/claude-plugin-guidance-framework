---
name: nextjs-lint
description: Next.js lint refinement. Adds a lint pass to the build phase after the Next.js build refinement. Use when the build phase runs in a Next.js project.
graph:
  graphSpecVersion: "2.0"
  role: refinement
  refines: build@acme-core
  after: [nextjs-build@acme-web]
---

# Next.js lint refinement

This refinement runs a lint pass over the build output after the Next.js build refinement. It adds findings to the build phase and never changes its outcome.

## Graph participation

- **role:** refinement
- **refines:** build@acme-core
- **after:** nextjs-build@acme-web
