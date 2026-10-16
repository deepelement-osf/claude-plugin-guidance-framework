---
name: realize-markdown
description: Markdown audit realization. Appends each concluded phase to a markdown log in the run's repository.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Markdown audit realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Appends one line per concluded phase to a markdown log, then returns recorded: true. If the line cannot be written, it returns recorded: false.
