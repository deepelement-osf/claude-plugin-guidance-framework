---
name: realize-next-build
description: Next.js build realization. Runs the project's own build tooling for the nextjs-build refinement.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Next.js build realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Runs the project's build tooling in the run's repository and returns the notes the build produced.
