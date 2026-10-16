---
name: realize-markdown
description: Markdown build realization. Writes the deliverable as a markdown file in the run's repository.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Markdown build realization

Default realization: yes

Writes the deliverable as one markdown file under the configured output directory, then reports passed. If the file cannot be written, it reports failed.
