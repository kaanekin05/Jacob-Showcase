---
name: design-review
description: "Reviews a game design document for completeness, internal consistency, implementability, and adherence to project design standards. Run this before handing a design document to programmers. Used by the `systems-designer` agent."
argument-hint: "[path-to-design-doc] [--depth full|lean|solo]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, AskUserQuestion
model: sonnet
---

## Insufficient input

**If the inputs this skill needs do not exist, the answer is "could not run".**
Never a filled-in report. Run this check first and stop if it fails.

1. List the inputs this skill reads: the design document under review, and the project design standards it is
   measured against.
2. Record each one `FOUND` or `ABSENT`. Never "assumed present".
3. An ABSENT input makes its section **`NOT ASSESSED — NO DATA`**. Do not
   estimate it. Do not infer it from an adjacent artifact. Do not leave the cell
   for whoever reads the template next.
4. If every required input is ABSENT, stop. Report **`NOT ASSESSED — NO DATA`**
   as the whole verdict. Name what was missing, and what produces it.

**A `NOT ASSESSED` verdict is a success.** It is the right answer to "what does
the data say" when there is no data.

**Absence of evidence is never evidence of absence.** A scan that found no
matches because there were no files to scan has verified nothing. Say which of
the two happened. A reader cannot tell the difference from a green result.

## Jacob Ruleset Compliance

When reviewing design documents for Unity implementation, verify:

- **MVC compatibility (§architecture)**: Design must map cleanly to Model (data/state), Controller (logic/events), View (Unity rendering). Reject designs requiring game logic in View components.
- **Performance feasibility (§performance)**: Flag designs requiring per-frame iteration over large collections, frequent instantiation/destruction, or string-heavy operations in hot paths.
- **Data-driven design (§architecture)**: All tunable values must be external (ScriptableObject or config), not hardcoded.
- **Input system (§architecture)**: Input-driven mechanics must assume New Input System (`UnityEngine.InputSystem`).
- **Async patterns (§frameworks)**: Async operations must use UniTask with CancellationToken.

---

## Phase 0: Parse Arguments

Extract `--depth [full|lean|solo]` if present. Default is `full` when no flag is given.

- **`full`**: Complete review — all phases + specialist agent delegation (Phase 3b)
- **`lean`**: All phases, no specialist agents — faster, single-session analysis
- **`solo`**: Phases 1-4 only, no delegation, no review-log write, no Phase 5 next-step prompt — use when called from within another skill

---

## Phase 1: Load Documents

Read the target design document in full. Read `AGENTS.md` for project context and standards. Read related design documents in `design/gdd/` for referenced or implied systems.

**Dependency graph validation:** For every system listed in the Dependencies section, check whether its GDD file exists in `design/gdd/`. Flag missing references — these are broken references that downstream authors will hit.

**Prior-review check.** Look for the review log at `<dir-of-the-reviewed-doc>/reviews/<doc-basename>-review-log.md`. If it exists, read the most recent entry and carry two things forward: the verdict it gave, and the blocking items it listed.

This session is then a **re-review**. Its job is not only to produce a fresh verdict. It is to say what happened to each prior blocking item, one of four things:

- **Fixed** — the GDD now addresses it. Quote the line that closes it.
- **Still open** — unchanged, or changed without addressing the finding.
- **Superseded** — the design moved and the item no longer applies. Say what replaced it.
- **Dropped without explanation** — gone from the GDD with nothing in its place.

The last one is the reason this check exists. A blocking item that quietly disappears between reviews is an untracked deferral, which §behavior/analysis says to name rather than let pass. Never fold a prior item into the new findings list without stating which of the four it was.

If no log exists, record "first review" and continue.

---

## Phase 2: Completeness Check

Evaluate against the Design Document Standard (from `game-designer` agent):

- [ ] Overview section (one-paragraph summary)
- [ ] Player Fantasy section (intended feeling, MDA aesthetics)
- [ ] Detailed Rules section (unambiguous mechanics)
- [ ] Formulas section (all math defined with variables)
- [ ] Edge Cases section (unusual situations handled)
- [ ] Dependencies section (other systems listed)
- [ ] Tuning Knobs section (configurable values identified)
- [ ] Acceptance Criteria section (testable success conditions)

A section that is present can still fail if it is an empty heading. Spot-read every section the verdict turns on.

---

## Phase 3: Consistency and Implementability

**Internal consistency:**
- Do the formulas produce values that match the described behavior?
- Do edge cases contradict the main rules?
- Are dependencies bidirectional?

**Implementability (Unity-specific):**
- Are the rules precise enough for a Unity programmer to implement without guessing?
- Are there any "hand-wave" sections where details are missing?
- Are performance implications considered?
- Does the design respect MVC boundaries (§architecture)?
- Are all tunable values designed as external data?

**Cross-system consistency:**
- Does this conflict with any existing mechanic?
- Does this create unintended interactions with other systems?
- Is this consistent with the game's established tone and design pillars, where documented?

---

## Phase 3b: Adversarial Specialist Review (full mode only)

**Skip this phase in `lean` or `solo` mode.** In `full` mode (the default), this phase is **mandatory** — do not skip it.

Before spawning any agents, print this notice:
> "Full review: spawning specialist agents in parallel. This typically takes several minutes. Use `--depth lean` for a faster single-session review."

**Step 1 — Identify every domain the GDD touches** (a GDD often touches several — be thorough), then spawn the matching Jacob agents:

| If the GDD contains… | Spawn |
|---|---|
| Economy, costs, drops, rewards, progression, retention | `live-ops-designer`, `systems-designer` |
| Combat stats, damage, health, DPS, formulas | `game-designer`, `systems-designer` |
| AI behaviour, pathfinding, targeting | `gameplay-programmer` |
| Level layout, spawning, wave/encounter structure | `level-designer` |
| UI, HUD, menus, player-facing displays | `ux-designer`, `unity-ui-specialist` |
| Animation, feel, timing, juice | `gameplay-programmer`, `technical-artist` |
| Rendering, shaders, VFX, post-processing | `unity-shader-specialist`, `technical-artist` |
| Asset loading, memory budget, streaming | `unity-addressables-specialist` |
| Performance, draw calls, GC, hot paths (§performance) | `unity-performance`, `performance-analyst` |
| Engine-specific patterns/APIs, MVC structure | `unity-specialist` |
| Acceptance criteria, test coverage | `qa-tester` |
| **Any formulas / system interactions** | `systems-designer` (always — active) |
| **Any gameplay system** | `game-designer` (always — active) |

> **Archive-aware (2026-07-12, amended 2026-10-01):** the design/production specialists `live-ops-designer`, `ux-designer`, `creative-director`, `art-director`, `accessibility-specialist` and `producer` **do not exist** — archived 2026-07-12, deleted 2026-10-01 (names and sources in the vault's *archived-roster* page). Spawn only **active** agents. If a GDD touches one of those domains, flag it as **not independently reviewed** and say which domain; do not stall waiting for an agent that is gone. `game-designer` and `level-designer` are active (restored 2026-09-14); `systems-designer` was never archived.

**Step 2 — Spawn all relevant specialists in parallel.**

**CRITICAL: `Agent` in this skill spawns a SUBAGENT — a separate independent session with its own context window. It is NOT task tracking. Do NOT simulate specialist perspectives internally. Do NOT reason through domain views yourself. You MUST issue actual `Agent` calls, issued simultaneously — do not spawn one at a time. A simulated review is not a specialist review.**

Prompt each adversarially, with the **GDD only** — do NOT pass your Phase 2/3 findings (§behavior/self-refine). A specialist handed the main review's conclusions checks *those* instead of the design, and its agreement then tells you nothing. Independence is what makes Step 4 worth reading.
> "Here is the GDD for [system]. Your job is NOT to validate it — find problems. From your domain, what is wrong, underspecified, likely to break, or missing? Be specific and critical."

Per-agent focus:
- **`game-designer`** — anchor to the GDD's Player Fantasy section; does the design deliver that feeling, or do rules serve implementability while undermining it?
- **`systems-designer`** — plug boundary values (min/max) into every formula; report any degenerate output (negative, div-by-zero, infinity, nonsense at extremes).
- **`unity-performance`** — flag any mechanic that implies per-frame allocation, large-collection iteration, or frequent Instantiate/Destroy in hot paths (§performance).
- **`qa-tester`** — flag every acceptance criterion that isn't independently testable ("feels balanced", "works well" are not ACs); suggest concrete rewrites.

**Step 3 — Senior lead review.** This one is a *synthesis* role, not an independent review, so it is the one spawn that correctly receives everything. If `creative-director` is **active**, spawn it as senior reviewer with the GDD + all findings + any disagreements: "Synthesise these. What matters most? Do you agree? Overall verdict?" — its synthesis becomes the **final verdict** in Phase 4. If `creative-director` is **archived**, the main review synthesises the verdict itself (or restore `creative-director` for a full adversarial pass).

**Step 4 — Surface disagreements.** Never silently pick a side. Present conflicts explicitly in Phase 4 for the user to adjudicate, and tag every finding with its source (`[game-designer]`, `[unity-performance]`, `[creative-director]`, …). Agreement is a finding too: a specialist that lands on a Phase 3 finding *without having been shown it* corroborates it — tag it `[corroborated]` rather than merging it away as a duplicate.

---

## Phase 4: Output Review

```markdown
## Design Review: [Document Title]
Specialists consulted: [list agents spawned, or "none — lean/solo mode"]
Re-review: [No — first review / Yes — prior verdict was X on YYYY-MM-DD]

### Prior Blocking Items: [N/A — first review / X of Y closed]
[One line per prior blocking item: fixed / still open / superseded / dropped without explanation]
[Dropped-without-explanation items are findings in their own right — list them under Required Before Implementation too]

### Completeness: [X/8 sections present]
[List missing sections]

### Dependency Graph
[List each declared dependency and whether its GDD file exists]

### Unity Implementability: [FEASIBLE / CONCERNS / BLOCKING]
[Specific Unity-related concerns]

### Required Before Implementation
[Numbered list — blocking issues only]

### Recommended Revisions
[Numbered list — important but not blocking]

### Specialist Findings (full mode only)
[Each finding tagged with its source agent, e.g. `[systems-designer]`, `[unity-performance]`]

### Specialist Disagreements (full mode only)
[Any unresolved conflicts between specialists or with the senior reviewer — for the user to adjudicate]

### Scope Signal
Estimate based on: dependency count, formula count, systems touched, and whether a new architecture decision (a vault WHY page) is likely required.
- **S** — single system, no formulas, no new ADR, <3 dependencies
- **M** — moderate complexity, 1-2 formulas, 3-6 dependencies
- **L** — multi-system integration, 3+ formulas, may require a new ADR
- **XL** — cross-cutting concern, 5+ dependencies, multiple new ADRs likely

### Verdict: [NOT ASSESSED — NO DATA / APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED]
```

No files are written during Phase 4. The **only** file this skill may ever write is the review log, under the rule in Phase 4b. Verdict: **COMPLETE**.

---

## Phase 4b: Record the Verdict

Skip this phase in `solo` mode. It runs in `full` and `lean`.

**Write scope — the one rule.** The single path this skill may create or modify is
`<dir-of-the-reviewed-doc>/reviews/<doc-basename>-review-log.md`. Nothing else. Not the GDD,
not `systems-index.md`, not any file a finding points at.

The reason is independence, not tidiness. A reviewer that edits what it reviews stops being a
reviewer, which is what §behavior's dispatched-reviewer rule protects against. Recording a verdict and
revising a design are two different permissions, and this skill holds only the first. When a
finding needs a fix, hand it to the user or to an agent in Phase 5 — never apply it here.

Ask once, with `AskUserQuestion`:
- Prompt: "Append this verdict to `reviews/[doc-basename]-review-log.md`? It lets the next review
  tell a fixed blocker from a dropped one."
- Options: `[A] Yes — append the entry` / `[B] No — skip the log`

On `[A]`, append (or create the file with) one entry. Newest entries go at the top, under a
`# Review log — [doc-basename]` heading:

```markdown
## Review — [YYYY-MM-DD] — Verdict: [NOT ASSESSED — NO DATA / APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED]
Scope signal: [S/M/L/XL]
Specialists: [list, or "none — lean mode"]
Prior blocking items: [X of Y closed, or "first review"]

### Blocking
1. [one line per blocking item — these are what the next review checks against]

### Recommended
1. [one line per non-blocking item]
```

Keep each blocking item to one line and make it self-contained. The next run reads this file
without the GDD open, so an item that only makes sense beside the design is an item that cannot
be checked later.

Never rewrite or delete an existing entry. The log is append-only, because its whole value is
showing what an earlier review said before the design moved.

---

## Phase 5: Next Steps

Skip this phase entirely in `solo` mode.

Use `AskUserQuestion`:
- Prompt: "Design review complete — verdict: [APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED]. How would you like to proceed?"
- Options (adjust based on verdict):
  - If **APPROVED**:
    - `[A] Hand off to lead-programmer for architecture planning`
    - `[B] Hand off to gameplay-programmer / unity-specialist for implementation`
    - `[C] Stop here`
  - If **NEEDS REVISION**:
    - `[A] Revise the GDD now, working with game-designer or systems-designer on blocking items` — this skill does not perform the edit itself (Phase 4b write scope); hand the blocking items over and let that agent or the user make the change
    - `[B] Stop here — revise in a separate session`
  - If **MAJOR REVISION NEEDED**:
    - `[A] Return to the main session with the vision/architecture conflict for the user to decide`
    - `[B] Stop here`
