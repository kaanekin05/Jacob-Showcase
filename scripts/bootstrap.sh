#!/usr/bin/env bash
#
# bootstrap.sh — wire Jacob (the single source of truth) into Claude Code.
#
# Jacob holds the only editable copies of the rules/skills/agents/commands/docs.
# Claude Code reads them through SYMLINKS — fake files that point back at Jacob —
# so editing Jacob once is the only edit there is.
#
# Jacob wired three tools until 2026-10-01. opencode and Antigravity CLI are no
# longer used, so their adapters are gone and their symlinks are retired on sight
# (see retired_links). Claude Code is the only consumer.
#
# This script (re)creates those symlinks. It is IDEMPOTENT: run it as many times
# as you like and the result is identical. It never clobbers a real file/dir, and
# it records what it did in .install-state.json so it can be safely uninstalled.
#
# Usage:
#   ./bootstrap.sh            # create/repair all symlinks
#   ./bootstrap.sh --dry-run  # show what WOULD change, touch nothing
#   ./bootstrap.sh --verify   # report current state, change nothing
#   ./bootstrap.sh --uninstall# remove only the symlinks this script created
#   ./bootstrap.sh --help
#
set -euo pipefail

# --- Configuration ----------------------------------------------------------
# JACOB_ROOT is where the canonical files live. Override via env if you ever
# clone Jacob somewhere else: JACOB_ROOT=/path ./bootstrap.sh
JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
STATE_FILE="$JACOB_ROOT/.install-state.json"

# MCP servers: one canonical definition (command+args) merged into Claude Code's
# USER-level config, so every project inherits them. The definition stays
# tool-neutral in shape; only the Claude translation is still emitted.
# This DELIBERATELY overrides the ruleset default
# "MCP is per-project, never on the spine" — a considered exception for globally
# useful servers (e.g. context7 live docs). Editable source stays in Jacob.
MCP_SERVERS_FILE="${MCP_SERVERS_FILE:-$JACOB_ROOT/mcp/servers.json}"
CLAUDE_JSON="${CLAUDE_JSON:-$HOME/.claude.json}"
# NOTE: ~/.claude/settings.json model selection is deliberately NOT managed here
# — Claude model selection is manual (see the Claude CLI note below). The one
# scoped exception is `.enabledPlugins` (plugin activation, orthogonal to model
# config): install_superpowers() flips it, since registering a plugin in
# installed_plugins.json is not enough to activate it in Claude Code.
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$CLAUDE_DIR/settings.json}"
JACOB_OUTPUT_STYLE="${JACOB_OUTPUT_STYLE:-jacob-plain}"   # rules/output-styles/<name>.md (§behavior register)
JACOB_STATUSLINE="$JACOB_ROOT/scripts/statusline-context.sh"   # context-window meter (configure_statusline)
JACOB_MODS_DIR="$JACOB_ROOT/mods"   # Claude Code mods, one folder each (configure_mods)

# memsearch redaction prompt: .memsearch/memory/*.md is git-tracked and pushed
# (§workspace), and it is written by an LLM summarizing raw transcripts — so a pasted
# credential can reach the remote. On 2026-08-30 one already had. Jacob owns the
# summarizer prompt that tells it to drop secrets and honor <private> markers;
# memsearch reads it from an ABSOLUTE path recorded in ~/.memsearch/config.toml,
# which is machine-local and therefore does not survive a fresh clone. Without
# this wiring, memsearch silently falls back to the upstream prompt (stop.sh:108)
# and the convention is gone with no error. Same shape as the MCP merge above:
# canonical source in git, user-level target so every project inherits it.
# scripts/doctor.sh Check 14 is the drift guard; it also greps the journals themselves.
MEMSEARCH_PROMPT="${MEMSEARCH_PROMPT:-$JACOB_ROOT/scripts/memsearch/summarize.txt}"

# Superpowers: a companion AI-agent-powered development framework. Jacob and
# Superpowers are complementary — Superpowers governs the development PROCESS
# (brainstorming → plans → SDD → review), Jacob governs the DOMAIN KNOWLEDGE
# (Unity/C# rules, framework guidelines). Each tool installs it through its own
# native plugin system, so there is no local clone anywhere (the old sibling
# ../superpowers clone was read by no tool and was deleted 2026-09-14). The
# skills stay in their own repo — Jacob does not vendor them. See the
# superpowers-integration memory for the full design.
SUPERPOWERS_MARKETPLACE="claude-plugins-official"
SUPERPOWERS_PLUGIN_NAME="superpowers"
SUPERPOWERS_PLUGIN_KEY="$SUPERPOWERS_PLUGIN_NAME@$SUPERPOWERS_MARKETPLACE"

# claude-obsidian: the LLM-wiki product (15 skills). Jacob vendored it under
# vendor/claude-obsidian/ and symlinked the skills out of it until 2026-10-01,
# because plugin-install was believed to fire an auto-commit hook. It does not —
# hooks.json registers only SessionStart and Stop, both of which reach
# hook_adapter.py, a file with no subprocess call, no git and no writes. 14 of the
# 15 vendored SKILL.md files were byte-identical to the plugin's; the 15th
# (wiki-lint) diverged only by Jacob's inline-vs-written-report scoping, which now
# lives in agents/wiki-lint.md where no refresh can reach it.
# vault/ stays DATA and is never touched by the plugin.
CO_MARKETPLACE_REPO="AgriciDaniel/claude-obsidian"
CO_MARKETPLACE="agricidaniel-claude-obsidian"
CO_PLUGIN_KEY="claude-obsidian@$CO_MARKETPLACE"
# The plugin resolves a vault by: explicit --vault, then CLAUDE_OBSIDIAN_VAULT,
# then the nearest .claude-obsidian.json. Jacob's skills run from SIBLING project
# directories, so the env var is the only durable pin — ruleset section 3.5 states
# the same path for the model, this states it for the tool. Machine-local key, so
# it does not survive a clone and belongs here.
CO_VAULT="${CO_VAULT:-$JACOB_ROOT/vault}"

# plugin-dev: Anthropic's plugin authoring toolkit (skill/agent/hook/command
# development skills + the skill-reviewer and agent-creator agents). Replaced
# Jacob's own forge skill and skill-reviewer agent on 2026-10-04. Jacob vendors
# none of it, so the marketplace owns refreshes. The official marketplace ships
# with Claude Code, so there is no marketplace step.
PLUGIN_DEV_KEY="plugin-dev@claude-plugins-official"

# Git pre-commit gate: run scripts/doctor.sh and block the commit on failure.
# Resolve the ACTUAL hooks dir (respects core.hookspath; LFS hooks live here too).
PRECOMMIT_MARKER="jacob-doctor-gate"
HOOKS_DIR="$(git -C "$JACOB_ROOT" rev-parse --git-path hooks 2>/dev/null || echo "$JACOB_ROOT/.git/hooks")"
case "$HOOKS_DIR" in /*) ;; *) HOOKS_DIR="$JACOB_ROOT/$HOOKS_DIR" ;; esac
PRECOMMIT="$HOOKS_DIR/pre-commit"

# The wiring map: "<link path>|<target path>".
# These are the per-tool adapters that all funnel back into Jacob.
links=(
  # --- Claude Code (plural dir names; reads CLAUDE.md AND AGENTS.md, so link only one) ---
  "$CLAUDE_DIR/CLAUDE.md|$JACOB_ROOT/AGENTS.md"
  "$CLAUDE_DIR/references|$JACOB_ROOT/references"
  "$CLAUDE_DIR/agents|$JACOB_ROOT/agents"
  "$CLAUDE_DIR/commands|$JACOB_ROOT/commands"
  "$CLAUDE_DIR/skills|$JACOB_ROOT/skills"
  "$CLAUDE_DIR/output-styles|$JACOB_ROOT/rules/output-styles"   # Claude-only: register/voice styles (§behavior). Activate via /config → Output style.

)

# Stale links from earlier hand-wiring that should be removed if present, plus
# the retired opencode / Antigravity adapters (2026-10-01). Only SYMLINKS are
# removed — a real config file or directory of yours is never touched.
legacy_links=(
  # retired 2026-10-05: Claude Code loaded this AND CLAUDE.md, so the ruleset was resident twice
  "$CLAUDE_DIR/AGENTS.md"
  # retired 2026-10-01: opencode is no longer used
  "$HOME/.config/opencode/AGENTS.md"
  "$HOME/.config/opencode/CLAUDE.md"
  "$HOME/.config/opencode/references"
  "$HOME/.config/opencode/command"
  "$HOME/.config/opencode/skills"
  # retired 2026-10-01: Antigravity CLI is no longer used
  "$HOME/.gemini/config/plugins/jacob/rules/JacobRuleset.md"
  "$HOME/.gemini/config/plugins/jacob/skills/jacob-skills"
  # retired 2026-10-01: ~/.agents was the opencode + Antigravity cross-tool path.
  # These four stayed live until the evening sweep. ~/.agents/skills resolved to
  # this repo's skills/, so every installer that targets a global skills path --
  # hindsight, threejs-game-skills, understand-anything, mempalace,
  # vercel-skills-cli, everything-claude-code -- had a write path into Jacob with
  # no tool left reading it. §workspace's clobber rule is the reason this list exists.
  "$HOME/.agents/AGENTS.md"
  "$HOME/.agents/CLAUDE.md"
  "$HOME/.agents/commands"
  "$HOME/.agents/skills"
  "$HOME/.agents/agents"
  "$HOME/.agents/references"
  "$CLAUDE_DIR/JacobMasterRuleset.md"   # misspelled order, pointed indirectly through AGENTS.md
  "$HOME/.gemini/GEMINI.md"              # retired: Gemini CLI → Antigravity CLI
  # retired by the 2026-09-14 layout: Documentations/ → references/, ruleset → AGENTS.md
  "$CLAUDE_DIR/Documentations"
  "$CLAUDE_DIR/JacobRulesetMASTER.md"
  "$HOME/.config/opencode/Documentations"
  "$HOME/.config/opencode/JacobRulesetMASTER.md"
  "$HOME/.agents/Documentations"
  "$HOME/.agents/JacobMasterRuleset.md"
)

# --- Output helpers ---------------------------------------------------------
GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
info()  { printf '%s\n' "$*"; }
ok()    { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
skip()  { printf '%s·%s %s\n' "$DIM" "$RESET" "$*"; }
warn()  { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
err()   { printf '%s✗%s %s\n' "$RED" "$RESET" "$*" >&2; }

MODE="install"
DRY=0

# --- State file (records what it created, for safe uninstall) ---------------
created=()  # link paths made/repaired this run

write_state() {
  [ "$DRY" -eq 1 ] && return 0
  local base; base=$(jq -n \
    --arg root "$JACOB_ROOT" \
    --arg updated "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{jacob_root: $root, updated: $updated, links: []}')
  local i n=${#links[@]}
  for ((i=0; i<n; i++)); do
    local lp="${links[$i]%%|*}" tg="${links[$i]##*|}"; [ "$lp" = "placeholder" ] && continue
    base=$(echo "$base" | jq --arg l "$lp" --arg t "$tg" '.links += [{"link": $l, "target": $t}]')
  done
  if [ -f "$STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
    local extra; extra=$(jq 'del(.jacob_root, .updated, .links)' "$STATE_FILE" 2>/dev/null)
    [ -n "$extra" ] && [ "$extra" != "{}" ] && base=$(echo "$base" "$extra" | jq -s 'add')
  fi
  printf '%s\n' "$base" > "$STATE_FILE"
}

# --- Core: make one symlink idempotently ------------------------------------
# Rules:
#   correct symlink already → skip
#   wrong/missing symlink   → (re)create
#   REAL file or dir there  → refuse to clobber, warn, leave it
link_one() {
  local link="$1" target="$2"
  [ "$link" = "placeholder" ] && return 0   # skip placeholder entries

  if [ ! -e "$target" ]; then
    warn "target missing, skipping: $target"; return 0; fi

  if [ -L "$link" ]; then
    local cur; cur="$(readlink "$link")"
    if [ "$cur" = "$target" ]; then skip "ok: $link"; return 0; fi
    if [ "$DRY" -eq 1 ]; then warn "would repoint: $link ($cur → $target)"; created+=("$link"); return 0; fi
    ln -sfn "$target" "$link"; ok "repointed: $link → $target"; created+=("$link"); return 0
  fi

  if [ -e "$link" ]; then err "REAL file/dir exists (not touching): $link"; return 0; fi

  if [ "$DRY" -eq 1 ]; then warn "would create: $link → $target"; created+=("$link"); return 0; fi
  mkdir -p "$(dirname "$link")"; ln -sfn "$target" "$link"
  ok "created: $link → $target"; created+=("$link")
}

remove_legacy() {
  local link="$1"
  if [ -L "$link" ]; then
    if [ "$DRY" -eq 1 ]; then warn "would remove legacy link: $link"; return 0; fi
    rm "$link"; ok "removed legacy link: $link"
  fi
}

# --- MCP servers: merge Jacob's canonical defs into Claude Code's user config --
# jq-merge helper: atomically apply <filter> to <file>, creating {} if absent.
_merge_json() {  # <file> <filter> <argjson-name> <argjson-value>
  local file="$1" filter="$2" name="$3" val="$4" tmp
  [ -f "$file" ] || { mkdir -p "$(dirname "$file")"; printf '{}\n' > "$file"; }
  tmp=$(mktemp)
  if jq --argjson "$name" "$val" "$filter" "$file" > "$tmp" 2>/dev/null; then
    mv "$tmp" "$file"; return 0
  fi
  rm -f "$tmp"; return 1
}

configure_mcp_servers() {
  [ -f "$MCP_SERVERS_FILE" ] || { skip "no mcp/servers.json — skipping MCP wiring"; return 0; }
  if ! command -v jq >/dev/null 2>&1; then
    warn "jq not installed — cannot merge MCP servers (install jq, then re-run)"; return 0; fi

  local names; names=$(jq -r 'keys | join(", ")' "$MCP_SERVERS_FILE")
  if [ "$DRY" -eq 1 ]; then
    warn "would merge MCP [$names] → $CLAUDE_JSON"; return 0; fi

  # Each entry is stdio ({command, args}) or HTTP ({url}); drop our 'note'.
  # Claude Code: {command, args} | {type:"http", url}.
  # ${JACOB_ROOT} in any string is expanded here, so servers.json carries no
  # machine path (Jacob lives under /Users on macOS, /mnt/fast on Linux).
  local canon; canon=$(jq --arg root "$JACOB_ROOT" \
    'map_values(if .url then {type:"http", url} else {command, args} end)
     | walk(if type == "string" then gsub("\\$\\{JACOB_ROOT\\}"; $root) else . end)' "$MCP_SERVERS_FILE")

  _merge_json "$CLAUDE_JSON" '.mcpServers = ((.mcpServers // {}) + $add)' add "$canon" \
    && ok "merged MCP [$names] → $CLAUDE_JSON (.mcpServers)" || warn "failed MCP merge: $CLAUDE_JSON"
}

uninstall_mcp_servers() {
  [ -f "$MCP_SERVERS_FILE" ] || { skip "no mcp/servers.json — nothing to unmerge"; return 0; }
  command -v jq >/dev/null 2>&1 || { warn "jq not installed — cannot unmerge MCP"; return 0; }
  local names_json names
  names_json=$(jq '[keys[]]' "$MCP_SERVERS_FILE"); names=$(jq -r 'keys | join(", ")' "$MCP_SERVERS_FILE")
  if [ "$DRY" -eq 1 ]; then warn "would remove MCP [$names] from tool configs"; return 0; fi
  _del_mcp() {  # <file> <container-key: mcpServers|mcp>
    local file="$1" key="$2" tmp
    [ -f "$file" ] || { skip "absent: $file"; return 0; }
    tmp=$(mktemp)
    if jq --argjson ks "$names_json" --arg k "$key" \
        '(.[$k]) |= (if . then reduce $ks[] as $n (.; del(.[$n])) else . end)' "$file" > "$tmp" 2>/dev/null; then
      mv "$tmp" "$file"; ok "removed MCP [$names] from $file (.$key)"
    else rm -f "$tmp"; warn "failed MCP unmerge: $file"; fi
  }
  _del_mcp "$CLAUDE_JSON" mcpServers
}

# --- Claude CLI model selection: NOT managed here (deliberate, 2026-07-25) ----
# bootstrap.sh used to merge an OmniRoute tier map into ~/.claude/settings.json
# .env on every run, and strip it again on --uninstall. That is gone: Claude model
# selection is MANUAL and owned by the user.
#
# Nothing in this repo writes ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*_MODEL. A plain
# ./bootstrap.sh will not touch your model config, --uninstall will not remove it,
# and nothing in scripts/doctor.sh reports or enforces it. Set the keys by hand.
# OmniRoute and its two toggle scripts were dropped 2026-10-01.

# --- Pre-commit gate: scripts/doctor.sh must pass before a commit lands -------------
# Refuses to clobber a pre-commit hook we didn't write (no marker).
install_precommit() {
  if [ -e "$PRECOMMIT" ] && ! grep -q "$PRECOMMIT_MARKER" "$PRECOMMIT" 2>/dev/null; then
    err "pre-commit hook exists and isn't ours (not touching): $PRECOMMIT"; return 0; fi
  if [ "$DRY" -eq 1 ]; then
    grep -q "$PRECOMMIT_MARKER" "$PRECOMMIT" 2>/dev/null \
      && skip "pre-commit gate already present" \
      || warn "would install pre-commit gate: $PRECOMMIT"; return 0
  fi
  mkdir -p "$HOOKS_DIR"
  cat > "$PRECOMMIT" <<EOF
#!/bin/sh
# DO NOT EDIT — managed by bootstrap.sh (jacob-doctor-gate). Remove with: ./bootstrap.sh --uninstall
"$JACOB_ROOT/scripts/sync-autoharness-lock.sh" || true
# Hooks run non-interactively, so a JACOB_ROOT exported in a shell rc never reaches doctor.
JACOB_ROOT="$JACOB_ROOT" exec "$JACOB_ROOT/scripts/doctor.sh"
EOF
  chmod +x "$PRECOMMIT"; ok "installed pre-commit gate: $PRECOMMIT"
}

uninstall_precommit() {
  if [ -f "$PRECOMMIT" ] && grep -q "$PRECOMMIT_MARKER" "$PRECOMMIT" 2>/dev/null; then
    [ "$DRY" -eq 1 ] && { warn "would remove pre-commit gate: $PRECOMMIT"; return 0; }
    rm "$PRECOMMIT"; ok "removed pre-commit gate: $PRECOMMIT"
  else skip "no jacob pre-commit gate to remove"; fi
}

# --- memsearch: point the summarizer at Jacob's redaction prompt -------------
# Uses `memsearch config set` rather than editing config.toml, so we never have
# to parse/rewrite TOML we don't own. Optional dependency: if the CLI isn't on
# this machine there is nothing to wire, which is a warn, not a failure.
install_memsearch_prompt() {
  if ! command -v memsearch >/dev/null 2>&1; then
    warn "memsearch CLI not on PATH — skipping redaction prompt wiring"; return 0; fi
  if [ ! -f "$MEMSEARCH_PROMPT" ]; then
    err "redaction prompt missing from the repo: $MEMSEARCH_PROMPT"; return 0; fi
  local cur; cur="$(memsearch config get prompts.summarize 2>/dev/null || true)"
  if [ "$cur" = "$MEMSEARCH_PROMPT" ]; then skip "memsearch redaction prompt already wired"; return 0; fi
  # Someone deliberately pointed this at a different prompt: say so, change nothing.
  if [ -n "$cur" ] && [ "$cur" != "$MEMSEARCH_PROMPT" ]; then
    err "prompts.summarize points elsewhere (not touching): $cur"; return 0; fi
  if [ "$DRY" -eq 1 ]; then warn "would wire prompts.summarize → $MEMSEARCH_PROMPT"; return 0; fi
  memsearch config set prompts.summarize "$MEMSEARCH_PROMPT" >/dev/null 2>&1 \
    && ok "wired memsearch redaction prompt: $MEMSEARCH_PROMPT" \
    || err "failed to set prompts.summarize"
}

# --- memsearch: pin the bare CLI to Jacob's own collection -------------------
# The global config's default is `memsearch_chunks`, a legacy store holding 3,276
# rows of cross-project content. memsearch derives a per-project collection
# (ms_<basename>_<sha8>), and the plugin hooks and memory-recall skill inject it,
# but a bare `memsearch search` does not — it fell through to the global default
# and returned another project's memories. Found 2026-09-27.
#
# ("milvus","collection") is project-allowlisted (config.py:39), so this writes
# .memsearch.toml and leaves the global config and ~30 other collections alone.
# The name is path-derived, so it is gitignored and regenerated here on clone.
install_memsearch_collection() {
  if ! command -v memsearch >/dev/null 2>&1; then
    warn "memsearch CLI not on PATH — skipping collection pin"; return 0; fi
  local state="$JACOB_ROOT/.memsearch/.index-state.json" col
  if [ ! -f "$state" ]; then
    skip "no memsearch index state yet — collection pin deferred"; return 0; fi
  col="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['collection'])" "$state" 2>/dev/null || true)"
  if [ -z "$col" ]; then err "could not read collection from $state"; return 0; fi
  if [ "$(cd "$JACOB_ROOT" && memsearch config get milvus.collection 2>/dev/null)" = "$col" ]; then
    skip "memsearch collection already pinned: $col"; return 0; fi
  if [ "$DRY" -eq 1 ]; then warn "would pin milvus.collection -> $col"; return 0; fi
  (cd "$JACOB_ROOT" && memsearch config set milvus.collection "$col" --project >/dev/null 2>&1) \
    && ok "pinned memsearch collection: $col" \
    || err "failed to pin milvus.collection"
}

# --- transcripts: snapshot them out from under the 30-day delete -------------
# A fresh clone should start preserving IMMEDIATELY, not on whatever day someone
# remembers the script exists — Claude Code's prune runs on a clock regardless.
# One idempotent rsync at install time; doctor Check 16 warns when it goes stale.
# The archive lives outside the repo, so --uninstall deliberately does NOT remove
# it: deleting a verbatim history to tidy up wiring would be the exact loss this
# whole path exists to prevent.
install_transcript_backup() {
  local sh="$JACOB_ROOT/scripts/backup-transcripts.sh"
  [ -x "$sh" ] || { warn "scripts/backup-transcripts.sh missing or not executable"; return 0; }
  [ -d "$HOME/.claude/projects" ] || { skip "no Claude Code transcripts on this machine"; return 0; }
  if [ "$DRY" -eq 1 ]; then warn "would snapshot transcripts via scripts/backup-transcripts.sh"; return 0; fi
  # rc must come from the script, not from the tail that trims its banner.
  local raw rc
  raw="$("$sh" 2>&1)"; rc=$?
  local out; out="$(printf '%s' "$raw" | tail -2 | tr '\n' ' ')"
  if [ "$rc" -eq 0 ]; then ok "transcripts archived:$out"; else err "transcript backup failed:$out"; fi
}

uninstall_memsearch_prompt() {
  command -v memsearch >/dev/null 2>&1 || { skip "memsearch CLI absent"; return 0; }
  local cur; cur="$(memsearch config get prompts.summarize 2>/dev/null || true)"
  if [ "$cur" = "$MEMSEARCH_PROMPT" ]; then
    [ "$DRY" -eq 1 ] && { warn "would unset prompts.summarize"; return 0; }
    memsearch config set prompts.summarize "" >/dev/null 2>&1 \
      && ok "unset memsearch redaction prompt" || err "failed to unset prompts.summarize"
  else skip "prompts.summarize is not Jacob's (leaving alone)"; fi
}

# --- Superpowers: native plugin install via the Claude marketplace ---------
install_superpowers() {
  if ! command -v jq >/dev/null 2>&1; then
    warn "jq not installed — cannot register superpowers plugin (install jq, then re-run)"; return 0; fi

  # --- Claude Code: the official marketplace owns the download and the cache ---
  local claude_plugins_json="$CLAUDE_DIR/plugins/installed_plugins.json"
  if [ -d "$CLAUDE_DIR" ]; then
    if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.plugins | has($k)' "$claude_plugins_json" >/dev/null 2>&1; then
      skip "claude plugin already installed: $SUPERPOWERS_PLUGIN_KEY"
    elif ! command -v claude >/dev/null 2>&1; then
      warn "claude CLI not on PATH — cannot install $SUPERPOWERS_PLUGIN_KEY"
    elif [ "$DRY" -eq 1 ]; then warn "would run: claude plugin install $SUPERPOWERS_PLUGIN_KEY"
    else claude plugin install "$SUPERPOWERS_PLUGIN_KEY" >/dev/null 2>&1 \
           && ok "installed claude plugin: $SUPERPOWERS_PLUGIN_KEY" \
           || warn "claude plugin install failed: $SUPERPOWERS_PLUGIN_KEY (check network)"; fi
  else warn "claude config dir not found: $CLAUDE_DIR — skipping claude plugin install"; fi

  # --- Claude Code: enable the plugin in settings.json (.enabledPlugins) ---
  # Registration in installed_plugins.json is NOT enough — Claude Code only
  # activates a plugin (and fires its SessionStart hook) when it's also flipped
  # true here.
  if [ -d "$CLAUDE_DIR" ]; then
    if [ -f "$CLAUDE_SETTINGS" ]; then
      if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.enabledPlugins[$k] == true' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
        skip "claude plugin already enabled: $SUPERPOWERS_PLUGIN_KEY"
      else [ "$DRY" -eq 1 ] && warn "would enable claude plugin: $SUPERPOWERS_PLUGIN_KEY" || {
        local es_tmp; es_tmp=$(mktemp)
        jq --arg k "$SUPERPOWERS_PLUGIN_KEY" '.enabledPlugins = ((.enabledPlugins // {}) + {($k): true})' \
          "$CLAUDE_SETTINGS" > "$es_tmp" \
          && mv "$es_tmp" "$CLAUDE_SETTINGS" \
          && ok "enabled claude plugin: $SUPERPOWERS_PLUGIN_KEY" \
          || { warn "failed to enable claude plugin (settings.json write)"; rm -f "$es_tmp"; }; }; fi
    else [ "$DRY" -eq 1 ] && warn "would create $CLAUDE_SETTINGS with enabledPlugins: $SUPERPOWERS_PLUGIN_KEY" || {
      jq -n --arg k "$SUPERPOWERS_PLUGIN_KEY" '{"enabledPlugins": {($k): true}}' > "$CLAUDE_SETTINGS" \
        && ok "created $CLAUDE_SETTINGS with enabledPlugins: $SUPERPOWERS_PLUGIN_KEY"; }; fi
  fi

  # Record state in .install-state.json
  if [ "$DRY" -eq 0 ] && [ -f "$STATE_FILE" ]; then
    local state_tmp; state_tmp=$(mktemp)
    jq '.superpowers = {"claude": true}' \
      "$STATE_FILE" > "$state_tmp" && mv "$state_tmp" "$STATE_FILE" 2>/dev/null
  fi
}

uninstall_superpowers() {
  if [ -f "$CLAUDE_DIR/plugins/installed_plugins.json" ] && command -v jq >/dev/null 2>&1; then
    if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.plugins | has($k)' "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1; then
      [ "$DRY" -eq 1 ] && { warn "would unregister claude plugin: $SUPERPOWERS_PLUGIN_KEY"; } || {
        local tmp; tmp=$(mktemp); jq --arg k "$SUPERPOWERS_PLUGIN_KEY" 'del(.plugins[$k])' \
          "$CLAUDE_DIR/plugins/installed_plugins.json" > "$tmp" \
          && mv "$tmp" "$CLAUDE_DIR/plugins/installed_plugins.json" \
          && ok "unregistered claude plugin: $SUPERPOWERS_PLUGIN_KEY"; }
    else skip "claude plugin not registered: $SUPERPOWERS_PLUGIN_KEY"; fi
  fi

  if [ -f "$CLAUDE_SETTINGS" ] && command -v jq >/dev/null 2>&1; then
    if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.enabledPlugins | has($k)' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
      [ "$DRY" -eq 1 ] && { warn "would disable claude plugin: $SUPERPOWERS_PLUGIN_KEY"; } || {
        local tmpe; tmpe=$(mktemp); jq --arg k "$SUPERPOWERS_PLUGIN_KEY" 'del(.enabledPlugins[$k])' \
          "$CLAUDE_SETTINGS" > "$tmpe" \
          && mv "$tmpe" "$CLAUDE_SETTINGS" \
          && ok "disabled claude plugin: $SUPERPOWERS_PLUGIN_KEY"; }
    else skip "claude plugin not enabled: $SUPERPOWERS_PLUGIN_KEY"; fi
  fi

  if [ -f "$STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
    local tmp3; tmp3=$(mktemp); jq 'del(.superpowers)' "$STATE_FILE" > "$tmp3" && mv "$tmp3" "$STATE_FILE" 2>/dev/null; fi
}

# --- Claude Code: activate Jacob's plain-English output style ---------------
# The style FILE lives in Jacob (rules/output-styles/, symlinked above), but the
# activation key is machine-local settings.json. A bare clone would therefore
# ship the style inert, so activation belongs in bootstrap (§workspace suitcase model).
# `/output-style <name>` was removed in CLI v2.1.91 — the settings key is the
# only durable activation path. Never overrides a style the user picked.
# --- claude-obsidian: marketplace + plugin install + vault pin ---------------
install_claude_obsidian() {
  command -v jq >/dev/null 2>&1 || { warn "jq not installed — cannot wire claude-obsidian"; return 0; }

  # Marketplace, then plugin, then the enable flag (registration alone is inert).
  if command -v claude >/dev/null 2>&1; then
    if claude plugin marketplace list 2>/dev/null | grep -q "$CO_MARKETPLACE"; then
      skip "marketplace present: $CO_MARKETPLACE"
    elif [ "$DRY" -eq 1 ]; then warn "would add marketplace: $CO_MARKETPLACE_REPO"
    else claude plugin marketplace add "$CO_MARKETPLACE_REPO" >/dev/null 2>&1 \
           && ok "added marketplace: $CO_MARKETPLACE" \
           || warn "marketplace add failed: $CO_MARKETPLACE_REPO (check network)"; fi

    if jq -e --arg k "$CO_PLUGIN_KEY" '.plugins | has($k)' \
         "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1; then
      skip "claude plugin already installed: $CO_PLUGIN_KEY"
    elif [ "$DRY" -eq 1 ]; then warn "would run: claude plugin install $CO_PLUGIN_KEY"
    else claude plugin install "$CO_PLUGIN_KEY" >/dev/null 2>&1 \
           && ok "installed claude plugin: $CO_PLUGIN_KEY" \
           || warn "claude plugin install failed: $CO_PLUGIN_KEY (check network)"; fi
  else warn "claude CLI not on PATH — cannot install $CO_PLUGIN_KEY"; fi

  if [ -f "$CLAUDE_SETTINGS" ]; then
    if jq -e --arg k "$CO_PLUGIN_KEY" '.enabledPlugins[$k] == true' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
      skip "claude plugin already enabled: $CO_PLUGIN_KEY"
    elif [ "$DRY" -eq 1 ]; then warn "would enable claude plugin: $CO_PLUGIN_KEY"
    else
      _merge_json "$CLAUDE_SETTINGS" '.enabledPlugins = ((.enabledPlugins // {}) + $add)' \
        add "$(jq -n --arg k "$CO_PLUGIN_KEY" '{($k): true}')" \
        && ok "enabled claude plugin: $CO_PLUGIN_KEY" || warn "failed to enable $CO_PLUGIN_KEY"
    fi
  fi

  # Vault pin. Never overwrite a different path the user chose deliberately.
  local cur=""
  [ -f "$CLAUDE_SETTINGS" ] && cur=$(jq -r '.env.CLAUDE_OBSIDIAN_VAULT // ""' "$CLAUDE_SETTINGS" 2>/dev/null)
  if [ "$cur" = "$CO_VAULT" ]; then skip "vault pinned: $CO_VAULT"
  elif [ -n "$cur" ]; then warn "CLAUDE_OBSIDIAN_VAULT is '$cur', not touching it"
  elif [ "$DRY" -eq 1 ]; then warn "would pin CLAUDE_OBSIDIAN_VAULT=$CO_VAULT"
  else
    _merge_json "$CLAUDE_SETTINGS" '.env = ((.env // {}) + $add)' \
      add "$(jq -n --arg v "$CO_VAULT" '{"CLAUDE_OBSIDIAN_VAULT": $v}')" \
      && ok "pinned CLAUDE_OBSIDIAN_VAULT=$CO_VAULT" || warn "failed to pin the vault path"
  fi
}

# --- plugin-dev: official plugin install + enable flag -----------------------
install_plugin_dev() {
  command -v jq >/dev/null 2>&1 || { warn "jq not installed — cannot wire plugin-dev"; return 0; }

  if ! command -v claude >/dev/null 2>&1; then warn "claude CLI not on PATH — cannot install $PLUGIN_DEV_KEY"
  elif jq -e --arg k "$PLUGIN_DEV_KEY" '.plugins | has($k)' \
         "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1; then
    skip "claude plugin already installed: $PLUGIN_DEV_KEY"
  elif [ "$DRY" -eq 1 ]; then warn "would run: claude plugin install $PLUGIN_DEV_KEY"
  else claude plugin install "$PLUGIN_DEV_KEY" >/dev/null 2>&1 \
         && ok "installed claude plugin: $PLUGIN_DEV_KEY" \
         || warn "claude plugin install failed: $PLUGIN_DEV_KEY (check network)"; fi

  if [ -f "$CLAUDE_SETTINGS" ]; then
    if jq -e --arg k "$PLUGIN_DEV_KEY" '.enabledPlugins[$k] == true' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
      skip "claude plugin already enabled: $PLUGIN_DEV_KEY"
    elif [ "$DRY" -eq 1 ]; then warn "would enable claude plugin: $PLUGIN_DEV_KEY"
    else
      _merge_json "$CLAUDE_SETTINGS" '.enabledPlugins = ((.enabledPlugins // {}) + $add)' \
        add "$(jq -n --arg k "$PLUGIN_DEV_KEY" '{($k): true}')" \
        && ok "enabled claude plugin: $PLUGIN_DEV_KEY" || warn "failed to enable $PLUGIN_DEV_KEY"
    fi
  fi
}

configure_output_style() {
  command -v jq >/dev/null 2>&1 || { warn "jq not found, skipping output style activation"; return 0; }
  [ -d "$CLAUDE_DIR" ] || { skip "claude config dir not found, skipping output style"; return 0; }
  [ -f "$JACOB_ROOT/rules/output-styles/$JACOB_OUTPUT_STYLE.md" ] || {
    warn "style file missing, skipping: rules/output-styles/$JACOB_OUTPUT_STYLE.md"; return 0; }

  local cur=""
  [ -f "$CLAUDE_SETTINGS" ] && cur=$(jq -r '.outputStyle // ""' "$CLAUDE_SETTINGS" 2>/dev/null)

  if [ "$cur" = "$JACOB_OUTPUT_STYLE" ]; then
    skip "output style already active: $JACOB_OUTPUT_STYLE"; return 0; fi
  if [ -n "$cur" ]; then
    warn "outputStyle is '$cur', not touching it. Switch with /config → Output style"; return 0; fi
  if [ "$DRY" -eq 1 ]; then
    warn "would set outputStyle: $JACOB_OUTPUT_STYLE"; return 0; fi

  if [ -f "$CLAUDE_SETTINGS" ]; then
    local os_tmp; os_tmp=$(mktemp)
    jq --arg s "$JACOB_OUTPUT_STYLE" '.outputStyle = $s' "$CLAUDE_SETTINGS" > "$os_tmp" \
      && mv "$os_tmp" "$CLAUDE_SETTINGS" \
      && ok "output style activated: $JACOB_OUTPUT_STYLE (applies next session)" \
      || { warn "failed to set outputStyle (settings.json write)"; rm -f "$os_tmp"; }
  else
    jq -n --arg s "$JACOB_OUTPUT_STYLE" '{"outputStyle": $s}' > "$CLAUDE_SETTINGS" \
      && ok "created $CLAUDE_SETTINGS with outputStyle: $JACOB_OUTPUT_STYLE"
  fi
}

# Context-window meter in the Claude Code status line. Claude Code has ONE
# statusLine slot. Orca's forwarder may already hold it; that forwarder prints
# nothing and our script chains it, so replacing Orca's entry loses nothing.
# Any other foreign entry is left alone.
configure_statusline() {
  command -v jq >/dev/null 2>&1 || { warn "jq not found, skipping status line"; return 0; }
  [ -d "$CLAUDE_DIR" ] || { skip "claude config dir not found, skipping status line"; return 0; }
  [ -x "$JACOB_STATUSLINE" ] || { warn "status line script missing or not executable, skipping: $JACOB_STATUSLINE"; return 0; }

  local cur=""
  [ -f "$CLAUDE_SETTINGS" ] && cur=$(jq -r '.statusLine.command // ""' "$CLAUDE_SETTINGS" 2>/dev/null)

  if [ "$cur" = "$JACOB_STATUSLINE" ]; then
    skip "status line already wired: $JACOB_STATUSLINE"; return 0; fi
  case "$cur" in
    ""|*".orca/agent-hooks/claude-statusline"*) ;;
    *) warn "statusLine is set to something else, not touching it"; return 0 ;;
  esac
  if [ "$DRY" -eq 1 ]; then
    warn "would set statusLine: $JACOB_STATUSLINE"; return 0; fi

  [ -f "$CLAUDE_SETTINGS" ] || echo '{}' > "$CLAUDE_SETTINGS"
  _merge_json "$CLAUDE_SETTINGS" '.statusLine = $sl' \
    sl "$(jq -n --arg c "$JACOB_STATUSLINE" '{type: "command", command: $c}')" \
    && ok "status line wired: $JACOB_STATUSLINE" || warn "failed to set statusLine (settings.json write)"
}

# Claude Code mods (plugins of function hooks) under mods/. Claude Code loads
# every folder named in env.CLAUDE_CODE_PLUGIN_DIRS of the USER settings.json,
# colon-separated, and reads them in place, so an edit in Jacob is live.
# A value that names folders outside mods/ is foreign and is left alone.
jacob_mod_dirs() {
  local out="" d
  for d in "$JACOB_MODS_DIR"/*/; do
    [ -f "${d}.claude-plugin/plugin.json" ] || continue
    out="${out:+$out:}${d%/}"
  done
  printf '%s' "$out"
}

configure_mods() {
  command -v jq >/dev/null 2>&1 || { warn "jq not found, skipping mods"; return 0; }
  [ -d "$CLAUDE_DIR" ] || { skip "claude config dir not found, skipping mods"; return 0; }
  local want cur="" part
  want=$(jacob_mod_dirs)
  [ -n "$want" ] || { skip "no mods under $JACOB_MODS_DIR"; return 0; }
  [ -f "$CLAUDE_SETTINGS" ] && cur=$(jq -r '.env.CLAUDE_CODE_PLUGIN_DIRS // ""' "$CLAUDE_SETTINGS" 2>/dev/null)

  if [ "$cur" = "$want" ]; then skip "mods already wired: $want"; return 0; fi
  local IFS=':'
  for part in $cur; do
    case "$part" in
      "$JACOB_MODS_DIR"/*) ;;
      *) warn "CLAUDE_CODE_PLUGIN_DIRS names a folder outside Jacob ('$part'), not touching it"; return 0 ;;
    esac
  done
  unset IFS
  if [ "$DRY" -eq 1 ]; then warn "would set CLAUDE_CODE_PLUGIN_DIRS=$want"; return 0; fi

  [ -f "$CLAUDE_SETTINGS" ] || echo '{}' > "$CLAUDE_SETTINGS"
  _merge_json "$CLAUDE_SETTINGS" '.env = ((.env // {}) + $add)' \
    add "$(jq -n --arg v "$want" '{"CLAUDE_CODE_PLUGIN_DIRS": $v}')" \
    && ok "mods wired: $want" || warn "failed to wire mods (settings.json write)"
}

# --- Subcommands ------------------------------------------------------------
# --- autoharness create bar: a PreToolUse hook on stage_skill -----------------
# Judges each new skill autoharness proposes against Kaan's bar before it is staged.
# Patches, merges, deletes and /learn pass through untouched. Spec:
# docs/superpowers/specs/2026-11-06-autoharness-create-bar-design.md
CREATE_BAR_MATCHER="mcp__plugin_autoharness_stage_skill__stage_skill"
CREATE_BAR_SCRIPT="$JACOB_ROOT/scripts/hooks/create_bar.py"

create_bar_wired() {  # 0 when settings.json carries Jacob's entry
  [ -f "$CLAUDE_SETTINGS" ] && jq -e --arg m "$CREATE_BAR_MATCHER" \
    '[.hooks.PreToolUse[]? | select(.matcher == $m) | .hooks[]?
      | select((.command // "") | endswith("scripts/hooks/create_bar.py"))] | length > 0' \
    "$CLAUDE_SETTINGS" >/dev/null 2>&1
}

configure_create_bar() {
  command -v jq >/dev/null 2>&1 || { warn "jq not found, skipping create-bar hook"; return 0; }
  [ -f "$CREATE_BAR_SCRIPT" ] || { warn "missing $CREATE_BAR_SCRIPT, skipping create-bar hook"; return 0; }
  if create_bar_wired; then skip "create-bar hook already wired"; return 0; fi
  if [ "$DRY" -eq 1 ]; then warn "would wire create-bar hook"; return 0; fi
  _merge_json "$CLAUDE_SETTINGS" '.hooks.PreToolUse = ((.hooks.PreToolUse // []) + [$add])' \
    add "$(jq -n --arg m "$CREATE_BAR_MATCHER" --arg c "python3 -I $CREATE_BAR_SCRIPT" \
      '{matcher: $m, hooks: [{type: "command", command: $c, timeout: 90}]}')" \
    && ok "wired create-bar hook: $CREATE_BAR_SCRIPT (applies next session)" \
    || warn "failed to wire the create-bar hook (settings.json write)"
}

do_install() {
  info "Wiring Jacob → Claude Code  (JACOB_ROOT=$JACOB_ROOT)"
  [ "$DRY" -eq 1 ] && warn "DRY RUN — nothing will be changed"
  [ -d "$JACOB_ROOT" ] || { err "JACOB_ROOT not found: $JACOB_ROOT"; exit 1; }

  for l in "${legacy_links[@]:-}"; do remove_legacy "$l"; done
  for entry in "${links[@]}"; do link_one "${entry%%|*}" "${entry##*|}"; done
  configure_mcp_servers
  install_claude_obsidian
  install_plugin_dev
  configure_output_style
  configure_statusline
  configure_mods
  configure_create_bar
  install_precommit
  install_memsearch_prompt
  install_memsearch_collection
  install_transcript_backup
  install_superpowers

  write_state
  info ""
  ok "done — ${#created[@]} link(s) created/repaired$([ "$DRY" -eq 1 ] && echo ' (dry run)')"
  [ "$DRY" -eq 0 ] && skip "state written: $STATE_FILE"
}

do_verify() {
  info "Verifying Jacob wiring  (JACOB_ROOT=$JACOB_ROOT)"
  local bad=0
  for entry in "${links[@]}"; do
    local link="${entry%%|*}" target="${entry##*|}"
    if [ "$link" = "placeholder" ]; then skip "placeholder: $entry"; continue; fi
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then ok "$link"
    else err "MISSING/WRONG: $link (expected → $target)"; bad=1; fi
  done
  # MCP servers merged into Claude Code's user config
  if [ -f "$MCP_SERVERS_FILE" ] && command -v jq >/dev/null 2>&1; then
    for m in $(jq -r 'keys[]' "$MCP_SERVERS_FILE"); do
      jq -e --arg m "$m" '.mcpServers[$m]' "$CLAUDE_JSON" >/dev/null 2>&1 && ok "Claude MCP: $m" || { err "Claude MCP missing: $m ($CLAUDE_JSON)"; bad=1; }
    done; fi
  if grep -q "$PRECOMMIT_MARKER" "$PRECOMMIT" 2>/dev/null; then ok "pre-commit gate: $PRECOMMIT"
  else err "MISSING: pre-commit gate ($PRECOMMIT)"; bad=1; fi
  # memsearch redaction prompt: a real failure when the CLI is here and the
  # wiring is not, because the fallback is silent (upstream prompt, no redaction).
  if command -v memsearch >/dev/null 2>&1; then
    if [ "$(memsearch config get prompts.summarize 2>/dev/null || true)" = "$MEMSEARCH_PROMPT" ] && [ -f "$MEMSEARCH_PROMPT" ]; then
      ok "memsearch redaction prompt: $MEMSEARCH_PROMPT"
    else err "memsearch redaction prompt NOT wired (run ./bootstrap.sh)"; bad=1; fi
  else warn "memsearch CLI not on this machine — redaction prompt not applicable"; fi
  # Superpowers: verify the Claude marketplace plugin is registered and enabled
    if [ -f "$CLAUDE_DIR/plugins/installed_plugins.json" ] && command -v jq >/dev/null 2>&1; then
      if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.plugins | has($k)' "$CLAUDE_DIR/plugins/installed_plugins.json" >/dev/null 2>&1; then
        ok "claude plugin registered: $SUPERPOWERS_PLUGIN_KEY"
      else err "claude plugin NOT registered: $SUPERPOWERS_PLUGIN_KEY"; bad=1; fi; fi
    if [ -f "$CLAUDE_SETTINGS" ] && command -v jq >/dev/null 2>&1; then
      if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.enabledPlugins[$k] == true' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
        ok "claude plugin enabled: $SUPERPOWERS_PLUGIN_KEY"
      else err "claude plugin registered but NOT enabled: $SUPERPOWERS_PLUGIN_KEY (run ./bootstrap.sh)"; bad=1; fi; fi
  # Status line: a warning, never a failure. Orca rewrites this slot on its own.
  if [ -f "$CLAUDE_SETTINGS" ] && command -v jq >/dev/null 2>&1; then
    if [ "$(jq -r '.statusLine.command // ""' "$CLAUDE_SETTINGS" 2>/dev/null)" = "$JACOB_STATUSLINE" ]; then
      ok "status line: $JACOB_STATUSLINE"
    else warn "status line not wired to Jacob's context meter (run ./bootstrap.sh)"; fi; fi
  # Mods: a real failure, nothing else rewrites this key.
  if [ -n "$(jacob_mod_dirs)" ] && [ -f "$CLAUDE_SETTINGS" ] && command -v jq >/dev/null 2>&1; then
    if [ "$(jq -r '.env.CLAUDE_CODE_PLUGIN_DIRS // ""' "$CLAUDE_SETTINGS" 2>/dev/null)" = "$(jacob_mod_dirs)" ]; then
      ok "mods: $(jacob_mod_dirs)"
    else err "mods NOT wired (run ./bootstrap.sh)"; bad=1; fi; fi
  # create-bar hook: a real failure, autoharness would create skills unjudged.
  if command -v jq >/dev/null 2>&1; then
    if create_bar_wired; then ok "create-bar hook: $CREATE_BAR_SCRIPT"
    else err "create-bar hook NOT wired (run ./bootstrap.sh)"; bad=1; fi; fi
  [ "$bad" -eq 0 ] && info "" && ok "all links correct" || { info ""; warn "run ./bootstrap.sh to repair"; exit 1; }
}

do_uninstall() {
  info "Removing Jacob symlinks (real files are left alone)"
  for entry in "${links[@]}"; do
    local link="${entry%%|*}"
    [ "$link" = "placeholder" ] && continue
    if [ -L "$link" ]; then
      [ "$DRY" -eq 1 ] && { warn "would remove: $link"; continue; }
      rm "$link"; ok "removed: $link"
    else skip "absent: $link"; fi
  done
  uninstall_mcp_servers
  uninstall_precommit
  uninstall_memsearch_prompt
  uninstall_superpowers
  if [ "$DRY" -eq 0 ] && [ -f "$STATE_FILE" ]; then rm "$STATE_FILE"; skip "state removed: $STATE_FILE"; fi
}

usage() { sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; }

# --- Arg parse --------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY=1 ;;
    --verify)    MODE="verify" ;;
    --uninstall) MODE="uninstall" ;;
    -h|--help)   usage; exit 0 ;;
    *)           err "unknown option: $arg"; usage; exit 1 ;;
  esac
done

case "$MODE" in
  install)   do_install ;;
  verify)    do_verify ;;
  uninstall) do_uninstall ;;
esac
