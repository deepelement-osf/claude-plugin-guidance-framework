---
name: realize-markdown
description: Markdown build realization. Writes the deliverable as a markdown file in the run's repository.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Markdown build realization

Call `guidance-activation-check:check-realization-config`, if installed, before any other step. Pass it the concept, this realization's name and `${CLAUDE_SKILL_DIR}`. If it is not installed, run this realization's own short inline check against its `schema.json`.

Default realization: yes

Writes the deliverable as one markdown file under the configured output directory, then reports passed. If the file cannot be written, it reports failed.
