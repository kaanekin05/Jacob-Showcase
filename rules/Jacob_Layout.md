# Jacob — Layout & Wiring (read before touching the spine)

**Gate (ruleset §spine).** Read the relevant block here *before* changing Jacob's own wiring: the symlink
spine, `scripts/bootstrap.sh`, `scripts/doctor.sh`, `skills.lock.json`, `mcp/servers.json`, model config, plugin
registration, or the directory layout. The master ruleset keeps only the headline; the mechanics and
the inventory live here, because they are relevant to a small fraction of turns and would otherwise
cost every turn (ruleset §agent-engineering — context is the scarce resource).

This file is **operational state**: it decays if the repo changes and the file doesn't. `scripts/doctor.sh`
Check 2 resolves every backticked workspace path cited here, so a stale path fails the health check.

---

## Directory map (actual layout) {#layout/directory-map}

```
Jacob/
├── AGENTS.md                 # Master ruleset — always-resident rules only (real file)
├── CLAUDE.md                 # → AGENTS.md (relative symlink)
├── README.md
├── rules/                    # Jacob's own gated governance docs (one gate away from the ruleset)
│   ├── Jacob_Layout.md       # This file — layout, wiring, inventory
│   ├── Jacob_Framework_Rules.md  # Per-library strict rules (ruleset §frameworks detail)
│   ├── Jacob_Engineering.md  # Tooling, model config, governance conventions (ruleset §agent-engineering detail)
│   ├── MODEL_POLICY.md       # Reference register of model IDs per CLI
│   ├── editorconfig.template # C# .editorconfig to copy into Unity projects
│   ├── project-CLAUDE.template.md  # Project CLAUDE.md template; `/new-project` fills it
│   ├── RTK.md               # `rtk` command reference; ruleset §shell imports it as @rules/RTK.md.
│   │                         # Moved here from ~/.claude/ 2026-09-29 — the bare @RTK.md import
│   │                         # resolved from the Jacob root and so loaded in no tool.
│   └── output-styles/        # Claude-only prompt-block voice styles. jacob-plain.md is §behavior's
│                             # canonical home for register + answer shape (doctor Check 15).
├── references/               # Unity-ecosystem library reference (Markdown here is Git LFS)
│   ├── AGENTS.md             # Reading index for the reference docs
│   ├── Unity_Documentation/  # 18 Part files (~5–12 MB each); Part_01 = TOC for all parts
│   ├── DOTween_Documentation.md           (~140 KB)
│   ├── Feel_Documentation.md              (~407 KB)
│   ├── Rayfire_Documentation.md           (~242 KB)
│   ├── SRDebugger_Documentation.md        (~29 KB)
│   ├── UniTask_Documentation.md           (~53 KB)
│   ├── VContainer_Documentation.md        (~103 KB)
│   ├── MessagePipe_Documentation.md       (~49 KB)
│   └── Odin_Documentation.md              (~138 MB — Odin Inspector; never read whole)
├── agents/                   # Personas — ALL top-level (no nested set). Index: agents/AGENTS.md
├── commands/                 # 6 slash-command templates (Jacob-native): triage-repo, new-project, handoff-brief,
│                             # commit-slices, pm-check, session-finalizer. The 4 claude-obsidian wrappers were
│                             # removed 2026-10-05 (plugin skills cover them)
├── docs/superpowers/         # Specs and plans written by the Superpowers workflow (specs/, plans/)
├── handoffs/                 # Dated work orders for an orchestrating agent. Each opens with its status
├── skills/                   # ALL skills flat at top-level — no nested skills/skills/
│   ├── AGENTS.md             # Routing index: which skill answers which task
│   ├── skills.lock.json      # Source of truth for installed versions (every skill entry + vendored tools)
│   ├── karpathy-guidelines/  # LLM coding-discipline guidelines (vendored, MIT)
│   ├── theone-unity-standards/  # VContainer/SignalBus + TheOne.DI/Publisher
│                             # The 15 wiki/obsidian skills are NOT here — the
│                             # claude-obsidian plugin owns them since 2026-10-01
├── mods/                     # Claude Code mods (plugins of function hooks), one folder each. Loaded in
│   │                         # place through env.CLAUDE_CODE_PLUGIN_DIRS, which bootstrap writes.
│   └── quick-bar/            # Side pane: context meter + buttons that fill the prompt with a command
├── mcp/                      # Canonical tool-neutral MCP server definitions
│   └── servers.json          # Globally-useful MCP servers (bootstrap merges into each tool)
├── scripts/                  # Everything executable Jacob owns
│   ├── bootstrap.sh          # Idempotent wiring: symlinks Jacob → Claude Code (--dry-run / --verify / --uninstall)
│   ├── doctor.sh             # Self-validation: lock↔disk, doc refs, wiring, memory index/links, §-refs (FAIL = non-zero exit)
│   ├── check-updates.sh      # Read-only weekly drift report (skills, plugins, MCP, models)
│   ├── backup-transcripts.sh # rsync Claude transcripts out from under the 30-day prune
│   ├── vault-lag.sh          # Which vault pages are older than the code they describe
│   ├── vault-suggest-links.py# Vault page PAIRS that look related but share no [[link]] — the
│   │                         # half wiki-lint can't do (it finds one-sided orphans). Manual.
│   ├── unity-build/          # Build pipeline for Unity games: unity_build.py + games/<game>.json, one per game.
│   │                         # Run it directly; the unity-build skill only adds the chat steps
│   ├── memsearch/            # summarize.txt redaction prompt + reindex.sh
│   └── evals/                # Behavior checks for §agent-engineering: trigger-cases.jsonl, overlap-audit.py,
│                             # answer-shape.py, register-check.py, response-quality/
├── vault/                    # Persistent LLM wiki DATA ONLY (ruleset §vault) — wiki/ .raw/ .vault-meta/
│                             # .obsidian/ _templates/. The product is a plugin and lives in Claude's
│                             # plugin cache; 2.x refuses to treat its own install tree as a vault
│                             # (PLUGIN_ROOT_IS_NOT_VAULT). Pinned by CLAUDE_OBSIDIAN_VAULT.
├── memory/                   # Backup COPIES of Claude Code's per-project auto-memory, one folder
│                             # per project. Not the live store — Claude reads and writes
│                             # ~/.claude/projects/<slug>/memory/, which is outside every repo and
│                             # therefore the one store a clone cannot restore (§workspace suitcase). Copies
│                             # go stale; re-copy rather than editing here, and wire nothing to read
│                             # from it. Memory, not vault (§vault). Scan for credentials before
│                             # committing.
                              # (archive/ deleted 2026-10-01 — names + sources only, in
                              #  vault/wiki/meta/archived-roster.md)
```

**`skills/synced/` is not Jacob's** (2026-09-25). Claude Code writes marketplace and built-in skill
payloads there, under UUID-named folders, because `~/.claude/skills` symlinks into this repo — the
§workspace "symlinks point both ways" hazard, seen from the other side. It is gitignored and **excluded from
two `doctor.sh` checks**: the skills-folder-versus-lock check, and the hidden-payload check, which
otherwise fires on all ~216 files inside it. Deleting the folder does not help; it regenerates on
the next sync.

Root holds only entry points (`AGENTS.md`, `CLAUDE.md`, `README.md`) plus dotfiles. Tool-owned state
stays hidden and untracked: `.memsearch/` (journals are tracked) and `.install-state.json`.
`vendor/` is gone — nothing is vendored as product code since 2026-10-01.

### Inventory notes

- **`dotnet-skills` is gone entirely (2026-10-01).** Jacob carried a curated 5-skill Unity/C# subset,
  handed it back to the plugin that morning, then uninstalled the plugin the same day: 35 skills and
  7 agents with no Unity contact. Jacob now has **no .NET layer**. The wshaddix `agents/agents/` +
  `commands/` set went 2026-07-12, `csharp-api-design` was archived earlier. Reinstating .NET support
  is a fresh decision, not a restore.
- The 6 curated .NET agent personas (akka-net, docfx, benchmark-designer, concurrency,
  dotnet-performance-analyst, roslyn) were archived 2026-07-21 and deleted 2026-10-01 — out of scope
  for Unity work, with no restore path.
- The broad `game-developer` / `game-development-sickn33` routers were archived 2026-07-12 and
  deleted 2026-09-14 after being mined — use the specific Unity agents instead.
- Removal history + the retirement of the doubly-nested convention: `vault/wiki/meta/jacob-ruleset-archive.md` §archive/directory-map.
  The old INTEGRATIONS.md ledger was deleted 2026-07-21; its content folded into that archive and `skills/skills.lock.json`.

### Retired layout conventions (must not reappear)

`agents/agents/`, `skills/skills/`, `commands/commands/`, `dotnet-skills-master/` — the doubly-nested
convention is retired. The pre-2026-09-14 top-level names are retired too: `Documentations/`,
`obsidian-vault/`, `claude-obsidian/`, `tools/`, `evals/`, `output-styles/`, and root-level
`JacobRulesetMASTER.md`, `MODEL_POLICY.md`, `doctor.sh`. `scripts/doctor.sh` Check 2b asserts all of
these stay absent; if one reappears on disk, move it into the current layout.

---

## Cross-tool spine {#layout/spine}

Jacob holds the only editable copies; each tool is wired via thin **symlink adapters** through the
`AGENTS.md` format. **Edit Jacob, never the per-tool copies** (ruleset §workspace).

**The tools that write back through the symlink** (ruleset §workspace, "the symlinks point both ways"): Unity's
`UnitySkills`, Coplay's configurator, and any plugin marketplace. Each sees `~/.claude/skills/<name>`
and reads it as *installed*, because the symlink makes it exist, so its sync/install/uninstall writes or
**deletes** straight into this repo. Turn auto-sync off per project, and record any local change to a
vendored file in `skills.lock.json` under `local_mods` so it survives a clobber. `skills/synced/` is the
same hazard seen from the other side — see *Inventory notes* above.

**Claude Code is the only consumer (2026-10-01).** It is *full-tier*: rules, skills, commands and agents.
opencode and Antigravity CLI were the other two until that date; their adapters are deleted and
`scripts/bootstrap.sh` retires their symlinks on sight. When wiring a **new** tool, classify its harness tier
first — do not assume full parity.

The symlink paths of the retired tools, the tier essay, and the symlink-ceiling /
generate-and-validate rule: `vault/wiki/meta/jacob-ruleset-archive.md` §archive/workspace.

`scripts/bootstrap.sh` re-materializes everything machine-specific on clone (symlink spine, per-tool MCP
config, `settings.json`, the doctor pre-commit hook, vendored venvs, the memsearch redaction prompt).
It does **not** rebuild Claude model config — see *Model config* below. `scripts/bootstrap.sh --verify` checks wiring;
`--uninstall` removes it.

**memsearch redaction prompt (2026-08-30).** `.memsearch/memory/*.md` is git-tracked, and it is
written by an LLM summarizing raw transcripts — so a pasted credential would land in the repo.
Jacob owns the summarizer prompt at `scripts/memsearch/summarize.txt` (drop secrets, honour `<private>`
markers); memsearch reads it by ABSOLUTE path from `~/.memsearch/config.toml`, which is machine-local and
does not survive a clone. Same shape as the MCP merge in §context — canonical source in git, user-level target so
every project inherits it. bootstrap refuses to clobber a `prompts.summarize` pointing anywhere else.
The failure mode this guards is silent: unwired, memsearch falls back to the upstream prompt with no error.
Rebuilding the index (both the journals and `vault/wiki/`) is `scripts/memsearch/reindex.sh`.

**Transcript archive (2026-09-07).** The journals are a LOSSY layer. Each entry carries a
`transcript:<path>.jsonl` backlink to the raw session it summarizes, and those files live in
`~/.claude/projects`, which Claude Code prunes after 30 days. Nothing reported the rot: the journal keeps
reading fine while its evidence disappears. When this was measured, **115 of 152 backlinks were already
unrecoverable**. `scripts/backup-transcripts.sh` rsyncs the tree to `~/Documents/Claude_Transcripts`
(override with `JACOB_TRANSCRIPT_ARCHIVE`); it never writes inside `~/.claude/` and refuses a destination
inside `JACOB_ROOT`, since the archive grows without bound and §workspace versions docs and config only.
bootstrap runs it once at install so a fresh clone starts preserving immediately, and `--uninstall`
deliberately leaves the archive alone. Check 16 reports dead backlinks and a stale archive.
This is the raw-archive floor under memsearch (episodic) and the vault (curated). The alternative
considered was MemPalace, declined 2026-09-07 — see `WATCHED_REPOS` in `scripts/check-updates.sh`.

**Vault source-lag (2026-09-07).** §vault says the vault lags the code and the code wins, without saying
which page lags. `scripts/vault-lag.sh` joins each wiki page's `updated:` and `path:` frontmatter against
the project checkout named in `vault/.vault-meta/source-roots.json`, using that path's last commit
date rather than mtime (a clone resets every mtime and would report the whole vault stale). An unmapped
group is reported as unverifiable, never as clean. `agents/wiki-lint.md` step 7 invokes it. First run:
9 lagging, 2 current, 2 unverifiable.

**Autoharness create bar (2026-11-06).** Autoharness's reflector is told to create a skill whenever it is
unsure, which bloats `skills/`. `scripts/hooks/create_bar.py` is a PreToolUse hook on its `stage_skill`
tool. It judges only `create` calls from an autoharness child session, and denies a skill that carries
no more than a sentence Kaan could just say. Patches, merges, deletes and `/learn` pass through. Any
judge failure allows. bootstrap merges the entry into `settings.json` `hooks.PreToolUse`, and Check 23
fails without it. Verdicts go to `.state/create-bar.log`, which is gitignored. The judge's rubric is
`scripts/hooks/create-bar-rubric.md`, and `scripts/evals/run-create-bar-eval.py` must pass 20/20 after
any rubric change.

---

## MCP servers on the spine {#layout/mcp}

**Project-specific** MCP servers (e.g. Unity MCP) are wired **per-Unity-project** (`<proj>/.mcp.json`),
not in Jacob — see the `unity-mcp-setup` memory. **Exception (2026-07-31):** Coplay `CoplayMCP` is a
deliberate **spine** exception (reverses the 2026-07-29 removal) — see the servers.json note for the
two-writers (Coplay Auto-Setup ↔ bootstrap) caveat.

**Exception — globally-useful servers live on the spine.** Jacob owns a canonical, tool-neutral MCP
definition at `mcp/servers.json`; `scripts/bootstrap.sh` translates it into Claude Code's format and merges
it into `~/.claude.json` under `.mcpServers`, at **user level**.

So **every** project inherits them, and `scripts/doctor.sh` Check 8 fails on drift. This deliberately overrides
the per-project default for servers that help everywhere.

Currently declared: one server. `context7` was removed on 2026-10-05, after zero calls in 45 days;
the local `references/` snapshots and Coplay's `unity_reflect` cover API lookups. **`CoplayMCP`**
(Coplay) — HTTP at `http://127.0.0.1:8085/mcp`, the shared server Coplay starts from the Unity
window. Entries in `mcp/servers.json` are stdio (`command`/`args`) or HTTP (`url`). Spine exception: present in every tool, useful only when a
Coplay-enabled Unity project is open.

Edit `mcp/servers.json`, never the per-tool copies; re-run `./scripts/bootstrap.sh`.

---

## Skill inventory & refresh {#layout/skill-inventory}

`skills/skills.lock.json` is the source of truth for installed local skill versions — consult it before
assuming a skill is present or to reconcile drift. Every entry carries an `update_policy`:

| Policy | Meaning |
|---|---|
| `track` | Safe re-pull from upstream |
| `adapted` | 3-way diff, never overwrite — re-apply Jacob deltas by hand |
| `frozen` | No upstream to pull from |
| `native` | Authored here |

Caveats that look like drift but aren't:
- Some entries have `version: null` — upstream isn't semver-tagged. That means "tracked, unversioned," not "untracked."
- `theone-unity-standards` records `source_status: 404` — upstream is gone and cannot be re-fetched.

**The refresh procedure itself lives in the `/check-updates` skill** (`skills/check-updates/SKILL.md`) —
it owns the step-by-step, and `scripts/check-updates.sh` produces the read-only drift report it acts on.

**`unity-skills` is package-owned, not vendored** (ruleset §invocation). The second Unity Editor tool is a REST
skill set delivered by the `com.besty.unity-skills` UPM package. It appears only inside Unity projects
that carry that package, which is its own scoping — nothing on Jacob's spine installs or refreshes it,
and it must never be added to `skills.lock.json`. Full disposition:
`vault/wiki/meta/archived-roster.md`. Jacob's own Editor automation route stays `unity-mcp-skill` over
the Coplay `CoplayMCP` server — see *MCP servers on the spine* above.

**External plugins are not vendored.** Superpowers (ruleset §behavior; detail in `Jacob_Engineering.md`) is managed through its own
plugin/marketplace system; updates come from upstream. `scripts/bootstrap.sh` wires the plugin registration but
does not re-vendor the skill content.

**autoharness is a sanctioned writer into `skills/` (2026-10-09).** The `autoharness` plugin learns skills
from sessions. Its global layer is `~/.claude/skills`, so it writes into this folder on purpose. It is
the one exception to the write-back hazard in *Cross-tool spine* above. Its skills carry a
`.sidecar.json` with `"created_by": "agent"`. `scripts/sync-autoharness-lock.sh` runs first in the
pre-commit gate and adds, updates, or removes their lock entries with `source: "autoharness"`.
It never touches an entry from another source. The skills are tracked in git and reviewed by hand
from `git status`. Its archive folder and its `*.json.lock` files are gitignored.

---

## Model config {#layout/model-config}

`rules/MODEL_POLICY.md` is a **reference register** of Claude's model IDs, not a routing policy — see its own
header for the roster.

**Claude model selection is manual (2026-07-25).** `scripts/bootstrap.sh` does not write the Claude tier env
vars and `--uninstall` does not strip them; that code was removed deliberately, not lost — do not
reinstate it. Change models by hand in `~/.claude/settings.json` `env`. The resulting state is manually
owned and not inspected by `scripts/doctor.sh` or `/check-updates`. OmniRoute routing was dropped
altogether on 2026-10-01, along with the two toggle scripts that applied it.

`scripts/doctor.sh` Check 7 (Claude model IDs in agent frontmatter) still enforces the Jacob-side wiring.

---

## Validation {#layout/validation}

`./scripts/doctor.sh` must exit 0 after any spine change. Checks that specifically guard this file's claims:

| Check | Guards |
|---|---|
| 1b | No vendored skill's payload is hidden from git by `.gitignore`. Guards the clone-plus-bootstrap promise: a swallowed file is present here and missing on the next machine |
| 2 | Every backticked workspace path cited in the ruleset, MODEL_POLICY, README, **and this file** resolves |
| 2b | Retired layout conventions stay absent |
| 8 | Declared MCP servers are merged into every tool config. A project-scoped server in `~/.claude.json` that points at the same URL or command as a Jacob server only warns |
| 11 | Every `§N` reference in a governance file resolves to a real ruleset heading |
| 14 | No credential patterns in the committed memsearch journals; redaction prompt is wired |
| 15 | `rules/output-styles/jacob-plain.md` exists, is symlinked into `~/.claude`, and `settings.json` `outputStyle` selects it |
| 16 | `transcript:` backlinks in the journals still resolve live or in the archive, and the archive is not behind |
| 17 | Every vault page with frontmatter carries `updated:`, the field `scripts/vault-lag.sh` reads |
| 23 | The autoharness create-bar hook is in `settings.json` `hooks.PreToolUse` and its script exists |
