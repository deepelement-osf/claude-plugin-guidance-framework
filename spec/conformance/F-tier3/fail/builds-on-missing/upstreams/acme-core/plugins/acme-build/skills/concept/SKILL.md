---
name: build
description: Build phase. Turns a goal into a deliverable. Use when a workflow reaches its build step.
graph:
  graphSpecVersion: "1.0"
  role: phase
  edges:
    - outcome: passed
      to: deliver@acme-core
    - outcome: failed
      to: deliver@acme-core
  uses: [secrets@acme-core]
---

# Build

Build turns the goal of a run into a deliverable. It names the operation the phase performs, not how a realization performs it.

## Operations

- Read the goal and any context the run supplies.
- Produce the deliverable and record what it contains.
- Report the outcome: passed or failed.

## Graph participation

- **role:** phase
- **edges:** passed → deliver@acme-core, failed → deliver@acme-core
- **uses:** secrets@acme-core
