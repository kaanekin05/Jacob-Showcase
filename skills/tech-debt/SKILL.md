---
name: tech-debt
description: "Track, categorize, and prioritize technical debt across the codebase. Scans for debt indicators, maintains a debt register, and recommends repayment scheduling."
argument-hint: "[scan|add|prioritize|report]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Write, AskUserQuestion
model: sonnet
---

## Insufficient input

**If the inputs this skill needs do not exist, the answer is "could not run".**
Never a filled-in report. Run this check first and stop if it fails.

1. List the inputs this skill reads: the source tree to scan, its `// SHORTCUT:` markers, and the existing debt
   register.
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

When scanning for technical debt in Unity projects, check for Jacob-specific violations:

- **Performance debt (§performance)**: LINQ in Update, uncached Find/GetComponent calls, string concatenation in hot paths, empty magic methods, Debug.Log in production loops.
- **Architecture debt (§architecture)**: Game logic in MonoBehaviours, UnityEngine references in Model classes, raw data passed to View, Singleton usage instead of VContainer.
- **Framework debt (§frameworks)**: Coroutine usage instead of UniTask, missing CancellationToken, hardcoded config instead of ScriptableObject, Resources.Load instead of Addressables, `WaitForCompletion` on Addressables handles.
- **Naming debt (§naming)**: Inconsistent field naming, missing `[SerializeField]` on inspector fields, public fields that should be properties.

---

## Phase 1: Parse Subcommand

Determine the mode from the argument:

- `scan` — Scan the codebase for tech debt indicators
- `add` — Add a new tech debt entry manually
- `prioritize` — Re-prioritize the existing debt register
- `report` — Generate a summary report of current debt status

If no subcommand is provided, output usage and stop. Verdict: **FAIL** — missing required subcommand.

---

## Phase 2A: Scan Mode

**Scope before you scan.** Debt only costs what it is paid for, so weight the scan toward code that keeps
changing. If the user named a direction, take it. Otherwise run `git log --oneline -60 --name-only` and let
the paths that keep reappearing pull attention first. A 900-line file nobody has touched in a year is worth
less than a 200-line one edited every week. If the churn is scattered with no hot spot, widen the net and say
so. State the scope in one line before scanning.

Search the codebase for debt indicators:

- `TODO` comments (count and categorize)
- `FIXME` comments (bugs disguised as debt)
- `HACK` comments (workarounds needing proper solutions)
- `@deprecated` markers
- `// SHORTCUT:` markers — deliberate corner-cuts left per §behavior, each naming a ceiling and an upgrade trigger (`// SHORTCUT: <ceiling>, <upgrade path>`). Grep `(#|//) ?SHORTCUT:` (skip `node_modules`, `.git`, build output). Pull the ceiling and trigger straight from the comment; a marker naming **no** upgrade trigger gets a `no-trigger` tag — those silently rot, surface them first.
- Duplicated code blocks (similar patterns in multiple files)
- Files over 500 lines (potential god objects)
- Methods over 40 lines (complexity)

**Unity-specific scans:**
- LINQ usage in Update/FixedUpdate/LateUpdate methods
- `Find()`, `FindObjectOfType()`, `Camera.main` calls outside Awake/Start
- `GetComponent()` without caching
- `tag == "..."` instead of `CompareTag("...")`
- Empty `Start()` / `Update()` methods
- `Debug.Log()` in gameplay code
- `Instantiate()` / `Destroy()` without pooling
- Missing `CancellationToken` on UniTask calls
- Unreleased `AsyncOperationHandle` for Addressables
- Singleton patterns instead of VContainer DI

**The deletion test.** The scans above find code that is *there*. This one finds code that should not be.
For anything that looks like a thin pass-through — a wrapper, a single-implementer interface, a class whose
methods mostly forward — ask: **would deleting this concentrate complexity, or just move it?**

- *Concentrates* → real debt. Removing it puts the logic behind one smaller surface, and the file count drops.
  Log it as Architecture Debt.
- *Just moves it* → not debt. The indirection is carrying something; leave it alone and don't log it.

This is §behavior's reduction ladder rung 1 (does it need to exist at all?) aimed at code that already shipped,
rather than at code about to be written. `karpathy-guidelines` has the countable form: an abstraction with one
implementation and one caller is indirection, and a seam needs two adapters to be real.

**Two things the deletion test must not fire on.** §architecture's MVC layers are load-bearing even when a Controller
looks thin, and §frameworks's asmdef boundaries are deliberate separation rather than accidental indirection.
Deleting either concentrates complexity on paper and breaks the architecture in practice.

Categorize each finding:

- **Architecture Debt**: Wrong abstractions, MVC violations, coupling issues, failed deletion tests
- **Performance Debt**: Hot-path allocations, uncached references, LINQ in Update, unoptimized queries
- **Framework Debt**: Wrong async patterns, missing DI, hardcoded config
- **Code Quality Debt**: Duplication, complexity, naming, missing types
- **Test Debt**: Missing tests, flaky tests, untested edge cases
- **Documentation Debt**: Missing docs, outdated docs, undocumented APIs
- **Dependency Debt**: Outdated packages, deprecated APIs, version conflicts

**State the denominator.** Count the source files the scan covered, and report that count with the findings. Zero findings over 400 files is a clean codebase. Zero findings over zero files is no information, so that case is `NOT ASSESSED — no source files to scan` (see Insufficient input). Give the count even when it is large and the finding count is genuinely zero.

Present the findings to the user.

Ask: "May I write these findings to `docs/tech-debt-register.md`?"

If yes, update the register and never overwrite it. **Match before appending.** A finding with the same file and the same category as an existing `Open` entry updates that entry instead of adding a duplicate. An `Open` entry whose pattern is no longer in its file is proposed as `Resolved [date]`. List those in the same approval. Verdict: **COMPLETE** — scan findings written to register.

If no, stop here. Verdict: **BLOCKED** — user declined write.

---

## Phase 2B: Add Mode

Ask the user for the description, affected files, and impact if left unfixed (plain text prompts).

Then use `AskUserQuestion` to collect the **category**:
- Prompt: "What category does this tech debt belong to?"
- Options:
  - `[A] Architecture Debt — wrong abstractions, MVC violations, coupling issues`
  - `[B] Performance Debt — hot-path allocations, uncached references, unoptimized queries`
  - `[C] Framework Debt — wrong async patterns, missing DI, hardcoded config`
  - `[D] Code Quality Debt — duplication, complexity, naming, missing types`
  - `[E] Test Debt — missing tests, flaky tests, untested edge cases`
  - `[F] Documentation Debt — missing/outdated docs, undocumented APIs`
  - `[G] Dependency Debt — outdated packages, deprecated APIs, version conflicts`

Then use `AskUserQuestion` to collect the **estimated fix effort**:
- Prompt: "What is the estimated effort to fix this item?"
- Options:
  - `[A] S — Small (under 1 day)`
  - `[B] M — Medium (1–3 days)`
  - `[C] L — Large (3–7 days)`
  - `[D] XL — Extra Large (over 1 week)`

Present the complete new entry to the user.

**Match before appending.** If an existing `Open` entry has the same file and the same category, show it. Ask whether to update that entry instead of adding a duplicate.

Ask: "May I append this entry to `docs/tech-debt-register.md`?" On a match, ask "May I update the existing entry instead?"

If yes, append the entry, or update the matched one. Verdict: **COMPLETE** — entry added to register.

If no, stop here. Verdict: **BLOCKED** — user declined write.

---

## Phase 2C: Prioritize Mode

Read the debt register at `docs/tech-debt-register.md`.

Score each item by: `(impact_if_unfixed × frequency_of_encounter) / fix_effort`

Re-sort the register by priority score and recommend which items to include in the next sprint.

Present the re-prioritized register to the user.

Ask: "May I write the re-prioritized register back to `docs/tech-debt-register.md`?"

If yes, write the updated file. Verdict: **COMPLETE** — register re-prioritized and saved.

If no, stop here. Verdict: **BLOCKED** — user declined write.

---

## Phase 2D: Report Mode

Read the debt register. If it does not exist, stop and report
**`NOT ASSESSED — NO DATA`**, naming the missing register and saying that
`scan` has not been run yet. Verdict: **NOT ASSESSED** — no register to read.

Otherwise generate summary statistics:

- Total items by category
- Total estimated fix effort
- Items added vs resolved since last report
- Trending direction (growing / stable / shrinking)

Flag any items that have been in the register for more than 3 sprints.

Output the report to the user. This mode is read-only — no files are written. Verdict: **COMPLETE** — debt report generated.

---

## Phase 3: Next Steps

- Run `scan` at least once per sprint to catch new debt.
- Schedule high-priority debt items into the next sprint (the `lead-programmer` agent owns this call for code-level debt).
- Run `report` at the start of each sprint to track debt trends over time.
- Items older than 3 sprints without action should either be fixed or consciously accepted with a documented reason.

### Debt Register Format

```markdown
## Technical Debt Register
Last updated: [Date]
Total items: [N] | Estimated total effort: [T-shirt sizes summed]

| ID | Category | Description | Files | Effort | Impact | Priority | Status | Added | Sprint |
|----|----------|-------------|-------|--------|--------|----------|--------|-------|--------|
| TD-001 | [Cat] | [Description] | [files] | [S/M/L/XL] | [Low/Med/High/Critical] | [Score] | [Open / Resolved YYYY-MM-DD / Accepted — reason] | [Date] | [Sprint to fix or "Backlog"] |
```

`Status` is `Open` when a row is added. `Resolved YYYY-MM-DD` records the day the debt was fixed. `Accepted — reason` records a conscious decision to keep it. Report Mode counts items added versus resolved from the `Added` date and the `Resolved` date.

### Rules
- Tech debt is not inherently bad — it is a tool. The register tracks conscious decisions.
- Every debt entry must explain WHY it was accepted (deadline, prototype, missing info).
- "Scan" should run at least once per sprint to catch new debt.
- Items older than 3 sprints without action should either be fixed or consciously accepted with a documented reason.
