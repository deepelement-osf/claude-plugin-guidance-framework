---
name: realization-contract
description: Realization contract for the Next.js lint refinement. Not invoked directly; realizations of nextjs-lint load it.
---

# Next.js lint refinement contract

A realization of nextjs-lint must return the findings described in graph-contract.json. It adds findings and never changes the outcome of the build phase it refines.
