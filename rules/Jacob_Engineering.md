# Jacob — AI & Agent Engineering (read before changing Jacob's own tooling)

**Gate (ruleset §agent-engineering).** Read the relevant block here *before* authoring or reworking a skill, agent,
command, hook, or MCP entry; before touching model config; and before editing any of Jacob's own
governance files. The master ruleset keeps only the headline; the craft and the conventions live here,
because they matter on a small fraction of turns and would otherwise cost every turn (§agent-engineering — context is
the scarce resource).

Companion files: wiring and inventory → `rules/Jacob_Layout.md`. The authoring *workflow* belongs to
Anthropic's own tools. Invoke **`anthropic-skills:skill-creator`** to build a skill and
**`plugin-dev:agent-development`** to build an agent. Dispatch **`plugin-dev:skill-reviewer`** to review
a skill. This file is the standing reference behind them, plus the Jacob wiring they cannot know about.

Moved out of the ruleset body on 2026-07-25 during a token-density pass. No rule was changed.

---

## Operating the harness — what fires when {#engineering/dispatch}

Agentic CLI coding is not "a chat with tools". It is a set of distinct primitives with **different
invokers, different costs, and different reliability**. Picking the wrong one is the most common design
error, and it is invisible until the thing under- or over-fires in production.

| Primitive | Who pulls the trigger | Canonical home in Jacob | Context cost | Reach for it when |
|---|---|---|---|---|
| **Rules** (`AGENTS.md` / `CLAUDE.md`) | Nobody — always resident | `AGENTS.md` (symlinked per tool, §workspace) | **Every token, every turn** | Invariants that must never be forgotten. The most expensive surface — offload detail and keep a headline index |
| **Skill** | The **model**, by matching `description:` | `skills/<name>/SKILL.md` | Zero until it fires, then full body | The main thread needs a procedure or knowledge *mid-task* |
| **Command** | The **user**, explicitly (`/name`) | `commands/<name>.md` | Zero until typed | A repeatable workflow a human starts deliberately |
| **Agent** | The model, by delegation | `agents/<name>.md` | A **whole separate context window** + cold start | Isolation, parallel fan-out, or heavy reads that must not pollute the main thread |
| **MCP server** | The model, as tools | `mcp/servers.json` | Tool schemas resident every turn | A live external capability (docs, code graph, Editor) |
| **Hook** | The **harness**, deterministically | `settings.json` (user-managed; the only hook `bootstrap.sh` installs is the git pre-commit doctor gate) | None — runs outside the model | Something that must happen *every* time regardless of what the model decides |

The four judgments the table can't encode:

- **If it must run reliably, make it a command.** A `description:` is a probability, not a guarantee — a skill can always under-fire.
- **Context is the scarce resource, not tokens-as-money.** Everything resident competes for attention: a bloated ruleset degrades *every* turn, including turns it's irrelevant to. Before adding anything always-resident, ask what it displaces.
- **Determinism belongs in hooks, not prompts.** "Always do X after Y" in a prompt is a suggestion the model may drop under load. If a rule has failed twice by being ignored, it's a hook, not a bullet.
- **The model doesn't know your wiring — the docs do.** A primitive works only if it's discoverable through the spine (§workspace): correct location, correct frontmatter, symlinked, `./scripts/doctor.sh` green. An artifact that exists but isn't wired is invisible, and its absence looks exactly like a model failure.

### Agent dispatch policy (ruleset §invocation)

Agents auto-dispatch. The model fires them on `description:` match, with no permission step. Five
rules keep that from turning into a stampede.

- **The ask-gate survives, once.** §behavior still requires agreeing the plan before the *first* dispatch
  of a new feature. A subagent cannot ask a question, so an unresolved ambiguity becomes a guess
  written to disk. After the plan is agreed, dispatch freely without pausing between tasks — this is
  the same two-phase boundary §behavior already defines for Superpowers.
- **One writer per file.** Two agents editing one file in parallel is a lost update, not a merge.
  Fan out across files, never within one.
- **Reviewers are free, writers are not.** `unity-reviewer`, `unity-performance`, `verifier` and
  `Explore` are read-only. Fire them in parallel and often; the cost is a context window that would
  otherwise fill with file dumps. A writer changes disk state, so it needs a brief you have read.
- **Every writer returns a diff.** Each writer file carries a `## Return contract` section requiring
  the unified diff plus a per-file §code compliance line. A prose summary is not a valid return,
  because the dispatcher cannot review what it cannot see.
- **Review the return, don't trust it.** The subagent ran cold, on a narrower model context, and
  could not consult you. "Done" is a claim, not evidence. §behavior's dispatched-reviewer rules apply in
  reverse here: you are now the reviewer, and agreement is the failure mode.

**Descriptions carry a differentiator or they collide.** Nine Unity agents overlap in domain. Each
description must name which sibling owns the adjacent work, or one task matches all nine.
`unity-specialist` is the declared default writer; UI, Addressables, DOTS, shaders, Editor tooling
and tests each carve out a slice against it. `scripts/doctor.sh` Check 12 warns on an agent
description with no `Use when`, `Triggers:` or `<example>`.

---

## Authoring new primitives {#engineering/authoring}

- **Skill vs. agent — decide first.** A **skill** is a procedure/knowledge injected into the *current* context. An **agent** is a *separate context window* with its own tool grant and system prompt — reach for it only for isolation, parallel fan-out, or heavy reads that shouldn't pollute the main thread. Default to a skill; justify an agent. (Delegation is never free: a subagent starts cold and re-derives context you already hold.)
- **Authoring vs. discovery — don't collide.** *Looking for* a capability is `find-skills`; *building* a new one is `anthropic-skills:skill-creator` (skills) or `plugin-dev:agent-development` (agents). Route in that order — never let both fire on one "I want a skill". Description-space overlap is auditable: `scripts/evals/overlap-audit.py` (report-only, run by `/check-updates`).
- **The `description:` is load-bearing.** It is the *entire* signal the model matches to fire a skill or route to an agent. Write it deliberately — concrete triggers, real verbs/nouns — and check both over-fire and under-fire before shipping. This is the #1 authoring failure.
- **Least privilege.** Grant an agent the minimum `tools:` it needs (e.g. `["Read", "Grep", "Glob"]` for a read-only reviewer). Never a blanket `*` without cause — `scripts/doctor.sh` Check 10 fails on a wildcard.
- **Single responsibility.** One skill/agent = one job. If the `description:` needs an "and" to explain it, split it.
- **"Better" requires an eval, not vibes.** Before claiming a skill/agent/prompt improved, run a behavior check (trigger test, sample-prompt parity). Run trigger evals with `scripts/evals/run-trigger-eval.sh`; `anthropic-skills:skill-creator` owns the description-tuning loop. A change that only *reads* better isn't verified.
  **Two halves, don't confuse them.** `scripts/evals/response-quality/` is *prospective*: synthetic prompts, blind judging, real money, a release gate. It decides whether to ship a rule. `scripts/evals/register-check.py` is *retrospective*: real Claude Code transcripts, free, deterministic counting, no judge. It finds out whether a shipped rule actually landed. A rule can pass the first and fail the second, which is exactly what happened to §behavior's register rule on 2026-08-31.
- **Wiring is mandatory, not optional.** Anthropic's authoring tools stop at the file. A new native skill or agent is not done until all five of these hold:
  1. `skills/skills.lock.json` has its entry, with `source: authored-in-place` and `update_policy: native`. Agents get no lock entry.
  2. An agent carries `model:` and `category:` per `rules/MODEL_POLICY.md`. `scripts/doctor.sh` Check 7 validates the model token.
  3. A new agent has its row in the `agents/AGENTS.md` routing table. A new skill has its row in `skills/AGENTS.md`.
  4. `./bootstrap.sh` has rewired the spine. A new file inside an already-linked directory needs no re-run. A new top-level directory does.
  5. `./scripts/doctor.sh` exits 0 (ruleset §spine gate). Then run `python3 scripts/evals/overlap-audit.py` and tighten any description it flags.
  `plugin-dev:skill-reviewer` flags descriptions over 500 characters. The spec cap is 1,024, and Jacob's descriptions run 650 to 1,006 by design. Ignore that one finding.
- **Description = routing contract, not summary.** The description must include three elements: (1) *what* the skill does, (2) *when* to use it (trigger phrases/situations), (3) *differentiator* vs related skills. Pattern: `"X via Y. Use for [situations]. [Differentiator]."`. Never summarize the full workflow in the description — the agent follows the summary and skips loading the body. (Harvested from `effective-agent-skills` 2026-08-23.)
- **An enforcement trigger must hang on an event visible in the tool record.** Never on the agent noticing that a moment qualifies — self-assessment ("is this a major deliverable?") is exactly what fails under load. And a trigger bound to a single tool is silently inert in every session that does not use that tool, so it always needs a second, independent path. Prefer a concrete write over a remembered check: the write is the enforcement. (Harvested from `one-skill-to-rule-them-all` 2026-08-30.)
- **Progressive disclosure is the architecture.** Level 1: `name` + `description` (~100 tokens, always resident). Level 2: full SKILL.md body (<5k tokens, loaded on match). Level 3: referenced files and scripts (unbounded, on demand). This is why bundled content has no practical limit — files don't consume tokens until accessed. Keep SKILL.md lean; push detail to `references/` once the body grows past ~200 lines. (Harvested from `effective-agent-skills` 2026-08-23.)
- **Writing craft for any agent-read document** is the vendored `writing-for-agents` skill: completion criteria, leading words, negation, and no-op pruning. This file stays the home for Jacob's own wiring and conventions. (Vendored from `mattpocock/skills` 2026-10-10.)
- **Match strictness to fragility.** Scale instruction rigidity to how costly a wrong move is: loose natural-language heuristics when many approaches are valid (code review); pseudocode or templates when there's a preferred pattern but variation is acceptable (report format); exact scripts and strict step lists when the workflow is fragile or error-prone (migrations, data patching). (Harvested from `effective-agent-skills` 2026-08-23.)
- **Build validation loops into skills.** The single biggest output quality improvement: state a verify → fix → re-verify loop explicitly in the skill body. Document skills → visual QA pass. Code skills → tests pass + zero errors. Data skills → schema validation. A skill without a validation step is incomplete. (Harvested from `effective-agent-skills` 2026-08-23.)
- **State-check before action.** Don't assume setup is done. Instruct the agent to verify state, then branch: "First check if X is configured: [command]. If not, walk the user through setup: [steps]." Prevents silent failures from missing prerequisites. (Harvested from `effective-agent-skills` 2026-08-23.)
- **Compose primitives, don't bundle workflows.** One skill = one capability or one discipline. Resist bundling concerns into "the X workflow." Multiple small skills combine at runtime; one large skill is rigid. If the description needs an "and" to explain what it does, split it. (Harvested from `effective-agent-skills` 2026-08-23.)
- **Preload an agent's governing skill; don't restate it in the body.** An agent whose job is defined by a skill Jacob already owns should name it in `skills:` — the full skill content is injected at the subagent's startup, not just the description. Restating those standards in the agent body is a second canonical home that drifts from the skill; a bare tool grant is worse, because an agent with no `Skill` tool cannot reach the skill at all and silently re-derives the standard from memory (`agents/unity-reviewer.md` enforces §naming/§architecture and §frameworks on `["Read","Grep","Glob"]`). This is progressive disclosure applied to the agent surface. Keep a body that stands alone anyway — put the *procedure* there and let `skills:` carry the *standard*. (Harvested from `claude-code-best-practice` 2026-08-31; verified against `code.claude.com/docs/en/sub-agents`.)
- **Skill invocation hierarchy — a user-invoked skill cannot call another user-invoked skill.** A skill invoked by `/name` is user-invoked (ruleset §agent-engineering). It can call *model*-invoked skills via the Skill tool, but a Skill call aimed at another user-invoked skill **fails silently** — no error, no output, and the calling skill proceeds as if the dependency ran. That is the bug this boundary prevents: skill A auto-runs user-invoked skill B as a setup step, B never fires, and A builds on a broken assumption about what the human has already done. If a setup step must run first, **instruct the human to invoke it** and verify its output before continuing (see "State-check before action" above).
- **Self-reference gate.** Anthropic's authoring tools and the §agent-engineering persona may *propose* edits to the ruleset, agents, or skills — but nothing auto-applies: ruleset §behavior (ask before implementing) and §workspace (commit only when asked) gate every change to Jacob's own governance.

---

## Governance-file conventions (doctor-asserted) {#engineering/conventions}

Negative space for Jacob's own docs and config — things that must **not** exist or happen. Framework
anti-patterns are enforced by ruleset §frameworks; reading anti-patterns by ruleset §context.

- **Retired directory conventions must stay retired** — `agents/agents/`, `skills/skills/`, `dotnet-skills-master/`. The doubly-nested convention is dead; flatten anything that reappears. `scripts/doctor.sh` Check 2b asserts this.
- **Backticks mean "live path."** A backticked workspace-relative path in the ruleset, `rules/MODEL_POLICY.md`, `README.md`, `rules/Jacob_Layout.md`, or this file is asserted to exist by `scripts/doctor.sh` Check 2. Name a deleted file in prose, not code, so the doc isn't asserting something untrue.
- **The master ruleset owns prefix-free anchors; every other document prefixes its own.** `§performance` and `§behavior` are `AGENTS.md`. `engineering/` is this file, `layout/` is `rules/Jacob_Layout.md`, `archive/` is `vault/wiki/meta/jacob-ruleset-archive.md`. A heading declares its anchor inline in braces, and the headings are the only source of truth, so nothing can drift out of sync. Those three prefixes are reserved words: cited bare, without a slug after them, they are rejected, because `layout` alone is ambiguous with the `layout/` namespace.
- **A bare section number is meaningless and `scripts/doctor.sh` Check 11 fails on it.** It also fails a citation that resolves to no heading, a duplicate anchor, and an anchor declared under a namespace its file does not own. Numbers were retired on 2026-10-04 because they could not express which document they belonged to: 166 of 668 citations named a `.md` file on the same line and had to be skipped, and 7 of those 166 were broken, including `doctor.sh` itself citing a retired section for the model register.
- **Sections move freely now.** There is no renumbering and no gap to preserve. Retiring a section means deleting its heading and removing its anchor from every citation, which Check 11 then reports. One alias exists, `§code`, standing for the four Unity code sections that are always cited together: `§naming`, `§performance`, `§architecture`, `§frameworks`. Adding another alias means editing Check 11's `ALIASES` table.
- **Old numbers are kept as history, not as pointers.** The number-to-anchor table is in `vault/wiki/meta/jacob-ruleset-archive.md` §archive/anchor-map. `.memsearch/` journals and vault pages keep the numbers they were written with, because they record what was true on their date.

Removal history and the retirement of the doubly-nested convention:
`vault/wiki/meta/jacob-ruleset-archive.md` §archive/directory-map.

---

## Model register {#engineering/model-register}

`rules/MODEL_POLICY.md` is a **reference register** of Claude's model IDs — *not* a routing policy. It is the
source of truth for IDs; read it there, and update the roster block when a new model ships.

- **Claude Code model selection is manual and user-owned.** Nothing in this repo writes `ANTHROPIC_MODEL` / `ANTHROPIC_DEFAULT_*_MODEL`; `./scripts/bootstrap.sh` does not touch them and `--uninstall` does not remove them. Change them by hand in `~/.claude/settings.json` `env`. **Never add this to bootstrap.** `scripts/doctor.sh` and `/check-updates` do not inspect the tier state.
- **Per-agent `category:`** documents *intent* (what kind of work the agent was designed for), not routing. `model:` is the Claude Code tier selector.
- `scripts/doctor.sh` Check 7 validates Claude model tokens in agent frontmatter. The tier env vars themselves are **user-owned** and deliberately not inspected by `scripts/doctor.sh` or `/check-updates`.

- **Never invent a model slug, context size, parameter, or product capability — for any provider.** `rules/MODEL_POLICY.md` is the register for IDs; the built-in `claude-api` skill is the gate for Anthropic specifics. Outside both, verify against the provider's live docs or say the detail is unverified. A consumer product and its API are different surfaces: the same model family exposes different controls in each, so a picker option is not an API parameter.


---

## External plugin awareness {#engineering/plugins}

Jacob coexists with external plugins that modify agent behavior. When one with behavioral effects is
installed, add an entry here and resolve any conflict per ruleset §behavior.

**Superpowers** (`obra/superpowers`) — general-purpose agent process methodology governing *how* the
agent works (brainstorming → plans → subagent-driven development → verification → review).
`bootstrap.sh` installs it through the Claude marketplace. There is no local clone.

- **Boundary:** the two-phase model in ruleset §behavior is the complete ownership split. Process → Superpowers; domain (ruleset §code) and reduction discipline (ruleset §behavior) → Jacob.
- **Not vendored.** Update it with `claude plugin update superpowers@claude-plugins-official`.
- **Uninstall:** `./bootstrap.sh --uninstall` removes it.
- Full install mechanics → `rules/Jacob_Layout.md` §layout/skill-inventory and `vault/wiki/meta/jacob-ruleset-archive.md` §archive/plugin-awareness.

---

## Validation {#engineering/validation}

`./scripts/doctor.sh` must exit 0 after any change covered by this file. Checks that specifically guard these claims:

| Check | Guards |
|---|---|
| 2 | Every backticked workspace path cited in the ruleset, MODEL_POLICY, README, Jacob_Layout, **and this file** resolves |
| 2b | Retired layout conventions stay absent |
| 7 | Claude model tokens in agent frontmatter are real IDs |
| 10 | No agent carries a wildcard `tools:` grant |
| 11 | Every bare `§N` in a governance file resolves to a real ruleset heading |
| 15 | The `rules/output-styles/` file §behavior points at exists, is symlinked, and is selected by `settings.json` |

A new check is not a guard until you have seen it fail. Run it once against a known violation and once against a clean control. Check 4b skipped every anchored link until 2026-10-10 because nobody did this.

### Dispatched-reviewer finding classification (§behavior)

When the critique is a *dispatched* reviewer rather than yourself — `verifier`, `unity-reviewer`, or a
fresh-context subagent — §behavior requires you to hand it the artifact plus the contract, never your claim.
Handing over the conclusion buys agreement, not review: a reviewer given your reasoning grades the
reasoning, and its default balanced-verdict shape does the rest.

- **Strip reasoning, not evidence.** A caller, guard, or test that contradicts the claim goes in the handoff.
- **Prompt it adversarially.** Use "find what is wrong; assume the author is overconfident", and paste that framing verbatim. It overrides a review agent's default balanced-verdict shape.

Classify each finding it returns, in this precedence order:

| Class | What it means | What you do |
|---|---|---|
| **Contract misread** | The reviewer judged against something the contract did not say | Fix the contract and re-run. Do not argue with the finding |
| **Valid and actionable** | The defect is real and inside scope | Change it |
| **Valid trade-off** | Real, but the cost was accepted deliberately | Document it — a `// SHORTCUT:` marker or a vault WHY page |
| **Noise** | Out of scope or wrong | Note it, then ask whether the contract should have ruled it out |

Contract misread comes first because every class below it is unsafe to judge until the contract is
right. The **rubber-stamp signal** is the stop condition: two or more cycles where the reviewer
raised substantive findings and you marked none actionable means you are validating, not reviewing.
Stop and escalate.

### Self-refine critique dimensions (§behavior tier-1 full pass)

The ruleset names these seven. The prompts live here. Ask them of your own draft *before* presenting it,
not of the user's request. One pass, then refine. The 3-cycle stop in §behavior is a hard limit.

| Dimension | Ask |
|---|---|
| **Accuracy** | Is every factual claim verified, or did I assert something I only assumed? Did I state a negative ("X doesn't exist") without searching for X by name? |
| **Completeness** | Did I deliver the whole requested scope, or quietly narrow it? What did I leave out, and did I say so? |
| **Edge cases** | What happens at the boundaries: null, empty, zero, overflow, first run, concurrent callers? |
| **Security** | Did I introduce a trust-boundary gap? Is input from outside the system validated? (Never on the reduction ladder's chopping block, §behavior.) |
| **Implementation-readiness** | Can this actually be built as written, or does it hand-wave a step? Is there a named verify for each claim? |
| **Clarity** | Does the first line carry the answer? Would someone who wasn't in this conversation follow it? |
| **Register** | Does any sentence carry a second clause behind an em-dash, colon, or parenthetical? Split it in two. Is there a plainer word for anything that isn't a domain term? (§behavior plain-English register. This is the one dimension that also runs at tiers 2–5.) |

Harvested from NeoLabHQ/context-engineering-kit `plugins/reflexion` 2026-08-26. Moved out of the resident
ruleset 2026-08-27 (§agent-engineering: the prompts are consulted during a tier-1 pass, not every turn). **Register** was
added 2026-08-31 and is the exception. It runs at every tier, because short answers are where dense
phrasing hides.

---

## Agentic design patterns — the shape checklist {#engineering/shape-checklist}

The primitive table (`rules/Jacob_Engineering.md` §engineering/dispatch) answers *what fires*. This answers the
question before it: **what shape should the system be at all.** Read it at the design point, before
choosing a primitive — the default failure is grabbing the first plausible shape because it's the one
that came to mind (§engineering/divergent).

Taxonomy adapted from Antonio Gulli's *Agentic Design Patterns* (2026). **Nothing was vendored** — the
book is unlicensed for redistribution and its code is Python/LangChain/ADK, which is the wrong domain:
those patterns build agent *applications*, Jacob builds agent *harness configuration*. The "when" and
"wrong when" columns below are Jacob's own, mapped onto its primitives.

| Shape | Jacob primitive | Reach for it when | Wrong when |
|---|---|---|---|
| **Prompt chaining** — sequential decomposition | Phases inside one skill | Steps have a hard order and each needs the last one's output | The model can hold it in one pass; chaining just adds latency and drift |
| **Routing** — dispatch to specialists | Agent delegation; `description:` matching | Inputs split into genuinely different kinds of work | One handler covers the spread — routing then adds a failure mode for nothing |
| **Parallelization** — concurrent fan-out | Multiple `Agent` calls in one block | Subtasks are independent and reads are heavy | Subtasks share state, or the merge costs more than the split saved |
| **Reflection** — self-critique before returning | `verifier` agent; ruleset §behavior re-present-the-plan | Output quality beats latency and a rubric exists | No rubric — self-critique without one launders confidence, it doesn't add correctness |
| **Tool use** | MCP server; Bash/Read/Grep grants | The capability is live, external, or authoritative | Static knowledge a gated doc already holds |
| **Planning** — decompose before acting | Ruleset §behavior todo lists; `Plan` agent | Multi-system work where order carries risk | Single-file edits; the plan becomes theater |
| **Multi-agent** — collaborating contexts | `agents/<name>.md` roster | Isolation is the point, or context would otherwise blow | One context can hold it — every agent starts cold and re-derives what you already know |
| **Memory** — state across turns | `memory/`, `vault/` (ruleset §vault) | The fact outlives this conversation | It's derivable from the repo; then the repo is the memory |
| **Human-in-the-loop** — approval gate | Ruleset §behavior ask-gate; §workspace commit gate; hooks | Irreversible, outward-facing, or spends money | Reversible local edits — a gate nobody needs trains you to click through the ones you do |
| **Guardrails** | Ruleset §code; `scripts/doctor.sh` checks | The failure is silent and expensive | The failure is loud and cheap — a test already catches it |
| **Evaluation** | `scripts/evals/response-quality/` (prospective), `scripts/evals/register-check.py` (retrospective), `scripts/evals/overlap-audit.py` | Claiming something got *better* (§workspace of this file) | Claiming something *runs* — that's a smoke test |
| **Fallback / recovery** | Explicit, per-case | A dependency is genuinely flaky | Masking a bug you haven't root-caused (ruleset §behavior) |

**The judgment the table can't encode: default to the fewest shapes.** Each one added is another
context window, another failure mode, another thing to debug at 3am. A single well-scoped skill beats a
four-agent pipeline that does the same work — ruleset §judgment's cutting rule applies to architecture, not
just features. If you cannot name what the shape buys, it is decoration.

---

## Divergent ideation (single-context, no-extra-calls) {#engineering/divergent}

Ruleset §behavior keeps the headline and points here. Moved out of the ruleset 2026-09-14 to keep it under
40,000 characters.

The no-extra-calls half of `UditAkhourii/adhd`, which is the parallel-divergence source spec. The parallel LLM calls are deliberately **not** taken, because those cost 5–10×. What remains are single-context reasoning moves that fight premature convergence. Premature convergence is the default failure: the agent commits to the first plausible answer because it is already in the buffer. These moves are weaker than true parallel isolation, since one context still anchors, but they are real. **Apply only at decision points:** architecture, storage or schema, API surface, naming, fuzzy bugs with no known root cause, migration or refactor shape. **Skip** for lookups, known-root-cause fixes, single-correct-answer work, and anything phrased "quick / standard / canonical / just". This must not fire per-keystroke.

- **Strip anchors before diverging.** Incidental implementation details in the problem statement, like the current stack or existing tool names, "infect all N branches" even though branches are isolated in the prompt. Before generating, identify and reframe. Strip implementation anchors while preserving genuine constraints: compliance, budget, physical limits, timing. Divergence works against the reframed problem. Convergence still judges against the original, because viability must account for real constraints. This step is optional, since some problems arrive anchor-free.
- **Generate before you judge.** Two postures, never blended. First list options with zero evaluation ("yes, and"), *then* switch to critic ("no, because"). Write all options down *before* evaluating any. That flush-to-buffer is the closest single-context substitute for isolation, because it stops you anchoring on option #1 while writing #2. Evaluating mid-generation strangles the range, since you converge on the first idea's shape.
- **Cycle frames, don't free-associate.** Re-pose the *whole* problem from distinct vantages, not variations of one: hardware constraints · regulator/auditor · adversary trying to break it · $0-1hr vs infinite-budget extremes · remove-the-load-bearing-assumption · 3am on-call · cross-domain transplant (biology/logistics/markets). Frames force distance a plain list can't. **A frame is a hat you wear, not a character you perform.** Use it for one more option, then drop it. If the output shows characters replying to each other, that is simulated deliberation, not divergence. One pass cannot split into a panel, however convincing the transcript reads.
- **Push past #3, then stop.** The first 2–3 options are the textbook answers a senior gives in 30s: correct, forgettable. Produce 5–6 before ranking any, because the interesting-but-viable ideas live in the awkward middle past #3. Stop at 5–6, or when new frames stop yielding new *mechanisms*, then converge. Diverging further to avoid deciding is procrastination, not ideation.
- **Name the trap mechanism, one line per trap.** Not "risky" but *why*: "global lock, dies past 3 writers." A tempting option with **3+ named traps is the false-economy pick**, the familiar answer that looks right. Surface the count, don't compress it.
- **Two picks, not one.** After ranking, name both the **safe recommendation** (highest fit) and the **★ novelty pick** (highest-novelty option that still ships). Say why the second isn't the default. Agents systematically under-weight novelty, so this re-rank is the value, and it survives without parallel branches. *Corollary: symmetric strength signal.* Before declaring two ideas equally viable, check whether they are genuinely distinct or just surface variations of the same mechanism. Group by angle, not by keywords. False equivalence strangles the shortlist.
- **Cluster by mechanism, not surface.** Group options by underlying angle, like "remove-the-server plays" or "cache-shaped plays", rather than by tech stack or feature. That reveals the *shape* of the design space, so the argument happens at the angle level.
- **Drill decisions one-at-a-time.** When a plan has multiple open choices, don't present them all at once. Present the *most important* unresolved decision, give the top 4 options with a stated preference, ask for the user's opinion, then stop and wait. Record the answer, then repeat with the next decision. This complements generate-before-you-judge. Divergent ideation maps the space, and this drills through it sequentially. (Harvested from `next-decision` pattern 2026-08-23.)
