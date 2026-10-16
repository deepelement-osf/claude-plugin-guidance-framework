---
name: nextjs-build
description: Next.js build refinement. Adds what building means for a Next.js project to the build phase. Use when the build phase runs in a Next.js project.
graph:
  graphSpecVersion: "1.0"
  role: refinement
  refines: build@acme-core
---

# Next.js build refinement

This refinement adds obligations for Next.js projects to the build phase. It never changes the build phase's outcome or its edges. It returns the notes the build phase needs.

## Graph participation

- **role:** refinement
- **refines:** build@acme-core
