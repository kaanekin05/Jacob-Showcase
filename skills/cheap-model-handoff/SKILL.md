---
name: cheap-model-handoff
description: >-
  Pick the cheapest Claude model that can do a job. Opus keeps the judgment,
  Sonnet writes code whose decisions are already made, and Haiku does
  mechanical edits. Use when choosing which model implements a plan task, when
  writing the per-task model label into a plan, when dispatching a writer
  subagent and setting its `model`, when asking whether a cheaper subagent can
  write already-outlined code, or when a mechanical edit such as a rename, a
  file move or a reference update spans 3 or more files. Not for a one-off edit
  under 3 files outside a plan, or a design question. Opus does those inline.
  Non-Claude workers such
  as Codex are `orchestration`. The task loop itself is
  `superpowers:subagent-driven-development`. Splitting Unity work by file
  ownership is `unity-parallel-subagents`.
category: general
---

# Hand the typing to a cheaper model, keep the judgment on Opus

Opus plans, brainstorms, debugs, and accepts or rejects everything that comes back. Sonnet and Haiku do the typing. A job never runs on a cheaper model the user did not see named.

## The tier line

| Tier | Gets the job when | Examples |
|---|---|---|
| `haiku` | Nothing to decide. The exact before and after is known. Success is checkable by search or compile | Renames, file moves, reference updates after a rename, one-line edits Opus wrote out |
| `sonnet` | Decisions are made, but the code is not written. The plan names classes, methods, and behavior | A MonoBehaviour from an outlined spec, a test from a listed case, one pattern applied across files |
| `opus` | The brief would have to say "use your judgment" | Design, debugging with an unknown cause, cross-system changes, §architecture layering, a §frameworks footgun not already pinned |

The test: if Opus cannot write the brief without leaving a decision open, the job stays on Opus.

## Labels in a plan

- Put one `**Model:** <haiku|sonnet|opus>` line under each task heading. Follow it with a one-line reason.
- An unlabeled task runs on `opus`. Never guess a cheaper tier for it.
- A plan with any `haiku` or `sonnet` label recommends subagent-driven execution.
- When handing a labeled plan over for approval, state the label count, for example "3 haiku, 4 sonnet, 2 opus".
- Labels have no effect under Native execution, also called inline execution or `superpowers:executing-plans`, because the main session does every task itself.

## Dispatching

- Every writer dispatch passes `model` from the task's label.
- A batched dispatch of several tasks runs on the highest label among them.
- A writer dispatch with no explicit `model` is forbidden. Without it, the agent's `opus` frontmatter wins and the handoff silently does nothing.
- Jacob agents keep their `opus` frontmatter. The per-dispatch `model` parameter outranks it.
- Every writer returns a diff. Opus reads it before accepting it. One writer per file. These rules come from `rules/Jacob_Engineering.md` §engineering/dispatch.

## Confirmation

- Labels are approved with the plan, in the one confirmation already given. The run does not stop for them.
- During a run, Opus asks only to change a label. Moving a task up or down both count.
- Outside a plan, a job touching 3 or more files gets a one-line ask that names the model and the job. Example: "Rename `EnemySpawner` across 12 files on Haiku?"
- Outside a plan, under 3 files, Opus works inline with no ask. Plan tasks of any size follow their label.
- A "no" keeps the job on Opus inline. There is no second ask for that job.

## Briefs per tier

- **Haiku briefs** list the exact before and after for every change. They also name the check that proves it, such as a `grep` that must return zero hits or a compile.
- **A Unity script rename** moves the `.cs` file and its `.meta` file together with `git mv`. The class name must equal the file name. `.meta` files do not count toward the 3-file floor.
- **Sonnet briefs** carry the plan's decided names, signatures, and behavior. Nothing in them is left for the writer to choose.

## Failure handling

- Fix rounds 1–3 stay on the same tier with no ask. Reviewer findings go back to the same implementer.
- A small slip, such as a missed reference or a typo, is fixed by Opus inline. No dispatch and no ask.
- Fix round 4 triggers a one-tier move up, after the user confirms. Haiku moves to Sonnet, and Sonnet moves to Opus.
- `opus` is the top writer tier. An `opus` task at fix round 4 gets a fresh `opus` implementer with no ask, because that is not a tier change. Moving to `fable` is a tier change and asks first.
- BLOCKED because the task needs more reasoning also triggers a confirmed one-tier move up.
- A "no" to either move-up ask stops the task. Opus asks the user what to do next. There is no same-model retry without changes.
- A task moved up at round 4 stays on its new tier for round 5, with no second ask.
- BLOCKED for missing context is re-dispatched on the same tier with that context. No ask.
- These two asks override Superpowers' automatic escalation. A failure therefore stops an unattended run until the user answers.

## Miss log

Append one line to `skills/cheap-model-handoff/misses.md` for every confirmed move up a tier, in this format:

`YYYY-MM-DD | job kind | failed tier | one-line why`

A reviewer finding fixed within rounds 1–3 is not a miss. A move down, or a label change during planning, is not a miss. The log is append-only, and it is the data for tuning the tier line.

## Reviewers

- Spec and code-quality reviewers take the model Superpowers' Model Selection gives them, never below `sonnet`. Scoped re-reviews included.
- Code-quality review on Unity code stays with `unity-reviewer`.
- The final whole-branch review runs on `opus`.
- "Opus reviews" means the main session reads each reviewer verdict and accepts or rejects the task. It is not a second full review.
