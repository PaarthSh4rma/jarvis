---
name: project-summary
description: Produce a concise grounded summary of a project's current local state.
scope: project
version: 1
---

# Project Summary

Use the approved project-status capability to summarise current, observable project state.

Procedure:

1. Resolve exactly one project through the backend project registry.
2. Retrieve its authoritative current status using the approved read-only tool.
3. Summarise the project name, branch, working-tree state, recent commit metadata, and detected technologies.
4. Keep the answer concise and distinguish unavailable values from negative findings.
5. Do not modify files, launch applications, write memory, or invent activity not present in the observation.
