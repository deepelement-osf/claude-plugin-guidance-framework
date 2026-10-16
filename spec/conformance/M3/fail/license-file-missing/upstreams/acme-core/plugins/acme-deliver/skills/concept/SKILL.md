---
name: deliver
description: Deliver phase. Publishes a deliverable and ends the run. Use when a workflow reaches its deliver step.
graph:
  graphSpecVersion: "1.0"
  role: phase
---

# Deliver

Deliver publishes the deliverable of a run. It is the last step of the core chain, so it declares no outgoing edge.

## Operations

- Publish the deliverable named by the run.
- Report the outcome: passed or failed.

## Graph participation

- **role:** phase
