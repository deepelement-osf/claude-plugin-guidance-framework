---
name: realization-contract
description: Realization contract for the Next.js build refinement. Not invoked directly; realizations of nextjs-build load it.
---

# Next.js build refinement contract

A realization of nextjs-build must return the notes described in graph-contract.json. It adds obligations and never changes the outcome of the build phase it refines.
