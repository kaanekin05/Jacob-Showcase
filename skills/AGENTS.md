# SKILLS KNOWLEDGE BASE

**Location:** `/Users/kaan/Workspace/Jacob/skills/` · **Vendored skills:** 22 · **Updated:** 2026-10-01

Routing index for the skills **Jacob vendors**, grouped by family. `skills.lock.json` is
authoritative for versions and `update_policy`; this file is authoritative for **which skill answers
which task**.

**Plugins supply more, and they are not listed here.** On 2026-10-01 twenty-one skills were handed
back to upstream maintainers: the 15 wiki/obsidian skills now come from the `claude-obsidian` plugin,
the Claude API reference is a Claude Code built-in, and the six C# skills went to `dotnet-skills` —
a plugin that was itself uninstalled hours later, so **.NET craft is no longer reachable at all**.
Jacob stopped carrying copies it was not diverging from. See
`vault/wiki/meta/jacob-single-tool-cut.md`.

**There is no archive tier.** `archive/` was deleted 2026-10-01 after three months in which nothing
was restored from it. The names and sources of all 16 deactivated agents and skills live in
`vault/wiki/meta/archived-roster.md`, which also carries the `git show` command to recover any one.

## CONVENTIONS

- Skills use kebab-case naming; each has a `SKILL.md` plus optional `references/`, `scripts/`, `templates/`.
- **Prefer the Skill tool over reading `SKILL.md` directly.**
- `skills.lock.json` is the source of truth for installed versions and `update_policy`
  (`native` / `adapted` / `track` / `frozen`).
- CCGS-adapted skills carry a `## Jacob Ruleset Compliance` section binding them to `AGENTS.md`.

---

## 1. Unity & game dev (7)

| Task | Skill | Notes |
|------|-------|-------|
| Unity code standards, DI, events | `theone-unity-standards` | VContainer/SignalBus, TheOne.DI/Publisher |
| Drive the Unity Editor from chat | `unity-mcp-skill` | Coplay MCP (`mcpforunityserver==10.1.0`), spine-wired in `mcp/servers.json`. §context: only on an explicit ask to create/alter assets |
| Hand-edit Unity serialized YAML | `unity-yaml-editing` | `m_Script` GUID/fileID repair, Missing components, `.meta` safety, ProjectSettings patches, per-block scene/prefab merges. **Last resort** — the only thing that reads GUID wiring at all |
| Shader standards | `unity-shaders` | Shader Graph + HLSL, URP/HDRP, SRP Batcher, variant stripping |
| Subsystem design house rules | `unity-system-design` | Save/persistence, telemetry, animation FSM, AI/NPC, physics-as-gameplay, netcode |
| Game design documents | `game-design-docs` | 8-section GDD standard, testable acceptance criteria |
| Debug / trace a bug | `bug-trace` (switched off in `skillOverrides` since 2026-10-05) | Trailhead → fault site through event/message/DI/UniTask indirection. While it is off, `superpowers:systematic-debugging` covers root-cause work |
| Run a game's test or release build | `unity-build` | Chat wrapper over `scripts/unity-build/unity_build.py`. Runs the pipeline; writing Editor tooling is the `tools-programmer` agent |
| Pick the model for a plan task, or hand a 3+ file mechanical edit to a cheaper subagent | `cheap-model-handoff` | Haiku, Sonnet and Opus tiers for Claude subagents. Non-Claude workers are `orchestration` |


> **Two Editor routes, one vendored.** `unity-mcp-skill` (Coplay MCP) is the default and the only one
> Jacob vendors — native `mcp__CoplayMCP__*` tool calls, no shell round-trip. A second tool,
> **`unity-skills`** (Besty0728 REST, 785 skills on :8090–8100), is **package-owned and deliberately NOT
> vendored here**: the `com.besty.unity-skills` UPM package installs it into each Unity project's own
> `.claude/skills/` (gitignored there). Consequences, all intentional —
> its version always matches the installed server, it needs no re-vendoring, and it is *physically* scoped
> to projects that have the package, so no description tricks are needed to stop it competing with
> `unity-mcp-skill`. Reach for it only inside those projects and only when the task needs its governance
> layer: a `?mode=dryRun`/`?mode=plan` rehearsal, per-task rollback surviving a Domain Reload, a JSONL
> audit trail, or a `POST /skills/batch` transaction. **Never install it to a global tool path**
> (`~/.claude/skills`) — that is a spine symlink, and its sync/uninstall
> writes and deletes straight into this repo (§workspace). Operating notes live with the per-project copy.

## 2. C# / .NET craft — REMOVED

Jacob vendored a curated five until 2026-10-01, handed them to the `dotnet-skills` plugin, then
uninstalled that plugin the same day. Its 35 skills and 7 agents cover Akka.NET, Aspire, EF Core,
Blazor and Playwright, none of which touch Unity. **There is no .NET skill layer in Jacob.** General
C# style for Unity lives in `theone-unity-standards` and ruleset §naming. The ones Jacob used to carry
were `csharp-coding-standards`, `csharp-type-design-performance`, `csharp-concurrency-patterns`,
`serialization`, `r3-reactive-extensions` and `csharp-api-design`.

## 3. Review & engineering process (6)

| Task | Skill | Used by |
|------|-------|---------|
| Code review vs Jacob standards | `code-review-standards` | `lead-programmer` |
| GDD completeness / implementability review | `design-review` | `systems-designer` |
| Technical-debt register + `// SHORTCUT:` harvest | `tech-debt` | `lead-programmer` |
| Whole-codebase structural refactor, run end to end (user-typed only) | `untangle-codebase` | `lead-programmer` |
| LLM coding discipline (full text behind §behavior) | `karpathy-guidelines` | — |

## 4. Jacob's own tooling (4)

| Task | Skill | Notes |
|------|-------|-------|
| Author or sharpen a skill/agent | `anthropic-skills:skill-creator` (skills), `plugin-dev:agent-development` (agents) | Anthropic's own authoring tools. They stop at the file; the lock/bootstrap/doctor wiring is the Jacob wiring checklist in `rules/Jacob_Engineering.md` §engineering/authoring |
| Discover a published skill, agent, plugin, or MCP server | `find-skills` | **Discovery only.** Four rungs: skills.sh catalog, `gh search repos/code`, awesome-list directories, WebSearch. Installing via `npx skills add` writes per-tool copies — forbidden by §workspace; route adoption through `/triage-repo` then `anthropic-skills:skill-creator` |
| Weekly upstream drift report | `check-updates` | Runs `scripts/check-updates.sh`; report-only, human-gated apply |


## 5. Knowledge vault + Obsidian syntax — PLUGIN, not vendored

Vault root (`VAULT_PATH`): `~/Workspace/Jacob/vault`. Resolve every vault path against it (§vault).

All 15 come from the `claude-obsidian` plugin as of 2026-10-01: `wiki`, `wiki-query`,
`wiki-retrieve`, `wiki-ingest`, `wiki-lint`, `wiki-fold`, `wiki-mode`, `wiki-cli`, `canvas`, `save`,
`autoresearch`, `think`, `defuddle`, `obsidian-markdown`, `obsidian-bases`. Invoke them by plain
name; Jacob carries no copy and no lock entry.

**The pin is load-bearing.** `CLAUDE_OBSIDIAN_VAULT` in `~/.claude/settings.json` `env` is what makes
them find Jacob's vault from a sibling project directory — implicit discovery finds nothing there and
the core fails closed. `scripts/bootstrap.sh` writes it, `scripts/doctor.sh` Check 13 fails without it.

**Jacob still owns the surrounding pieces:** the 2 agents (`wiki-ingest`, `wiki-lint`). The 4
command wrappers (`wiki`, `save`, `autoresearch`, `canvas`) were removed on 2026-10-05; they
duplicated the plugin's skills in the listing. Type `/claude-obsidian:<name>` instead. `agents/wiki-lint.md`
carries the inline-vs-written-report scoping the skill does not. Detail: `vault/MAINTENANCE.md`.

> `wiki-retrieve` (index build) and `wiki-query` (read-only consumer) are a **layered pair**, not
> duplicates — do not merge them.

## 6. Design & visual output (6)

| Task | Skill |
|------|-------|
| UI/UX design intelligence — palettes, type pairings, UX rules, stacks | `ui-ux-pro-max` |
| Audit existing web code (HTML/CSS/JSX) for accessibility — names, keyboard, focus, forms | `fixing-accessibility` |
| Audit web animation cost — layout thrash, compositor props, scroll-linked motion, blur | `fixing-motion-performance` |
| Place Unity UI from a mockup or Figma export by measuring, not eyeballing | `ui-from-reference` |
| Architecture / workflow / sequence diagrams as standalone HTML | `archify` |
| Turn existing art into game sprites (cutout, slicing, video loops, recolor) and draw small pixel art with Claude. GPT/Grok generation is off by user choice. Runtime lives outside Jacob at `~/.local/share/sprite-gen`. Packing finished sprites in Unity is `manage-sprite-atlas` | `sprite-gen` |

> `ui-ux-pro-max` has **zero** Unity coverage — it is platform-neutral plus web. The Unity translation
> note lives in `agents/unity-ui-specialist.md`, and its hardcoded `scripts/search.py` path is why this
> skill stays vendored rather than plugin-installed. `archify` is `adapted`: its upstream
> update-notifier is stripped on every re-vendor, per `skills.lock.json` `local_mods`.
> `ui-ux-pro-max` looks rules up and picks designs. The two `fixing-*` skills audit a file that
> already exists. All three are web or platform-neutral; none applies to Unity UI. Both `fixing-*`
> skills are verbatim `track` copies from `ibelick/ui-skills`.

## 7. Host / IDE integration (2)

| Task | Skill |
|------|-------|
| Orca worktrees, terminals, embedded browser | `orca-cli` |
| Multi-agent coordination — task DAGs, dispatch, waits | `orchestration` |

> Boundary: `orca-cli` for ownership handoffs and ordinary terminal/worktree control;
> `orchestration` only when coordination *state* matters.

## 8. Writing (1)

| Task | Skill |
|------|-------|
| Sharpen a draft / detect AI-slop patterns | `no-ai-slop` |

> The Claude API reference was vendored as `claude-api-migration` until 2026-10-01. Its body diffed
> zero lines against upstream and Claude Code ships that skill built in, so the copy went.

> `no-ai-slop` edits **user drafts**. §behavior/output remains the sole home for Jacob's own response shape.

---

## ANTI-PATTERNS

- **DO NOT** install skills through any tool's own marketplace or `npx skills add` — single-source
  breaks (§workspace). Vendor once in Jacob; `bootstrap.sh` propagates.
- **DO NOT** load an orchestrator skill tree blindly — invoke the specific sub-skill by name.
- **DO NOT** invoke a CCGS-adapted workflow skill without its `## Jacob Ruleset Compliance` section.
- **DO NOT** merge two `track` skills. Merging converts them to `adapted`, which means a manual
  three-way reconcile on every drift report, forever.
