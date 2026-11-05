---
name: long-work-ledger
description: Use when a long migration may reset context; keep a ledger.
category: general
---

# Keep a ledger for long multi-wave work

Write every decision, baseline, and commit hash to one ledger file in the session scratch folder as it happens. After a context reset, read the ledger before the next action. Its lines outrank any summary.

- One line per decision: date, who decided, the choice, and the evidence. Quote the user's own word, such as "yes" or "option 1".
- Take each baseline the moment you have it: dead-reference counts, permission lists, plist keys, compile results. Store the raw output as a file and cite its path. Later checks diff against that file, not against a recalled number.
- Record each commit with its hash, subject, and file count. Keep each commit message draft in the ledger folder and pass it with `-F`.
- Re-read the baseline file before any check you re-run after a reset.
- Keep tokens and keys out of the ledger. Name the file that holds them instead.
