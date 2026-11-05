# Jacob — Model Register

**What this is.** A reference register of the models available to Claude Code, the only CLI Jacob
runs on since 2026-10-01. It does **not** route requests.

**Claude Code model selection is manual and user-owned** (changed 2026-07-25). Nothing in this repo
writes the tier env vars — `scripts/bootstrap.sh` does not merge them and `--uninstall` does not strip
them. Set them by hand in `~/.claude/settings.json` `env`. Left unset, which is the normal state, Claude
Code uses its own auth and the `/model` picker. `scripts/doctor.sh` does not inspect any of this.
See `rules/Jacob_Engineering.md` §engineering/model-register.

This is the single place that records what models exist, what their canonical IDs are, and what
aliases frontmatter uses.

---

## Model rosters

### Claude Code — Anthropic (alias map)

Agent frontmatter uses the **short alias** where one exists so it stays portable and auto-resolves to
whatever the plan provides. Fable has no verified short alias, so Fable-assigned agents carry the
full `claude-fable-5`.

| Alias (frontmatter) | Canonical ID | One-line role |
|---|---|---|
| `opus` | `claude-opus-5-5` | Deepest reasoning — architecture, multi-system design, perf/concurrency audit, high-stakes review, and every code-writing agent. Thinking is always on; `effort` defaults to `medium`, one level below Opus 5. `claude-opus-5` and `claude-opus-4-8` remain valid IDs. |
| `sonnet` | `claude-sonnet-5-5` | Balanced default — structured output, docs, high-volume vault work (`wiki-ingest`), most day-to-day work. `claude-sonnet-5` remains a valid ID. Not the implementer default. |
| `haiku` | `claude-haiku-4-5-20251001` | Fast + cheap — routine edits, search, high-volume low-ambiguity file sweeps. |
| *(no verified alias)* | `claude-fable-5-1` | Creative / narrative / design ideation. Use the **full ID** in frontmatter — no short alias is verified. `claude-fable-5` remains a valid ID. |

Roster verified 2026-09-29 against the Claude API reference skill that Claude Code ships built in. Jacob vendored a byte-identical copy of it until 2026-10-01, then deleted the copy.


### Code-writing agents run on Opus (2026-09-28)

The nine `category: implementer` agents that write code were moved from `sonnet` to `opus`:
`gameplay-programmer`, `unity-specialist`, `unity-ui-specialist`, `unity-addressables-specialist`,
`unity-dots-specialist`, `unity-shader-specialist`, `tools-programmer`, `technical-artist`, `qa-tester`.

**Why.** Ruleset §invocation now lets these agents auto-dispatch. Before that they fired only when the user
asked, so the main thread wrote the code and Sonnet was a deliberate cost saving on rare delegation.
Auto-dispatch inverts that. The subagent becomes the default author of Unity C# held to §code, and
the model writing that code should not be weaker than the one reviewing it.

`wiki-ingest` stays on `sonnet`. It is an implementer by category but it files vault pages, not code,
and it runs in high-volume parallel batches where Sonnet is the right trade.

---

## Per-agent `model:` and `category:` frontmatter

Each editable top-level `agents/*.md` carries two frontmatter keys:

- **`category:`** — documentation of intent (what kind of work this agent is designed for).
  Not used for routing.

- **`model:`** — the **Claude Code tier selector**; it picks the tier directly.
  `scripts/doctor.sh` Check 7 validates the value is a real Claude alias/ID to catch typos.

---

## Maintenance

- **New model version ships** → update the roster block above by hand. `/check-updates` deliberately
  does **not** sweep model rosters.
- **Provenance:** Jacob-native, authored-in-place. (The INTEGRATIONS.md ledger that used to record
  this was deleted 2026-07-21; provenance now lives in `skills/skills.lock.json` and the vault archive.)
