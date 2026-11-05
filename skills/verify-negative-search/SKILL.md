---
name: verify-negative-search
description: Use when a search finds nothing or rtk output is filtered.
category: troubleshooting
---

# Verify a negative search before calling it absent

A zero-hit search is not proof of absence while the output is filtered. Before you say a file, class, or symbol does not exist, rerun the search unfiltered and report only what that run showed.

- If the output carries a `(N filtered)` marker or a `[see remaining: tail ...]` line, the hits were hidden. Read the tee log named in the marker, or rerun the command with `rtk proxy <cmd>`.
- Search by stem too, using a case-insensitive pattern such as `-iname "*name*"`, across the root the user named.
- Report the result as "not found after searching `<patterns>` in `<roots>`". Never write "absent" or "does not exist" for a search you have not verified.
- If the file is still missing, ask the user for the path or the project. Do not guess a nearby file.

The marker format this rule catches is in `references/filtered-output-example.md`.
