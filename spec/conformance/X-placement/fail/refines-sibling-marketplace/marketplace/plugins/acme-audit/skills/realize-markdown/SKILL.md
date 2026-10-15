---
name: realize-markdown
description: Markdown audit realization. Appends each concluded phase to a markdown log in the run's repository.
default: true
graph:
  graphSpecVersion: "1.0"
  runs: agent
---

# Markdown audit realization

Default realization: yes

Appends one line per concluded phase to a markdown log, then returns recorded: true. If the line cannot be written, it returns recorded: false.
