---
name: realize-git-push
description: Git push deliver realization. Pushes the deliverable branch to its remote.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: command
  command: scripts/deliver.sh
  effects: [push]
---

# Git push deliver realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

The command in this skill's scripts directory performs the push. Its exit status decides the outcome: 0 is passed, anything else is failed.
