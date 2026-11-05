# AGENTS KNOWLEDGE BASE

**Generated:** 2026-06-11 · **Updated:** 2026-09-14
**Location:** `/Users/kaan/Workspace/Jacob/agents/`

## OVERVIEW

Unity game-dev personas (CCGS-adapted) + three vault/process agents (`verifier`, `wiki-ingest`, `wiki-lint`), all at top level. `skill-reviewer` was deleted 2026-10-04; use Anthropic's `plugin-dev:skill-reviewer`. (8 pure design/production/art roles were **archived to `archive/agents/`** 2026-07-12; `game-designer` and `level-designer` were restored 2026-09-14 for level work that may ship — see the Archived section. The **6 curated .NET specialist agents were archived to `archive/agents/` 2026-07-21** as out of scope for Unity — restore via `git mv`. The full 16-agent upstream .NET set was **removed** 2026-07-12 — see ANTI-PATTERNS.)

## STRUCTURE

```
agents/
├── # Unity / Game-Dev (CCGS-adapted)
├── unity-specialist.md              # Core Unity engine implementer
├── unity-addressables-specialist.md # Addressables strategy & memory management
├── unity-dots-specialist.md         # ECS, Jobs, Burst, hybrid renderer
├── unity-shader-specialist.md       # Shaders, VFX, GPU profiling
├── unity-ui-specialist.md           # UI systems (UGUI/UI Toolkit per project)
├── unity-performance.md             # Hot-path code review (GC, caching, pooling)
├── unity-reviewer.md                # Read-only code quality reviewer
├── gameplay-programmer.md           # Gameplay mechanics & systems
├── tools-programmer.md              # Editor tools, debug, pipeline
├── lead-programmer.md               # Code architecture, standards, review
├── technical-artist.md              # Shaders, VFX, rendering optimization, art pipeline
├── performance-analyst.md           # System-level profiling & benchmarking
├── qa-tester.md                     # Test scaffolds & bug reporting
│
├── # Production & Design (active — the pure design/production roles are archived, see below)
├── systems-designer.md              # Formulas, math, interaction matrices, balance
├── game-designer.md                 # Core loops, mechanics, player-facing rules
├── level-designer.md                # Mobile puzzle levels, difficulty curve, solvability
│
└── # Vault / Process
    ├── verifier.md                  # Pre-commit staged-diff audit (BLOCKER/HIGH/MEDIUM/LOW)
    ├── wiki-ingest.md               # Parallel batch ingestion into the Obsidian vault
    └── wiki-lint.md                 # Wiki health check (orphans, dead links, stale claims)
```

(The 6 curated .NET specialist agents that previously sat here were archived 2026-07-21 — see ".NET personas — archived" below.)

## WHERE TO LOOK — Unity / Game-Dev

| Task | Agent | Notes |
|------|-------|-------|
| Unity engine patterns, APIs, optimization | `unity-specialist` | MonoBehaviour vs DOTS, subsystems, best practices |
| Addressables loading, groups, memory, CDN | `unity-addressables-specialist` | Strategy beyond binary rules |
| ECS, Jobs, Burst, hybrid renderer | `unity-dots-specialist` | Performance-critical thousands-of-entities systems |
| Shader Graph, HLSL, VFX, SRP Batcher | `unity-shader-specialist` | Replaces `unity-shaders` skill |
| UI system selection per project context | `unity-ui-specialist` | Replaces "UGUI only" rule |
| Hot-path code review (GC, caching, pooling) | `unity-performance` | Frame-by-frame code audit |
| Read-only code quality review | `unity-reviewer` | Naming, MVC, decoupling, framework rules |
| Gameplay mechanics implementation | `gameplay-programmer` | Feature code, state machines, input |
| Editor tools, debug utilities, pipeline | `tools-programmer` | Custom inspectors, build tools |
| Code architecture, standards enforcement | `lead-programmer` | Primary code review gate |
| Shaders, VFX, rendering optimization | `technical-artist` | Art-to-engine bridge |
| System-level profiling, benchmarks | `performance-analyst` | Profiler analysis, regression detection |
| Test scaffolds, bug reports | `qa-tester` | EditMode/PlayMode test patterns |
| Formulas, math, interaction matrices, balance | `systems-designer` | Detailed rule specification (engineering-adjacent — kept active) |
| Core loops, mechanics, "how does the game work" | `game-designer` | Writes specs, not code; restored 2026-09-14 |
| Puzzle level layouts, difficulty curve, solvability | `level-designer` | Casual mobile puzzle (iOS/Android); specs only, `unity-specialist` builds; restored 2026-09-14 |

### Deleted design/production roles (archived 2026-07-12, deleted 2026-10-01)

`creative-director`, `art-director`, `live-ops-designer`, `ux-designer`, `accessibility-specialist`, `producer` — pure design/production/art roles a Unity engineer rarely invokes directly. They sat in an `archive/` tier for three months and nothing was ever restored from it, so the tier is gone and so are the files. **Do not treat their absence as drift, and do not re-author them here.** Their roles and their CCGS source are recorded in `vault/wiki/meta/archived-roster.md`, which also carries the `git show` command to recover one. (`game-designer` and `level-designer` were restored to the active roster 2026-09-14 and are unaffected.)

## WHERE TO LOOK — Vault / Process

| Task | Agent | Notes |
|------|-------|-------|
| Pre-commit audit of a staged diff | `verifier` | Dispatched after staging, before commit; four-tier findings (BLOCKER/HIGH/MEDIUM/LOW) with `file:line` |
| Batch-ingest multiple sources into the vault | `wiki-ingest` | Parallel; triggers on "ingest all" / "batch ingest" |
| Wiki health check | `wiki-lint` | Orphans, dead wikilinks, stale claims, frontmatter gaps |
| Review an existing skill | `plugin-dev:skill-reviewer` | Anthropic's plugin agent, not Jacob's. Read-only, severity-tiered findings. Ignore its "description over 500 chars" finding: the spec cap is 1,024. Authoring is `anthropic-skills:skill-creator` |

## .NET personas — deleted

The 6 curated .NET specialist agents (`akka-net-specialist`, `docfx-specialist`, `dotnet-benchmark-designer`,
`dotnet-concurrency-specialist`, `dotnet-performance-analyst`, `roslyn-incremental-generator-specialist`) were
archived 2026-07-21 as out of scope for a Unity C# gameplay workspace, then **deleted 2026-10-01** when that
became permanent — Jacob is Unity-only. The `dotnet-skills` plugin carried them for a day and was
uninstalled 2026-10-01 too, so there is **no .NET routing in Jacob at all**. **No restore path.**
A .NET task means installing that plugin again, deliberately, as a new decision.

## CONVENTIONS

- Each agent is a `.md` file with persona definition and routing instructions.
- Every top-level agent carries a `model:` per `rules/MODEL_POLICY.md` (validated by `scripts/doctor.sh` Check 7).
- Unity/game-dev agents are adapted from CCGS (Donchitos/Claude-Code-Game-Studios, MIT) with `## Jacob Ruleset Compliance` sections.
- Agents are invoked via `task(subagent_type="<name>")` or similar delegation.
- **Agents auto-dispatch** on `description:` match, per ruleset §invocation. The model fires them without
  asking. That makes `description:` the whole routing contract, so every agent here carries either
  `Use when ...`, `Triggers: ...`, or an `<example>` block. `scripts/doctor.sh` Check 12 warns on one
  that does not.
- **Write a differentiator into every description.** Nine Unity agents overlap in domain. Each
  description names which sibling owns the adjacent work (`unity-specialist` is the default writer;
  UI, Addressables, DOTS and shaders each carve out their slice). Without it they all match one task.
- **The nine code-writing implementers run `opus`**, not `sonnet` (changed 2026-09-28 when
  auto-dispatch landed — rationale in `rules/MODEL_POLICY.md`). `wiki-ingest` stays `sonnet`.
- **Writers carry a `## Return contract`** section and `skills: ["theone-unity-standards"]`. The
  contract makes them return a diff instead of a prose summary, so the dispatching thread can review
  the code against §code. The `skills:` preload injects the governing standard at subagent startup
  rather than restating it in the body (`rules/Jacob_Engineering.md` §engineering/authoring).

## ANTI-PATTERNS

- **DO NOT** re-add the removed upstream .NET agents (ASP.NET/Blazor/MAUI/Uno/cloud/security/docs/architect/testing).
  They were dropped 2026-07-12 as out of scope for a Unity C# gameplay workspace, alongside the dotnet-skills prune.
- **DO NOT** treat the 6 curated .NET agents' absence as drift, and **do not re-author them here**. They were
  archived 2026-07-21 and deleted 2026-10-01. Jacob has no .NET layer by design.
- **DO NOT** invoke CCGS-adapted agents without respecting `AGENTS.md` — every Unity agent has a
  compliance section that enforces §code rules.
