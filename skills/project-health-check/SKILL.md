---
name: project-health-check
description: Assess a project's current development health without modifying it.
scope: project
version: 1
---

# Project Health Check

Use the approved project-status capability to inspect current project and Git state.

Procedure:

1. Resolve exactly one project through the backend project registry.
2. Retrieve its authoritative current status using the approved read-only tool.
3. Assess the reported branch, working-tree state, latest commit, and detected technologies.
4. State missing information plainly and do not infer facts from unrelated fields.
5. Do not modify files, launch applications, write memory, or claim unsupported checks occurred.
