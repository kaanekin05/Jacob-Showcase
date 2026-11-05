# Jacob evals — the substrate behind "'better' requires an eval" (§agent-engineering)

§agent-engineering says a skill/agent change isn't "better" until a behavior check says so. This directory is the
Jacob-native substrate for that check: **a corpus, a static auditor, and two model-in-the-loop runners.**

## Contents

| File | What it is | Honesty boundary |
|---|---|---|
| `trigger-cases.jsonl` | Corpus of `{prompt, expect, note}` cases: which skill/agent *should* fire per prompt, incl. negative controls. | Ground truth is authored by a human; it says what *should* happen, not what *does*. `expect` must be the frontmatter `name:`, not the directory — they differ for 5 skills (doctor Check 12 lists them). |
| `overlap-audit.py` | Static description-space auditor — flags skill/agent **description pairs that compete** for the same prompts (TF-IDF cosine over descriptions + `Triggers:` phrases). | Measures *description competition only*. It does **not** predict firing — a low-overlap pair can still mis-route, and a flagged pair may be fine by design. |
| `build-roster.py` | Parses every `skills/*/SKILL.md` + `agents/*.md` frontmatter into the `name: description` roster the trigger eval routes against. | Plugin skills have nothing on disk here, so their descriptions are **mirrored by hand** in the file — an incomplete mirror is fine, a stale one is not. |
| `run-trigger-eval.sh` | Model-in-the-loop trigger eval: one `claude -p` call per case, scored against `expect`. | Measures **whether the description routes**, not whether the skill then works — no skill body is read and no tool is called. Exits 2 and refuses to print a pass rate if a run aborts part-way. |
| `run-gate-eval.sh` | Model-in-the-loop gate eval: one tool-using `claude -p` session per case in `gate-cases.jsonl`, scored on whether it **read** the gated reference file (`Read`/`Grep`/`Glob` names the basename). | Measures **that the file was opened**, not that the answer obeyed it or that the read came before the code. A session that stops before writing code scores `INCONCLUSIVE`, not FAIL. Exits 2 and refuses to print a pass rate if a run aborts part-way. |
| `run-create-bar-eval.py` | Model-in-the-loop eval for the autoharness create-bar hook: the judge from `scripts/hooks/create_bar.py` rules on 20 create intents built from real learned skills Kaan labelled keep or too small, plus synthetic one-liners. `TRIALS=3 python3 -I scripts/evals/run-create-bar-eval.py`. | Measures **the judge's verdict on a create**, not what autoharness does after a deny. A miss means the rubric is wrong, never the label; label disagreements are Kaan's to settle. |
| `answer-shape.py` | Deterministic counter for jacob-plain's five countable shape rules (prose words, bold spans, volunteered lines, line-1 verdict, blocking-question placement), plus `--against` to report numbers and scope words a compression dropped. No model call, no judge. | **Counts form, not intent.** Volunteered material is seen only under an `Also noticed:` heading, so loose off-scope paragraphs score zero. Exceeding a ceiling can be correct — jacob-plain names five reasons — so it FLAGs, never gates. `rules/output-styles/jacob-plain.md` defines every number; this only mirrors them. |
| `response-quality/` | Baseline-vs-candidate A/B harness for response quality (adapted from ayghri/i-have-adhd, MIT). | Judging is manual and costs real dollars per run; isolation via `--setting-sources ""` is load-bearing — without it the operator's own ruleset leaks into the baseline. |

## `trigger-cases.jsonl` format

One JSON object per line:

```json
{"prompt": "<what the user would type>", "expect": "<skill-or-agent name, or 'none'>", "note": "<why>"}
```

Add a `should-fire` and at least one `should-not-fire` (negative control) case whenever you author or
sharpen a skill/agent (the `rules/Jacob_Engineering.md` §engineering/authoring checklist reminds you). Negative controls are what catch over-firing.

## Running the real trigger eval (model in the loop)

Deciding *which* skill a prompt actually triggers requires a model in the loop — a shell script cannot
compute it. `run-trigger-eval.sh` is that harness, built in-process rather than by reinventing an eval
engine (§agent-engineering):

```
./scripts/evals/run-trigger-eval.sh                 # all cases, one model call each
./scripts/evals/run-trigger-eval.sh find-skills     # only cases whose expect/note mentions find-skills
TRIALS=3 ./scripts/evals/run-trigger-eval.sh find-skills  # 3 trials/case, majority-scored
MODEL=claude-sonnet-5 ./scripts/evals/run-trigger-eval.sh
```

It hands the model the live roster (every skill + agent on the spine with its description) and asks
which single one it would route to, then scores that against `expect`. **Costs one model call per case
per trial and draws on your own session quota** — filter to the skill you changed rather than sweeping
all 23 out of habit. Exits 2 without printing a pass rate if the CLI stops answering mid-run.

**Routing is not deterministic.** Cases have flipped between back-to-back runs with no intervening
change. One failure is not a finding: re-run it with `TRIALS=3` before touching a description. 3/3 is
signal; 1/3 is noise, and rewriting a description to chase noise is exactly the "vibes, not evals" trap
§agent-engineering warns about. When trials disagree the row shows the split.

**Most early failures were the harness, not the skills.** Confirm the case's `expect` is right and the
harness is asking a fair question *before* rewording anything. Every one of these produced a
false failure and none was a description problem:

| Symptom | Actual cause |
|---|---|
| A skill looked like it never fired | Its `description:` was a folded `>-` block that a shell one-liner truncated to the literal string `>-`. Now parsed by `build-roster.py`, and guarded by doctor Check 12. |
| Agent-shaped cases scored `none` | The roster listed agents but the prompt said "route to at most one **skill**". Agents are now labelled `(agent)` and named as valid answers. |
| Two cases failed on a correct answer | They asserted the frontmatter `name:` where the harness routes by **directory** name. Five skills diverge; doctor Check 12 lists them. |
| A rate-limit message scored as a routing miss | The runner treated CLI output as an answer. It now aborts instead of manufacturing a pass rate. |

> **Dead reference removed 2026-08-26:** this section used to point at `eval-viewer/generate_review.py`.
> That script belongs to Anthropic's `skill-creator` plugin, which is **not installed** here (it exists
> only as an uninstalled marketplace clone under `~/.claude/plugins/marketplaces/`). Jacob has no
> viewer; `run-trigger-eval.sh` replaced the manual scoring it left behind (2026-08-27).

## Running the gate eval

§context says a **READ FIRST** row must be read before you write code in that area. This eval checks
whether a real session does that. Each case in `gate-cases.jsonl` names a `cwd`, a `prompt` and the
`gates` (file basenames) that must be read. One case is a negative control with a `watch` list that must
**not** be read.

```
./scripts/evals/run-gate-eval.sh                    # all cases, one session each
./scripts/evals/run-gate-eval.sh unitask            # only cases whose id contains "unitask"
MODEL=haiku ./scripts/evals/run-gate-eval.sh control-awake   # cheap dry run
```

Output is a markdown report on stdout. The raw stream per case is saved to `$OUT_DIR/<id>.jsonl`
(`OUT_DIR` defaults to a fresh `mktemp -d` and is printed at the top). `MODEL` defaults to `sonnet`.

The script disallows Write, Edit, MultiEdit, NotebookEdit, Bash, Agent, Task, WebFetch, WebSearch and
Workflow, and MCP is empty. `bypassPermissions` is there because a permission prompt in `-p` mode would
silently deny the read of a gate file and fake a FAIL. **Costs one full tool-using session per case** and
draws on your own session quota.

Verdicts: `PASS` when every gate was read (control: no watched file was read). `FAIL` when a gate was
never read. `INCONCLUSIVE` when the case expects code, no gate was read and the answer has no fenced code
block, because the session never reached the decision under test. Re-run an `INCONCLUSIVE` case, and re-run
a `FAIL` before changing a rule on its strength. Sessions are not deterministic, same as the trigger eval.

## Running the overlap auditor (static, no model, no network)

```
python3 scripts/evals/overlap-audit.py            # default threshold 0.35
python3 scripts/evals/overlap-audit.py 0.25       # lower = more (noisier) pairs
```

Report-only, exits 0. Wired into `/check-updates` as a routing-collision section. Use it after adding a
skill/agent to catch the collision *before* it degrades routing — exactly the `forge`↔
`find-skills` overlap (forge was deleted 2026-10-04) that motivated §agent-engineering's authoring-vs-discovery boundary.
