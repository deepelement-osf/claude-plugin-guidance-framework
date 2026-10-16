---
name: realization-contract
description: Realization contract for the build phase. Not invoked directly; realizations of build load it.
---

# Build realization contract

A realization of build must:

- produce one deliverable per run and report its outcome, passed or failed;
- accept the frame that refinements of build receive;
- keep its own settings in the schema.json beside this file.

The shape of the frame and the selection rule are in graph-contract.json.
