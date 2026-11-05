# Response-quality evals — the "sample-prompt parity" half of §18

`../trigger-cases.jsonl` + `../overlap-audit.py` answer **which artifact fires**. This directory
answers the other question `rules/Jacob_Engineering.md` §18 demands and Jacob previously had
no substrate for: **did the response actually get better?**

Baseline vs candidate on identical prompts, blind-judged against a weighted rubric, with a release gate.

Adapted from [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) (MIT) @ `16a42a01`, pinned in
`check-updates.sh` `WATCHED_REPOS` as `i-have-adhd`.

## Contents

| File | What it is | Honesty boundary |
|---|---|---|
| `run_evals.py` | `validate` / `plan` / `run` / `score`. Upstream verbatim except the 3 adaptations listed in its docstring. | Runs and aggregates. It does **not** judge — see below. |
| `cases.jsonl` | 18 Jacob-shaped cases: §8 hot paths, §9 MVC leaks, §10 footguns, §7 naming, §19 scope/budget, §13 pushback + reduction ladder + Divergent Ideation, §18 agent-engineering, safety, and 3 negative controls. | Authored ground truth. `criteria` is guidance for the judge, not an assertion the harness checks. |
| `rubric.md` | 5 weighted dimensions + the release gate. Upstream verbatim. | Correctness 35% / autonomy 25% / actionability 20% / safety 10% / concision 10%. |
| `runners.json` | Claude + Codex runner configs. Model pinned to `claude-opus-5`. | Replaces upstream's `runners.example.json`. |

**Upstream's own 14 cases were dropped, not vendored** — they test ADHD-output-style compliance. Kept,
they would have measured the wrong thing.

## The one thing you must not change

Both runners isolate the call from your own config: `--setting-sources ""` for Claude,
`--ignore-user-config --ephemeral` for Codex. **This is load-bearing.** Without it, your global
`~/.claude/CLAUDE.md` — i.e. the Jacob ruleset — leaks into the **baseline** condition, and the eval
measures the ruleset against itself and reports no difference. The model pin matters for the same
reason: unpinned, the eval silently runs whatever the CLI defaults to, and per-token cost moves with it.

## Run it

```bash
python3 scripts/evals/response-quality/run_evals.py validate
python3 scripts/evals/response-quality/run_evals.py plan --trials 3

# baseline: no instructions injected
python3 scripts/evals/response-quality/run_evals.py run \
  --runner claude --condition baseline --trials 3 --budget-usd 10 \
  --output scripts/evals/response-quality/results/responses.jsonl

# candidate: inject the ruleset (or a single changed SKILL.md)
python3 scripts/evals/response-quality/run_evals.py run \
  --runner claude --condition candidate --condition-skill AGENTS.md \
  --trials 3 --budget-usd 10 \
  --output scripts/evals/response-quality/results/responses.jsonl
```

Runs are resumable — rerun the same command and completed `(case, trial, condition, runner)` rows are
skipped. `--budget-usd` is capped at 25 and the remaining budget is passed to every Claude call.

For a **single-artifact** change, point `--condition-skill` at that `SKILL.md` and cut `cases.jsonl`
down with `--case <id>` — a full 3-trial sweep of all 18 cases across 2 conditions is 108 model calls.

> **The 4 §18 cases added 2026-08-26 have no baseline.** `skill-vs-agent-reduction`,
> `description-craft`, `spine-clobber-safety`, and `jacob-capability-not-a-skill` post-date every run
> recorded so far, so the release gate's "within 0.1 of baseline" clause cannot be evaluated for them
> until **both** conditions are run fresh. Do not compare them against an older baseline sweep.

## Judging (manual — price this in before you start)

The harness does not judge. Blind the `condition` field, score each response by hand or with a separate
judge call, one JSON object per line:

```json
{"case_id":"mvc-leak","trial":1,"condition":"candidate","correctness":5,"autonomy":5,"actionability":4,"safety":5,"concision":4,"blocker":false,"notes":"Refused the MonoBehaviour placement, named §9."}
```

```bash
python3 scripts/evals/response-quality/run_evals.py score scripts/evals/response-quality/results/scores.jsonl
```

`score` refuses to compare conditions judged on different rows — that check is why the gate means
something. Record the CLI and model versions with any published number.

## When to run this

Run it on a changed skill/agent, and it is the honest answer whenever a ruleset
edit claims to improve behavior. It is **not** a per-commit gate: it costs real dollars and real
judging time. `results/` is gitignored-by-convention — do not commit response bodies.
