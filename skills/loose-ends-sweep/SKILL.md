---
name: loose-ends-sweep
description: Use when asked for loose ends, or /session-finalizer.
category: general
---

# Loose-ends sweep across sessions

A sweep reports open items. It fixes nothing. Verify each candidate against live state before you list it.

- Skip autoharness reflector runs. They carry no user work and close nothing. Count them in one line, and do not mine them for items.
- Read the substantive sessions in full, in windows, before you list anything. A session digest is an index, not evidence.
- Check each candidate against live state first: `git status -sb`, `git rev-list --count origin/BRANCH..BRANCH`, `git stash list`, the mtime of any build artifact against the commit that built it, and any saved build run record. "Not done yet" in a session may have been finished later.
- Put items that later work closed under one `Closed since:` line. Do not list them as open.
- For each open item give three things: where it came from (session id and time), the open question, and one next action. Order the items by dependency. A parent decision comes before the choices under it.
- Transcript timestamps are UTC. State the offset once, at the top.
- Quote the user's exact words only for decisions still waiting on them.
- If a secret reached the chat during the window, list it under the secret-handling rules, not as a loose end.
- When a step is held on a user decision, write the hold into the project memory note when the hold starts. The note names the held step, the decision it waits on, the recommended option, and what runs after it. A session that ends early then still carries the hold.
