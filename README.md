# Jacob

Jacob is how I bring AI into my everyday work as a Unity game developer. It is a ruleset, a team of agents, and a set of skills that Claude Code loads in every session. The idea is simple. My game-dev judgment is written down as rules, and every AI agent I work with is held to them.

This is a one-time reading copy of my personal workspace. Some parts are left out on purpose. The last section says what and why.

## The idea

A general AI model writes plausible Unity code. Plausible is not shippable. It reaches for LINQ in `Update()`, calls `FindObjectOfType()` in the game loop, and puts game logic inside a `MonoBehaviour`. Code review catches that late. Jacob catches it early. It gives the model the standards a senior Unity engineer applies, plus the judgment about whether a feature should be built at all.

Jacob has two halves held to one standard:

- **Game development.** Zero-allocation runtime code, strict MVC, data-driven tuning, frame and memory budgets with a named measurement, and the target platform treated as an architectural constraint.
- **AI engineering.** Routing, context budgets, agent boundaries, evals, and health checks. These make the agents follow the game-dev rules reliably, not occasionally.

## Where to look

| To see | Read |
|---|---|
| The rules the AI is held to | `AGENTS.md`. Start with §performance, §architecture and §frameworks. §judgment is the "should this exist at all" half. |
| Library-specific traps (UniTask, VContainer, Addressables, MessagePipe and more) | `rules/Jacob_Framework_Rules.md` |
| A game-dev team as agents | `agents/`. 16 Unity and game-design agents, each with explicit boundaries. For example, `unity-reviewer` reviews code against the ruleset, `unity-performance` audits hot paths, and `systems-designer` turns a mechanic into numbers. The routing index is `agents/AGENTS.md`. |
| Game feel as a spec, not a polish pass | `skills/unity-system-design/SKILL.md`, section 7. Hitstop, screen shake and cancel windows are numbers in data that a designer can tune. |
| AI that ships builds | `scripts/unity-build/` and `skills/unity-build/`. It builds Unity games from chat and runs guards that stop a bad release, such as forbidden defines and values that must not change. Then it uploads to TestFlight and Google Drive. It has 312 tests that run with no network. |
| Evidence that the routing works | `scripts/evals/`. 68 trigger cases check that a prompt reaches the right skill or agent. 9 gate cases and a response-quality set scored against a rubric sit beside them. |
| How it stays consistent | `scripts/doctor.sh`. 24 checks run before every commit. Every section reference must resolve, the ruleset must stay under its size budget, and vendored skills must match their locked hashes. |
| How new tools get adopted or turned down | `commands/triage-repo.md`, and the `WATCHED_REPOS` list in `scripts/check-updates.sh`. A section below explains it. |
| Self-learning with a bar | `scripts/hooks/create_bar.py` and `scripts/hooks/create-bar-rubric.md`. The autoharness plugin turns lessons from my sessions into skills. Before it can add a new one, an LLM judge checks it against a bar written in my words: a skill must replace context I would otherwise explain again every time. Edits and merges stay automatic. `scripts/evals/create-bar-cases.jsonl` holds 20 labelled cases. It is new, and its allow/deny ratio is still being measured. |
| How the agents are told to write | `rules/output-styles/jacob-plain.md` |

## What's inside

| Folder | What it holds |
|---|---|
| `AGENTS.md` | The ruleset Claude Code loads every turn. It keeps invariants and indexes only, and points at the detail. `CLAUDE.md` is a symlink to it. |
| `rules/` | The detail behind the ruleset, read only when a task needs it: per-library framework rules, Jacob's layout and wiring, how its tooling is built, the model register, and the output style. |
| `agents/` | 19 subagents, one Markdown file each. They fire on their own when a task matches their description. |
| `skills/` | 45 skills. 9 are written here, 18 were learned from my sessions by the autoharness plugin, and 18 are vendored from upstream repos. `skills/skills.lock.json` records each one's version and update policy. `skills/AGENTS.md` says which skill answers which task. |
| `commands/` | 6 slash commands that run only when I type them. |
| `mods/` | Claude Code mods. `mods/quick-bar/` is a side pane with a context meter and one-click buttons for frequent commands. |
| `mcp/` | `mcp/servers.json`, the MCP servers every project sees. Today that is the Unity Editor bridge. |
| `scripts/` | Setup, the health check, the hooks, the build pipeline, session tooling, and the evals. |

### Agents

- **Unity implementers.** These write code and return a diff for review: `unity-specialist` (the default writer), `gameplay-programmer`, `unity-ui-specialist`, `unity-addressables-specialist`, `unity-dots-specialist`, `unity-shader-specialist`, `tools-programmer`, and `technical-artist`.
- **Structure, testing, and measurement.** `lead-programmer` plans structure across files. `qa-tester` writes tests and bug reports. `performance-analyst` takes and reads Profiler captures.
- **Read-only reviewers.** `unity-reviewer` checks naming and MVC layering. `unity-performance` audits hot paths. `verifier` audits a staged diff before commit and returns a ship-or-hold verdict.
- **Design.** `game-designer` shapes loops and mechanics. `systems-designer` turns a mechanic into exact numbers. `level-designer` builds mobile puzzle levels.
- **Knowledge vault.** `wiki-ingest` and `wiki-lint` maintain my Obsidian vault.

### Skills

- **Unity and game development.** `unity-system-design`, `unity-shaders`, `unity-mcp-skill`, `unity-yaml-editing`, `game-design-docs`, `ui-from-reference`, `sprite-gen`, `localization`, `manage-sprite-atlas`, `optimize-audio`, `optimize-text-mesh-pro`, and `bug-trace`.
- **Builds, devices, and release.** `unity-build`, `unity-batchmode-run`, `android-build-size-diff`, `device-test-handoff`, `dependency-upgrade-policy`, `rclone-google-drive`, `unity-dead-script-refs`, `simple-localization-csv-rows`, and `video-frame-timing`.
- **Review and engineering process.** `code-review-standards`, `design-review`, `tech-debt`, `untangle-codebase`, `cheap-model-handoff`, and `unity-parallel-subagents`.
- **Git and session habits.** `git-workflow`, `git-history-search`, `secret-handling`, `verify-negative-search`, `plain-decision-questions`, `long-work-ledger`, `loose-ends-sweep`, and `fill-pasted-template`.
- **Jacob's own tooling.** `check-updates`, `writing-for-agents`, and `claude-code-plugin-mod-not-loaded`.
- **Web, hosting, and writing.** `ui-ux-pro-max`, `fixing-accessibility`, `fixing-motion-performance`, `scrapling-official`, `orca-cli`, `orchestration`, and `no-ai-slop`.

### Commands

| Command | What it does |
|---|---|
| `/triage-repo` | Evaluates an external repo for adoption. Stops for approval before touching any file. |
| `/commit-slices` | Splits a dirty tree into vertical-slice commits. Shows the slices first and never pushes. |
| `/pm-check` | Checks a PM's task list against the code, with one verdict and a `file:line` per bullet. |
| `/session-finalizer` | Lists unanswered questions and unfinished steps across past sessions. |
| `/handoff-brief` | Writes a brief for a fresh session and replies with one line to paste. |
| `/new-project` | Writes a project `CLAUDE.md` for a Unity repo from a template. |

### Hooks

Hooks are the only part the harness runs every time, without the model deciding to.

| Hook | What it does |
|---|---|
| Pre-commit gate | Runs `scripts/sync-autoharness-lock.sh`, then `scripts/doctor.sh`. A failing check blocks the commit. |
| `scripts/hooks/create_bar.py` | Judges each new learned skill before autoharness can add it, and denies one that is only a sentence I could just say. |
| `scripts/statusline-context.sh` | Shows a context-window meter in the status line. |
| quick-bar mod | Keeps the side pane's meter and buttons live. |

## How Jacob decides what to adopt

New AI tooling shows up every week, and most of it would make Jacob worse. `/triage-repo <url>` decides. It reads an external repo as untrusted data and gives each part one verdict: vendor it, harvest the idea, replace an existing piece, watch it, or reject it. It stops for my approval before it touches a file.

The part I care about is that the rubric is held to evidence, including evidence about itself.

- **The incumbent has to compete.** If Jacob already has something similar, the triage compares the two in both directions. "We already have one" is not a finding. An incumbent that loses gets replaced.
- **Harvesting is not the safe default.** Rewriting someone's idea in my own words looks cheap. In practice I own that prose forever and never get upstream's fixes. So a harvest verdict has to explain why the code itself could not be taken.
- **The rubric was audited, and then fixed.** The first version weighed one benefit against four costs. Across the first 28 repos it said "vendor" zero times. Over the same period, 34 of Jacob's 42 installed skills had come from outside. It now weighs four benefits against four costs.
- **A cost counts only after its cheapest fix.** Pinning a release fixes release churn. A missing login is a task for the day I use the tool, not a reason to say no. `sprite-gen` first came back "watch only" for exactly those reasons, and the recheck vendored it.
- **Every verdict is pinned with its reason.** A reject leaves no trace in the repo, so the next time that repo comes up, the whole triage gets paid for again. `scripts/check-updates.sh` pins 43 repos, each with its verdict, the conflict that decided it, and every re-review since.

## How it runs on my machine

Claude Code reads Jacob through symlinks. `~/.claude/CLAUDE.md` points at `AGENTS.md`, and `agents/`, `skills/` and `commands/` are linked the same way. That leaves exactly one place to edit. `scripts/bootstrap.sh` rebuilds those links after a clone.

The Superpowers plugin runs the working process: brainstorm, plan, build, verify. Jacob owns the domain rules. `AGENTS.md` §behavior/superpowers draws the line between them.

This copy is not meant to run anywhere else. Paths under `/Users/kaan` are left as they are.

## What this copy leaves out

- `references/`. The mirrored Unity manual and the docs for paid Asset Store packages (Odin, Feel, RayFire, SRDebugger). They are licensed for my use, not for redistribution. They are also about 140 MB.
- `vault/`. My Obsidian knowledge base.
- `.memsearch/`, `memory/` and `handoffs/`. Session journals and working notes.
- `docs/`. Design specs that contain private build details.
- The evidence and ledger files that the autoharness self-learning plugin writes next to each skill. They quote real sessions.
- Three vendored skills, for licensing reasons. `theone-unity-standards` came from a repo that was later withdrawn and never carried a license. `karpathy-guidelines` says "MIT" in its upstream README, but upstream publishes no license file or copyright line to pass on. `find-skills` has no confirmed upstream.

When `AGENTS.md` or a skill mentions one of these, the file exists in the private version only.

Project names in the build pipeline are replaced with code names, Amber through Fern. Real identifiers in the build configs and tests are replaced with fake values of the same shape. That covers the Apple team ID, the test device ID, the Drive folder IDs, an update-server host, and a person's name. The tests pass with the fake values.

Every vendored skill folder carries its upstream license file. `agents/LICENSE` covers the agents adapted from Claude-Code-Game-Studios and claude-obsidian.
