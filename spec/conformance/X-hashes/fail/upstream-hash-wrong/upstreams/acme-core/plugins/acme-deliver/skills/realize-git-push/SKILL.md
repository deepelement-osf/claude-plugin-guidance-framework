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

Default realization: yes

The command in this skill's scripts directory performs the push. Its exit status decides the outcome: 0 is passed, anything else is failed.
