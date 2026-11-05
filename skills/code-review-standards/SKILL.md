---
name: code-review-standards
disable-model-invocation: true
description: "User-invoked review pass over named Unity C# files or a diff. Routes each file to the right specialist agent (`unity-reviewer`, `unity-performance`, `unity-shader-specialist`, `unity-ui-specialist`), then merges their findings into two verdicts it never combines — Standards (does it follow the rules) and Spec (does it implement the approved plan, ADR, or design doc). Use when you want the full pass with the spec check, or before merging Unity gameplay code. A single read-only ruleset check on code just written is the `unity-reviewer` agent on its own. Triggers: review this file, code review, review my changes, did we build what was asked, does this match the spec, does this match the ADR, is anything missing from the spec."
argument-hint: "[path-to-file-or-directory]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash, Agent, AskUserQuestion
model: sonnet
---

## Insufficient input

**If the inputs this skill needs do not exist, the answer is "could not run".**
Never a filled-in report. Run this check first and stop if it fails.

1. List the inputs this skill reads: the named files or diff, `AGENTS.md`, and for the Spec axis the approved
   plan, ADR, GDD, or WHY page.
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

This skill enforces the Jacob ruleset (`AGENTS.md`) as the absolute standard. Every review must check:

- **Naming (§naming)**: `_camelCase` private fields, `PascalCase` public members, `[field: SerializeField]` for serialized auto-properties, `UPPER_SNAKE_CASE` constants.
- **Performance (§performance)**: No LINQ/foreach-on-dict/string-concat in Update/FixedUpdate/LateUpdate. Cache in Awake/Start. `TryGetComponent` over `GetComponent` + null check. Pool spawned objects. `CompareTag` not `tag ==`. No empty magic methods. No `Debug.Log` in production loops.
- **Architecture (§architecture)**: Strict MVC — no game logic in MonoBehaviours, no UnityEngine in Model classes, no raw data passed to View. New Input System only. ScriptableObject for config. Physics writes in FixedUpdate only. UniTask over Coroutine/Task.
- **Framework (§frameworks)**: UniTask with CancellationToken. VContainer — no Singletons. MessagePipe — interfaces for messages. Addressables — `*Async` only, release every handle, never `WaitForCompletion`. asmdef for module boundaries. SRDebugger wrapped in `#if !DISABLE_SRDEBUGGER`.

---

## Phase 1: Load Target Files

Read the target file(s) in full. Read `AGENTS.md` for project coding standards.

---

## Phase 2: Identify Specialists

Jacob is Unity-only — there is no per-project engine config to look up. Route each file by type, for use in Phase 7:

- C# gameplay/architecture files → `unity-reviewer` (Jacob-ruleset compliance reviewer)
- Hot-path / perf-sensitive files (Update loops, pooling, allocations) → `unity-performance`
- Shader files (`.shader`, `.hlsl`, Shader Graph) → `unity-shader-specialist`
- UI code (UGUI/UI Toolkit) → `unity-ui-specialist`
- DOTS/ECS code → `unity-dots-specialist`
- Cross-cutting or broad architecture concerns → `unity-specialist`

---

## Phase 3: ADR Compliance Check

Search for ADR references in, in priority order:
1. Header comments at the top of the implementation files
2. Commit messages referencing these files (`git log --oneline -- [file]`)

Look for patterns like `ADR-NNN` or a path to an ADR file.

If no ADR references found, note: "No ADR references found — ADR compliance check skipped."

For each referenced ADR: read the file, extract the **Decision** and **Consequences** sections, then classify any deviation:

- **ARCHITECTURAL VIOLATION** (BLOCKING): Uses a pattern explicitly rejected in the ADR
- **ADR DRIFT** (WARNING): Meaningfully diverges from the chosen approach without using a forbidden pattern
- **MINOR DEVIATION** (INFO): Small difference from ADR guidance that doesn't affect overall architecture

---

## Phase 3b: Spec Axis

The rest of this skill asks *does this code follow the rules*. This phase asks the other question:
**does it implement what was actually asked for?** Code can pass every rule and build the wrong thing.

Find the spec, in this priority order (it mirrors §behavior's authority order — explicit user statement > spec >
tests > current code behavior):

1. **The approved plan from this conversation.** §behavior requires a plan before implementation, so if one was
   approved, it is the spec and it outranks everything below.
2. **The governing ADR's Decision section**, already loaded in Phase 3.
3. **A GDD or system spec** from `game-design-docs` — including its §judgment cut list, which is as load-bearing as
   its feature list.
4. **A vault WHY page** (§vault) that the code points at with a `// WHY:` comment.

If none of the four exists, record "no spec available" and skip this phase. Do not invent the spec by reading
the code, because that guarantees the code passes.

With a spec in hand, report exactly three things:

- **Missing or partial** — what the spec asked for that isn't here.
- **Scope creep** — behaviour in the code that nothing asked for. Check the cut list: shipping something
  explicitly cut is a finding, not a bonus.
- **Implemented but wrong** — present, but doing something other than what the spec describes.

Quote the spec line for every finding. A spec finding with no quote scores 0 under Phase 8.

**Keep this phase's findings separate from every other phase's.** They are the Spec axis, and Phase 8 reports
them under their own verdict.

---

## Phase 4: Standards Compliance (Jacob Ruleset)

Evaluate against Jacob's coding standards:

- [ ] Private fields are `_camelCase`
- [ ] Public members are `PascalCase`
- [ ] Serialized auto-properties use `[field: SerializeField]`
- [ ] Constants are `UPPER_SNAKE_CASE`
- [ ] No LINQ in Update/FixedUpdate/LateUpdate
- [ ] No `foreach` on Dictionaries/HashSets in hot paths
- [ ] No string concatenation in hot paths
- [ ] References cached in Awake/Start (no `Find()`, `FindObjectOfType()`, `Camera.main` in game loop)
- [ ] `TryGetComponent` used instead of `GetComponent` + null check
- [ ] `CompareTag` used instead of `tag ==`
- [ ] No empty `Start()` / `Update()` magic methods
- [ ] No `Debug.Log()` in production gameplay loops
- [ ] MVC separation: no game logic in MonoBehaviours, no UnityEngine in Model classes
- [ ] UniTask used with CancellationToken (not Coroutine or standard Task)
- [ ] Addressables `*Async` only, every handle released, no `WaitForCompletion`
- [ ] Public methods and classes have XML doc comments
- [ ] Dependencies injected (no Singletons for game state)
- [ ] Configuration values from ScriptableObjects or external data, not hardcoded
- [ ] Cyclomatic complexity under 10 per method
- [ ] No method exceeds 40 lines (excluding data declarations)
- [ ] Systems expose interfaces, not concrete class dependencies

---

## Phase 5: Architecture and SOLID

**Architecture:**
- [ ] Correct dependency direction (engine ← gameplay, not reverse)
- [ ] No circular dependencies between modules
- [ ] Proper layer separation (UI does not own game state)
- [ ] Events used for cross-system communication (`event Action`, `UnityEvent`, or MessagePipe)
- [ ] Consistent with established patterns in the codebase

**SOLID:**
- [ ] Single Responsibility: Each class has one reason to change
- [ ] Open/Closed: Extendable without modification
- [ ] Liskov Substitution: Subtypes substitutable for base types
- [ ] Interface Segregation: No fat interfaces
- [ ] Dependency Inversion: Depends on abstractions, not concretions

**Smell baseline.** Read `references/smell-baseline.md` and match its twelve smells against the reviewed set.
It exists so a review that breaks no explicit rule still has something to say. Three rules bind it, and they
are in the file: the Jacob ruleset overrides the baseline, every smell is a judgement call that goes under
**Suggestions** and never blocks a merge, and anything Rider or the analyzers already enforce is skipped.

Several Unity shapes that comply with §code read as smells out of context — a Controller owning its Model, a View
that forwards to its Controller, a `[field: SerializeField]` float a designer tunes. The file carries a
**Not this** line for each. Check it before reporting, or this baseline becomes the noise Phase 8 exists to
suppress.

---

## Phase 6: Unity-Specific Concerns

- [ ] Frame-rate independence (delta time usage where applicable)
- [ ] No allocations in hot paths (Update loops, physics callbacks)
- [ ] Proper null handling (`== null` not `is null` for Unity objects)
- [ ] Resource cleanup (no leaked AsyncOperationHandles, Coroutines, or event subscriptions)
- [ ] Physics writes only in FixedUpdate
- [ ] `[UsedImplicitly]` on Unity magic methods, Animation Events, VContainer-injected dependencies
- [ ] Gate integrity: run `references/gate-integrity.md` on every test, CI, analyzer-config or threshold hunk
- [ ] Thread safety where required

---

## Phase 7: Specialist Reviews (Parallel)

Spawn all applicable specialists simultaneously via `Agent` — do not wait for one before starting the next.

### Unity Specialists

Using the routing from Phase 2, spawn in parallel:

- C# gameplay/architecture files → `unity-reviewer`
- Hot-path / perf-sensitive files → `unity-performance`
- Shader files → `unity-shader-specialist`
- UI code → `unity-ui-specialist`
- DOTS/ECS code → `unity-dots-specialist`
- Cross-cutting concerns → `unity-specialist`

### QA Testability Review

Spawn `qa-tester` via `Agent` in parallel with the Unity specialists. Pass:
- The implementation files being reviewed
- Any acceptance criteria or test cases the user named for this review

Ask the qa-tester to evaluate:
- [ ] Are all test hooks and interfaces exposed (not hidden behind private/internal access)?
- [ ] Do EditMode/PlayMode tests exist covering the changed logic?
- [ ] Are any acceptance criteria untestable as implemented (e.g., hardcoded values, no seam for injection)?
- [ ] Does the implementation introduce any new edge cases not covered by existing tests?
- [ ] Are there any observable side effects that should have a test but don't?

Collect all specialist findings before producing output.

**Verify every specialist finding before you report it.** A finding passes through to the report only with three things recorded:

- **File and line** it refers to.
- **Evidence.** Quote the code, or name the concrete input or state that triggers it.
- **Confidence.** `VERIFIED` means you checked it yourself. `UNVERIFIED — specialist claim` means you could not.

Report an unverified finding as unverified, or drop it. Never promote it to a defect because it is phrased confidently. Agents derive well and diagnose existing code badly. Without this step the review launders a guess: it enters as a specialist finding and leaves as a reviewed defect. Phase 8's confidence score rates a finding you have verified. It does not replace the check.

Label each verified defect `REGRESSION` (this change introduced it) or `PRE-EXISTING` (it is in the base). Never merge the two counts.

---

## Phase 8: Output Review

**Confidence scoring.** Rate each finding 0–100 (0 = false positive, 25 = might-be, 50 = real-minor, 75 = real-important, 100 = certain). Drop findings < 80. If you cannot quote the violated rule or point at the failing line, score 0. False positives erode trust — silence beats noise.

**Two axes, reported separately, never merged.** The Standards axis asks whether the code follows the rules.
The Spec axis (Phase 3b) asks whether it builds the asked-for thing. Code passes one and fails the other all
the time: rule-perfect code implementing the wrong feature is a Standards pass and a Spec fail; code that
does exactly what the plan said while breaking §architecture is the reverse.

Give each axis its own verdict and **do not pick a winner across them**. A single merged verdict lets a clean
Standards pass hide a Spec failure, which is the exact masking this split exists to prevent. Never re-rank a
Spec finding against a Standards finding either — they are not on one scale.

ADR findings belong to the Standards axis: Phase 3 asks whether the code conforms to a decision already made.
When an ADR is also the only spec available, Phase 3b asks a different question of the same document (is the
decision fully implemented), and the finding is filed once, in the axis whose question it answers.

```markdown
## Code Review: [File/System Name]

## Standards axis

### Unity Specialist Findings: [N/A — no specialist applicable / CLEAN / ISSUES FOUND]
[Findings from spawned specialist(s), or "No specialist applicable." if skipped]

### Testability: [N/A / TESTABLE / GAPS / BLOCKING]
[qa-tester findings: test hooks, coverage gaps, untestable paths, new edge cases]
[If BLOCKING: implementation must expose [X] before tests can run]

### ADR Compliance: [NO ADRS FOUND / COMPLIANT / DRIFT / VIOLATION]
[List each ADR checked, result, and any deviations with severity]

### Standards Compliance: [X/Y passing]
[List failures with line references and a confidence score, e.g. "(conf: 90)"]

### Architecture: [CLEAN / MINOR ISSUES / VIOLATIONS FOUND]
[List specific architectural concerns]

### SOLID: [COMPLIANT / ISSUES FOUND]
[List specific violations]

### Unity-Specific Concerns
[List Unity-specific issues]

### Smells: [NONE / N POSSIBLE]
[Baseline smells, each named and quoted, each labelled "possible" — judgement calls only]

### Standards — Required Changes
[Must-fix items — ARCHITECTURAL VIOLATIONs always appear here. Smells never do.]

### Standards — Suggestions
[Nice-to-have improvements, including every smell]

### Standards verdict: [NOT ASSESSED — NO DATA / APPROVED / APPROVED WITH SUGGESTIONS / CHANGES REQUIRED]

## Spec axis

### Spec source: [approved plan / ADR-NNN / GDD path / WHY page / NO SPEC AVAILABLE]
[If NO SPEC AVAILABLE, the rest of this axis is skipped and its verdict is N/A]

### Missing or partial
[What the spec asked for that isn't here — quote the spec line for each]

### Scope creep
[Behaviour nothing asked for, and anything shipped from the §judgment cut list — quote the spec line]

### Implemented but wrong
[Present but doing something other than what the spec describes — quote the spec line]

### Spec verdict: [N/A — no spec / MATCHES SPEC / GAPS / DIVERGES]

## Both axes

### Positive Observations
[What is done well — always include this section]

### Summary
[Standards: N findings, worst is <one line>. Spec: N findings, worst is <one line>.]
[No combined verdict. If one axis blocks, say which one and why.]
```

This skill is read-only — no files are written. Verdict: **COMPLETE**.

---

## Phase 9: Next Steps

Use `AskUserQuestion`:
- Prompt: "Code review complete — Standards: [verdict]. Spec: [verdict]. How would you like to proceed?"
- Carry **both** verdicts into the prompt. Collapsing them to one here undoes Phase 8's split, and the axis
  that blocks is the one the user needs to see first.
- Options (adjust based on the verdicts). **Either axis can block**, so offer merge only when both are clear:
  - Standards APPROVED **and** Spec MATCHES SPEC (or N/A):
    - `[A] Proceed / merge`
    - `[B] Stop here`
  - Standards blocks (CHANGES REQUIRED / MAJOR REVISION):
    - `[A] Fix the issues and re-run /code-review`
    - `[B] Stop here`
  - Spec blocks (GAPS / DIVERGES) while Standards is clear — the case a merged verdict used to hide:
    - `[A] Close the spec gaps, then re-run /code-review`
    - `[B] Revise the spec — the code is right and the plan was wrong`
    - `[C] Stop here`

If an ARCHITECTURAL VIOLATION is found:
- If the violation contradicts an **existing ADR**: fix the implementation to comply with the ADR. If the design has legitimately changed, revise the existing ADR in place to record the change. Do not create a competing one.
- If **no ADR exists** for the pattern that was violated: file the correct approach as a vault WHY page (ruleset §vault) before fixing the code.
- For other architectural violations: escalate to `lead-programmer`, or return to the main session with the conflict.

---

## Phase 7b: Read the history before proposing a refactor

Runs against the same files Phase 7 dispatched, before any finding is written up. Parallel-specialist
dispatch is Phase 7's job and uses Jacob's real agent roster — do not invent reviewer roles alongside it.

Odd-looking code is a claim you have not yet checked. Before proposing to change it:

- `git log --oneline -5 -- <file>` and `git log -S'<the odd construct>' --oneline -- <file>`.
- **Read the commit messages for intent.** `fix: perf regression`, `workaround: Unity bug 12345`,
  `revert:` — these mean the shape is load-bearing. Report it as context, not as a finding:
  *"This looks unusual but commit `abc123` says it works around a URP batching bug — confirm before changing."*
- **Recent churn raises priority, it does not lower it.** Code touched in the last two weeks is where
  regressions live; that is a reason to read it closely, not to leave it alone. What earns caution is a
  *stated reason* in the history, not recency.
- **Absence of history is not permission.** A file with one "initial commit" tells you nothing about
  intent — fall back to callers and tests (`query_graph_tool` pattern=`callers_of` / `tests_for`).
- Genuinely stale code — no changes in 6+ months, no tests, **and** no callers (verify all three) —
  is a removal candidate. Two of three is not.

This is §behavior's *intent before behavior change* applied to review: resolve `code does X; the review expects
Y; the history says Z` before writing the finding. Where they disagree, say so rather than filing Y.

---

## Sources

- NeoLabHQ/context-engineering-kit `plugins/review`: review-lens taxonomy and the historical-context
  check. The multi-agent dispatch half was **not** taken — Phase 7 already spawns Jacob's real
  specialist roster in parallel, and a second reviewer vocabulary would compete with it.
- mattpocock/skills `engineering/code-review` (MIT, @6654f6b): the twelve-smell Fowler baseline
  (`references/smell-baseline.md`) and the two-axes-never-merged rule in Phase 8. Its issue-tracker
  plumbing was **not** taken — Jacob has no tracker, so Phase 3b sources the spec from the approved
  §behavior plan, the governing ADR, a `game-design-docs` GDD, or a §vault WHY page instead. The Unity
  anti-matching in the baseline is Jacob's, not upstream's.
- Jacob Ruleset (`AGENTS.md`): §code coding standards
