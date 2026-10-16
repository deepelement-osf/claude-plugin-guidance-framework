---
name: realize-lint-script
description: Lint script realization for the Next.js lint refinement. Runs the project's lint script as a command.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: command
  command: scripts/lint.sh
---

# Lint script realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

The command in this skill's scripts directory runs the lint pass. Exit status 0 is passed, anything else is failed.
