---
name: realize-git-push
description: Git push deliver realization. Pushes the deliverable branch to its remote.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Git push deliver realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Pushes the deliverable branch to its remote. Its outcome is passed when the push succeeds and failed otherwise.
