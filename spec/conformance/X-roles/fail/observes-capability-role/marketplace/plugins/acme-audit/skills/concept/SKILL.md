---
name: audit
description: Audit observer. Records that a phase concluded. Use when a run should keep a record of each phase outcome.
graph:
  graphSpecVersion: "1.0"
  role: observer
  observes: {role: capability}
  on: concluded
---

# Audit observer

The audit observer runs after a phase concludes and records that it did. It cannot change the phase's outcome, its deliverable or its edges.

## Graph participation

- **role:** observer
- **observes:** role: capability
- **on:** concluded
