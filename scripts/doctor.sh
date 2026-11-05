#!/usr/bin/env bash
#
# scripts/doctor.sh — check that Jacob's *claims about itself* still match reality.
#
# Jacob's docs assert things: which skills are tracked, which docs exist, what
# the symlinks point at, which memories are indexed. Nothing enforces those
# claims, so they drift (this whole class of bug was found by hand repeatedly).
# This script asserts them automatically. Each check maps to a real drift we hit.
#
# Severities: FAIL = a source-of-truth lie (non-zero exit). WARN = worth a look.
#
# Usage:
#   ./scripts/doctor.sh            # run all checks
#   ./scripts/doctor.sh --help
#
set -uo pipefail   # NOTE: no -e; checks must all run even if one finds problems.

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
RULESET="$JACOB_ROOT/AGENTS.md"
LOCK="$JACOB_ROOT/skills/skills.lock.json"
MEMORY_DIR="${MEMORY_DIR:-$HOME/.claude/projects/$(printf %s "$JACOB_ROOT" | tr / -)/memory}"
SUPERPOWERS_PLUGIN_KEY="superpowers@claude-plugins-official"
CLAUDE_PLUGINS_JSON="${CLAUDE_PLUGINS_JSON:-$HOME/.claude/plugins/installed_plugins.json}"
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
JACOB_OUTPUT_STYLE="${JACOB_OUTPUT_STYLE:-jacob-plain}"

# Aliases where a lock entry name != its folder name (bash-3.2 safe). None
# currently, and none expected — every lock entry is its own folder since the
# 2026-10-01 handovers left Jacob vendoring no plugin subset.
alias_to_folder() { echo "$1"; }
folder_to_alias() { echo "$1"; }

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
fails=0; warns=0
pass() { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; warns=$((warns+1)); }
fail() { printf '%s✗%s %s\n' "$RED" "$RESET" "$*"; fails=$((fails+1)); }
# Not-applicable, not a problem: neither fails nor warns.
skip() { printf '%s-%s %s\n' "$DIM" "$RESET" "$*"; }
hdr()  { printf '\n%s%s%s\n' "$BOLD" "$*" "$RESET"; }

[ "${1:-}" = "--help" ] && { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
[ -d "$JACOB_ROOT" ] || { fail "JACOB_ROOT not found: $JACOB_ROOT"; exit 1; }

# --- Check 1: skills.lock.json <-> skills/ folders (the lock-drift bug) -------
hdr "1. skills.lock.json ↔ skills/ folders"
if [ -f "$LOCK" ]; then
  lock_names=$(grep -oE '^    "[^"]+": \{' "$LOCK" | sed -E 's/^ *"([^"]+)".*/\1/')
  # `synced/` is NOT a skill. Claude Code writes marketplace/built-in skill payloads there,
  # under UUID-named folders, because ~/.claude/skills symlinks into this repo (§workspace, "the
  # symlinks point both ways"). It regenerates after deletion, so it is gitignored and
  # skipped here rather than removed.
  disk_dirs=$(for d in "$JACOB_ROOT"/skills/*/; do
    n=$(basename "$d"); [ "$n" = "synced" ] && continue; printf '%s\n' "$n"
  done)
  # lock entries with no matching folder (apply alias).
  # `watched` entries are idea-sources tracked for drift only — harvested into a Jacob
  # surface, never vendored — so they legitimately have no skills/ folder.
  for n in $lock_names; do
    want=$(alias_to_folder "$n")
    pol=$(jq -r --arg k "$n" '.skills[$k].update_policy // ""' "$LOCK" 2>/dev/null)
    if [ "$pol" = "watched" ]; then
      if printf '%s\n' "$disk_dirs" | grep -qx "$want"; then
        fail "watched idea-source has a skills/ folder: $n (watched = never vendored; re-policy it)"
      else
        pass "watched idea-source (no folder, by design): $n"
      fi
      continue
    fi
    if printf '%s\n' "$disk_dirs" | grep -qx "$want"; then pass "tracked + present: $n"
    else fail "tracked in lock but NO folder: $n (expected skills/$want/)"; fi
  done
  # folders with no lock entry (reverse-apply alias)
  for d in $disk_dirs; do
    name=$(folder_to_alias "$d")
    printf '%s\n' "$lock_names" | grep -qx "$name" || fail "folder skills/$d/ is NOT in skills.lock.json"
  done
  # every entry carries a valid update_policy (check-updates.sh routes on it;
  # a missing one makes the freshness checker silently skip that skill).
  # NOTE: "watched" is deliberately NOT accepted here. A watched idea-source has
  # nothing on disk, so a lock entry for one is un-validatable (files_hash null,
  # file_count 0) and check-updates.sh section 1 would render it as a vendored skill and
  # tell you to "re-pull to compare" — the exact opposite of do-not-vendor.
  # Watched sources live in scripts/check-updates.sh WATCHED_REPOS. See §invocation there.
  if command -v jq >/dev/null 2>&1; then
    bad=$(jq -r '.skills | to_entries[]
      | select((.value.update_policy // "") | IN("track","adapted","frozen","native") | not)
      | .key' "$LOCK")
    if [ -z "$bad" ]; then pass "all lock entries have a valid update_policy"
    else for b in $bad; do fail "lock entry has invalid update_policy: $b (watched idea-sources belong in check-updates.sh WATCHED_REPOS, not the lock)"; done; fi
  else
    warn "jq not installed — cannot verify update_policy fields"
  fi
  # files_hash integrity: catch silent in-place edits to vendored skills. Canonical
  # hash = git-tracked files under the dir, sorted, content+path hashed — must match
  # how skills.lock.json's files_hash is written (git ls-files | shasum | shasum).
  if command -v jq >/dev/null 2>&1 && command -v shasum >/dev/null 2>&1; then
    _canon() { ( cd "$JACOB_ROOT" && git ls-files "$1" 2>/dev/null | LC_ALL=C sort -f | xargs shasum -a 256 2>/dev/null | shasum -a 256 | awk '{print "sha256:"$1}' ); }
    while IFS=$'\t' read -r key stored backing; do
      dir="${backing:-skills/$key}"
      got=$(_canon "$dir")
      if [ "$stored" = "$got" ]; then pass "files_hash intact: $key"
      else fail "files_hash DRIFT: $key ($dir) — recorded != on-disk (edited in place? re-vendor upstream, or re-hash if intentional)"; fi
    done < <(jq -r '.skills | to_entries[] | select(.value.files_hash != null)
      | [.key, .value.files_hash, (.value.backing_dir // "")] | @tsv' "$LOCK")
  else
    warn "jq/shasum missing — cannot verify files_hash integrity"
  fi
  # 1b: a vendored skill's payload must actually be IN git. .gitignore's C#
  # build rule "[Bb]in/" silently swallowed skills/archify/bin/ — all four
  # files, including archify.mjs, the CLI every documented archify command
  # invokes. A fresh clone plus bootstrap.sh therefore produced a skill where
  # nothing ran, breaking §workspace's suitcase promise. Worse, files_hash above
  # hashes `git ls-files` output, so its drift check had a blind spot over
  # exactly the file most worth watching. Nine days between install and catch.
  #
  # FAIL, not WARN: the noise patterns below are filtered out, so a surviving
  # hit means real payload is being dropped on clone.
  #
  # skills/synced/ is excluded: Claude Code writes marketplace payloads there because
  # ~/.claude/skills symlinks into this repo. It is a tool's cache, regenerates on sync,
  # and a fresh clone is SUPPOSED to lose it — the opposite of what this check guards.
  #
  # Scope: skills/ AND vendor/. It was skills/ only until 2026-09-28, on the
  # reasoning that backing_dir trees are full code repos whose correctly-ignored
  # files would false-positive. That reasoning held for the venv, not for the
  # payload: the SAME "[Bb]in/" rule then swallowed vendor/claude-obsidian/bin/,
  # five setup-*.sh scripts a fresh clone never had, and the skills/-only scope
  # is exactly why this check stayed silent. The noise filters below already
  # cover what a code repo legitimately ignores — measured over vendor/ on
  # 2026-09-28, they take 4831 ignored files to 0. A one-path negation per
  # incident does not close the class; widening the scope does.
  _swallowed=$( ( cd "$JACOB_ROOT" && git ls-files --others --ignored --exclude-standard skills/ vendor/ 2>/dev/null ) \
    | grep -vE '(^|/)(node_modules|\.venv|venv|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache)/' \
    | grep -vE '(^|/)\.DS_Store$' \
    | grep -vE '\.(log|pyc)$' \
    | grep -vE '^skills/synced/' \
    | grep -vE '^skills/(\.archive/|.+\.json\.lock$)' \
    | grep -vE '(^|/)\.claude/autoharness/' )
  # .claude/autoharness/ is per-session plugin state that autoharness writes under whatever
  # folder a session starts in. .gitignore drops it everywhere, and a clone is meant to lose it.
  if [ -z "$_swallowed" ]; then
    pass "no skills/ or vendor/ payload hidden from git by .gitignore"
  else
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      rule=$( ( cd "$JACOB_ROOT" && git check-ignore -v "$f" 2>/dev/null ) | cut -d: -f1,2 )
      fail "payload hidden from git: $f (ignored by ${rule:-unknown}) — a fresh clone loses it; add a scoped negation like '!skills/<name>/bin/' or '!vendor/<name>/bin/', or delete the file if it is genuinely build output"
    done <<< "$_swallowed"
  fi
  # every track entry should carry a pin (source_commit or a release) so the
  # freshness checker can compare precisely — WARN (some upstreams legitimately lag).
  if command -v jq >/dev/null 2>&1; then
    for k in $(jq -r '.skills | to_entries[]
      | select(.value.update_policy=="track" and (.value.source_commit|not) and (.value.source_release|not))
      | .key' "$LOCK"); do
      warn "track entry has no source_commit/source_release pin: $k (pin it on the next re-vendor)"
    done
  fi
else
  fail "missing $LOCK"
fi

# --- Check 2: workspace paths cited in the top-level docs exist ---------------
# Originally references/-only, which is why a deleted INTEGRATIONS.md and a
# graphify/ tree replaced back on 2026-07-20 both sat cited-but-missing in the
# ruleset for weeks — the gate simply wasn't looking at them. Now every
# backticked workspace-relative path in the three top-level docs is resolved.
#
# Scope rule: a backticked token is checked only if it is a *relative path* under
# a real Jacob top-level dir, or a root-level `*.sh` script. Deliberately NOT
# checked: bare basenames (`Part_01.md`, `settings.json`) — those are prose
# shorthand, and half of them name files outside Jacob entirely; vault-relative
# paths (wiki/… resolve against VAULT_PATH, §vault); home/absolute paths; URLs;
# shell vars; placeholders (<Library>, <proj>, globs).
#
# Corollary for authors: backticks mean "live path". Write a since-deleted file's
# name as prose, not code, so the doc isn't asserting something untrue.
#
# NEGATIVE_PATHS are cited by Jacob_Engineering.md precisely *because* they must not exist (the
# retired doubly-nested convention). They're excluded here and asserted absent in
# Check 2b — so if one ever reappears on disk, that's drift and it fails.
#
# Jacob_Layout.md joined the scan 2026-07-25: the ruleset's directory map moved
# there, so without it this check's coverage would have silently shrunk to the
# handful of paths the slimmed ruleset still cites.
hdr "2. Workspace paths cited in docs resolve"
NEGATIVE_PATHS="agents/agents skills/skills dotnet-skills-master commands/commands Documentations obsidian-vault claude-obsidian tools evals output-styles JacobRulesetMASTER.md MODEL_POLICY.md doctor.sh"
doc_files="$RULESET $JACOB_ROOT/rules/MODEL_POLICY.md $JACOB_ROOT/README.md $JACOB_ROOT/rules/Jacob_Layout.md"
checked=0; missing=0
is_negative() {
  for n in $NEGATIVE_PATHS; do [ "$1" = "$n" ] && return 0; done
  return 1
}
for f in $doc_files; do
  [ -f "$f" ] || { warn "doc missing, cannot scan: $f"; continue; }
  base=$(basename "$f")
  toks=$(grep -oE '`[^`]+`' "$f" | tr -d '`' | sort -u)
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    case "$t" in
      *'<'*|*'>'*|*'*'*|*'…'*|*' '*) continue ;;  # placeholder, glob, or prose
      '~'*|/*|http*|'$'*|.*) continue ;;          # home, absolute, URL, var, dotfile
    esac
    t="${t%/}"
    is_negative "$t" && continue
    case "$t" in
      references/*|rules/*|skills/*|agents/*|commands/*|scripts/*|mcp/*|vault/*) ;;
      */*) continue ;;                            # some other nested path — not ours
      *.sh) ;;                                    # root-level script
      *) continue ;;
    esac
    checked=$((checked+1))
    [ -e "$JACOB_ROOT/$t" ] || { fail "$base cites missing path: $t"; missing=$((missing+1)); }
  done <<EOF
$toks
EOF
done
if [ "$checked" -eq 0 ]; then warn "no workspace paths found in docs (unexpected)"
elif [ "$missing" -eq 0 ]; then pass "all $checked cited workspace paths resolve (ruleset + MODEL_POLICY + README + Jacob_Layout)"
fi

# --- Check 2b: retired layouts stay retired ----------------------------------
hdr "2b. Retired directory conventions absent (Jacob_Engineering.md)"
for n in $NEGATIVE_PATHS; do
  if [ -e "$JACOB_ROOT/$n" ]; then
    fail "retired layout reappeared: $n/ — Jacob_Engineering.md says this must not exist (flatten it)"
  else
    pass "still absent: $n/"
  fi
done

# --- Check 3: symlink wiring (delegate to bootstrap.sh --verify) --------------
hdr "3. Symlink wiring (scripts/bootstrap.sh --verify)"
if [ -x "$JACOB_ROOT/scripts/bootstrap.sh" ]; then
  if "$JACOB_ROOT/scripts/bootstrap.sh" --verify >/dev/null 2>&1; then pass "all tool symlinks resolve"
  else fail "wiring broken — run ./scripts/bootstrap.sh (see ./scripts/bootstrap.sh --verify)"; fi
else
  warn "scripts/bootstrap.sh not executable/found — skipping wiring check"
fi

# --- Check 4: memory index + [[links]] (the dangling-link bug) — WARN ---------
hdr "4. Memory index ↔ files & [[links]]"
if [ -d "$MEMORY_DIR" ] && [ -f "$MEMORY_DIR/MEMORY.md" ]; then
  index="$MEMORY_DIR/MEMORY.md"
  # every memory file (except MEMORY.md) is referenced in the index
  for f in "$MEMORY_DIR"/*.md; do
    base=$(basename "$f"); [ "$base" = "MEMORY.md" ] && continue
    grep -q "$base" "$index" && pass "indexed: $base" || warn "memory not in MEMORY.md index: $base"
  done
  # every [[link]] resolves to an existing <name>.md — in memory/ OR in the vault.
  # A memory note legitimately links into vault (§vault: memory = where we left
  # off, vault = the looked-up knowledge it points at). Checking only MEMORY_DIR made
  # every such cross-tier link look dangling — unity-vault-harvest.md cites
  # [[repo-local-work-ledger]], which has lived in wiki/patterns/ the whole time.
  links=$(grep -ohE '\[\[[a-z0-9-]+\]\]' "$MEMORY_DIR"/*.md 2>/dev/null | sed -E 's/\[\[([a-z0-9-]+)\]\]/\1/' | sort -u)
  for l in $links; do
    if [ -f "$MEMORY_DIR/$l.md" ]; then
      pass "link resolves: [[$l]]"
    elif [ -d "$JACOB_ROOT/vault" ] && \
         find "$JACOB_ROOT/vault" -name "$l.md" -print -quit 2>/dev/null | grep -q .; then
      pass "link resolves into vault: [[$l]]"
    else
      warn "dangling memory link: [[$l]] (no $l.md in memory/ or vault/)"
    fi
  done
else
  warn "memory dir not found ($MEMORY_DIR) — skipping (set MEMORY_DIR to override)"
fi

# --- Check 4b: references/ links inside skills & agents (dangling-doc bug) — FAIL
# Check 4 covers memory [[links]]; nothing covered the reference pointers INSIDE a
# SKILL.md. A broken one fails silently: the agent follows the pointer, hits
# file-not-found, and stalls mid-skill. Live instance when this check was added —
# unity-mcp-skill cited references/probuilder-guide.md and
# references/resources-reference.md; neither has ever existed in that folder.
# Markdown LINK syntax only — `](path)`. Skills legitimately name example paths in
# prose (a backticked `references/urp.md` used as an illustration, not a link), and matching bare paths would fail on those. Resolve against the
# PHYSICAL dir so the symlinked claude-obsidian skills, which reach sideways via
# ../wiki/references/, resolve the way an agent reading them would.
# PROMOTED TO FAIL 2026-10-01. As a warn it reported the same two unity-mcp-skill
# links for a month after a Coplay sync reverted Jacob's fix, and nobody acted —
# skills.lock.json's local_mods promised a restore that never happened. A ledger
# nobody reads is not a contract; a gate is. Occurrences were repaired to 0 in the
# same commit, so this fails only on a NEW break or a re-clobber.
hdr "4b. references/ links inside skills & agents"
refdocs=0
while IFS= read -r doc; do
  [ -f "$doc" ] || continue
  links=$(grep -oE '\]\((\.\./)*references/[A-Za-z0-9._/-]+\.md(#[A-Za-z0-9_-]+)?\)' "$doc" 2>/dev/null \
            | sed -E 's/^\]\((.*)\)$/\1/' | sort -u)
  [ -n "$links" ] || continue
  refdocs=$((refdocs+1))
  docdir=$(cd "$(dirname "$(realpath "$doc")")" && pwd)
  bad=""; n=0
  for l in $links; do
    n=$((n+1))
    f="${l%%#*}"
    if [ ! -e "$docdir/$f" ]; then bad="$bad $l"; continue; fi
    # An anchor must match a heading, slugged the way GitHub does it (lowercase,
    # punctuation dropped, spaces to hyphens, -1/-2 on repeats). A renamed heading
    # otherwise breaks the link while the file still exists. Harvested from
    # addyosmani/agent-skills validate-reference-links.js, 2026-10-10.
    if [ "$f" != "$l" ] && command -v python3 >/dev/null 2>&1; then
      python3 -I - "$docdir/$f" "${l#*#}" <<'PY' || bad="$bad $l"
import re, sys
seen, slugs = {}, set()
for line in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
    if not m: continue
    s = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
    n = seen.get(s, 0); seen[s] = n + 1
    slugs.add(s if n == 0 else f"{s}-{n}")
sys.exit(0 if sys.argv[2] in slugs else 1)
PY
    fi
  done
  label="${doc#$JACOB_ROOT/}"
  if [ -z "$bad" ]; then
    pass "refs resolve ($n): $label"
  else
    for b in $bad; do fail "dangling reference link: $label → $b"; done
  fi
done < <(find -L "$JACOB_ROOT/skills" -name SKILL.md 2>/dev/null; \
         find "$JACOB_ROOT/agents" -maxdepth 1 -name '*.md' 2>/dev/null)
[ "$refdocs" -gt 0 ] || warn "no references/ links found at all — the scan path is probably wrong"

# --- Check 5: agents present & well-formed (the Unity-agent gap) --------------
# Required agents fill the Unity identity gap; their loss is a regression.
# Every top-level agent must have a name: frontmatter line or it won't register.
hdr "5. agents/ present & well-formed"
REQUIRED_AGENTS="unity-reviewer unity-performance"
for a in $REQUIRED_AGENTS; do
  [ -f "$JACOB_ROOT/agents/$a.md" ] && pass "required agent present: $a" \
    || fail "required agent MISSING: agents/$a.md"
done
for f in "$JACOB_ROOT"/agents/*.md; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  case "$base" in AGENTS.md|README.md) continue ;; esac   # index files, not agents
  if head -5 "$f" | grep -qE '^name:[[:space:]]*[^[:space:]]'; then :
  else fail "agent has no 'name:' frontmatter (won't register): agents/$base"; fi
done

# --- Check 6: RETIRED 2026-10-01 (code-review-graph cut) -----------------------
# The tool was removed: vendor/, the graph, the skill, the MCP entry and the
# bootstrap venv all went with it. Its graph had indexed only Jacob itself
# (4,630 nodes, zero .cs) in two and a half months. The number stays unused
# rather than renumbering 7-22, matching the ruleset's retired-section rule.

# --- Check 7: rules/MODEL_POLICY.md + agent model IDs ------------------------------
# rules/MODEL_POLICY.md is a reference register of model IDs per CLI. Validate the one
# thing that is Jacob-side: every agent `model:` token is a real Claude model ID.
# The register documents Claude's roster only, so that is all there is to check.
hdr "7. Model register ↔ valid model IDs"
MODEL_POLICY="$JACOB_ROOT/rules/MODEL_POLICY.md"
# Claude allowlist: canonical IDs + short aliases + inherit. Keep in sync with
# rules/MODEL_POLICY.md's Claude roster table.
model_ok() {
  case "$1" in
    claude-opus-5-5|claude-opus-5|claude-opus-4-8|claude-sonnet-5-5|claude-sonnet-5|claude-haiku-4-5-20251001|claude-fable-5-1|claude-fable-5) return 0 ;;
    opus|sonnet|haiku|fable|inherit) return 0 ;;
    *) return 1 ;;
  esac
}
if [ -f "$MODEL_POLICY" ]; then
  pass "rules/MODEL_POLICY.md present"
  # Validate every editable agent's model: token (category no longer enforced).
  for f in "$JACOB_ROOT"/agents/*.md; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    case "$base" in AGENTS.md|README.md) continue ;; esac
    m=$(awk '/^---/{c++} c==1 && /^model:/{sub(/^model:[[:space:]]*/,""); gsub(/["\047[:space:]]/,""); print; exit} c==2{exit}' "$f")
    [ -z "$m" ] && continue   # no model: = vendored/symlinked, inherits default (fine)
    if ! model_ok "$m"; then
      fail "agent has UNKNOWN model '$m': agents/$base (not in rules/MODEL_POLICY.md allowlist)"
    else
      pass "agent model ok: $base (model=$m)"
    fi
  done
  # Validate the Claude IDs cited in the policy.
  # `\<claude-` anchors on a word boundary so a name that merely contains the
  # substring isn't parsed as a model ID. Two exclusions follow: anything ending
  # in a file extension, and anything followed by `/`, which makes it a path
  # segment (skills/some-claude-named-dir/...) rather than a model ID.
  for id in $(grep -oE '\bclaude-[a-z0-9.-]+/?' "$MODEL_POLICY" | grep -vE '\.(sh|md|json|py)$|/$' | sort -u); do
    if model_ok "$id"; then pass "policy cites valid Claude model: $id"
    else fail "rules/MODEL_POLICY.md cites UNKNOWN Claude model id: $id"; fi
  done
else
  fail "missing $MODEL_POLICY (model policy — see rules/Jacob_Engineering.md §spine)"
fi

# --- Check 8: MCP servers merged into each tool's user config ----------------
# Jacob owns a canonical MCP def (mcp/servers.json) that bootstrap.sh merges into
# Claude Code's USER-level config (deliberate override of the per-project default,
# see AGENTS.md §workspace and §frameworks). FAIL if a declared server is missing from the
# config — that means bootstrap wasn't run or the config drifted.
hdr "8. MCP servers ↔ Claude config"
MCP_SERVERS_FILE="$JACOB_ROOT/mcp/servers.json"
CLAUDE_JSON="${CLAUDE_JSON:-$HOME/.claude.json}"
if [ -f "$MCP_SERVERS_FILE" ]; then
  if command -v jq >/dev/null 2>&1; then
    for m in $(jq -r 'keys[]' "$MCP_SERVERS_FILE"); do
      jq -e --arg m "$m" '.mcpServers[$m]' "$CLAUDE_JSON" >/dev/null 2>&1 && pass "Claude MCP: $m" || fail "Claude MCP missing: $m (run ./bootstrap.sh)"
    done
    # A project-scoped server (.projects[<path>].mcpServers) that points at the same endpoint as
    # a Jacob server loads every tool schema twice. Coplay's Unity window writes one named
    # 'UnityMCP'. Names differ by design, so match the endpoint: URL, or command plus args.
    # Normalized: lowercase, trailing slash stripped, localhost -> 127.0.0.1. NOT normalized:
    # other hosts or ports, command paths, argument order. WARN only: Coplay rewrites it itself.
    dups=$(jq -r --slurpfile jac "$MCP_SERVERS_FILE" '
      def ep: if .url then (.url|ascii_downcase|sub("//localhost";"//127.0.0.1")|sub("/+$";""))
              elif .command then ([.command]+(.args//[])|join(" "))
              else empty end;
      ($jac[0]|to_entries|map({k:.key,e:(.value|ep)})|map(select(.e!=null))) as $j
      | (.projects//{})|to_entries[] | .key as $p
      | (.value.mcpServers//{})|to_entries[] | .key as $n | (.value|ep) as $e
      | $j[]|select(.e==$e) | [$p,$n,.k,(if ($e|test("^https?:")) then "URL" else "command" end)]|@tsv
    ' "$CLAUDE_JSON" 2>/dev/null)
    if [ -n "$dups" ]; then
      while IFS=$'\t' read -r dp dn dj dk; do
        warn "project-scoped MCP '$dn' in $dp duplicates Jacob's '$dj' (same $dk)
      Remove it: claude mcp remove $dn -s local   (run from $dp)"
      done <<EOF
$dups
EOF
    else
      pass "no project-scoped MCP server duplicates a Jacob server"
    fi
  else
    warn "jq not installed — cannot verify MCP server wiring"
  fi
else
  warn "mcp/servers.json absent — no MCP servers declared"
fi

# --- Check 9: Superpowers plugin installation --------------------------------
# Superpowers is a companion process framework. bootstrap.sh installs it through
# the Claude marketplace; there is no local clone. FAIL if it is absent or
# registered-but-not-enabled — run ./bootstrap.sh to repair.
hdr "9. Superpowers plugin"

# Claude Code plugin registration
if [ -f "$CLAUDE_PLUGINS_JSON" ]; then
  if command -v jq >/dev/null 2>&1; then
    if jq -e --arg k "$SUPERPOWERS_PLUGIN_KEY" '.plugins | has($k)' "$CLAUDE_PLUGINS_JSON" >/dev/null 2>&1; then
      pass "claude plugin: $SUPERPOWERS_PLUGIN_KEY"
    else
      fail "claude plugin NOT registered: $SUPERPOWERS_PLUGIN_KEY (run ./bootstrap.sh)"
    fi
  else
    warn "jq not installed — cannot verify claude plugin registration"
  fi
else
  warn "claude plugins registry absent: $CLAUDE_PLUGINS_JSON (run ./bootstrap.sh)"
fi

# --- Check 10: agent tool grants (least privilege, §agent-engineering) ----------------------
# §agent-engineering mandates the minimum tools: grant per agent; a blanket '*' wildcard is a
# privilege footgun. FAIL on a wildcard grant; WARN if an agent has no explicit
# grant at all (inherits ALL tools). Turns the rule from honor-system into a gate.
hdr "10. Agent tool grants (least privilege, §agent-engineering)"
for f in "$JACOB_ROOT"/agents/*.md; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  case "$base" in AGENTS.md|README.md) continue ;; esac
  tools=$(awk '/^---[[:space:]]*$/{c++; next} c==1 && /^tools:/{sub(/^tools:[[:space:]]*/,""); print; exit} c>=2{exit}' "$f")
  if [ -z "$tools" ]; then
    warn "agents/$base has no explicit tools: — inherits ALL tools (§agent-engineering least privilege)"
  elif printf '%s' "$tools" | grep -qE '(^|[^A-Za-z0-9])\*'; then
    fail "agents/$base grants a blanket tool wildcard (tools: $tools) — §agent-engineering: enumerate the minimum"
  else
    pass "agent tool grant scoped: $base"
  fi
done

# --- Check 11: §-anchors resolve to real governance headings -----------------
# The ruleset and its three gated rules files are cited from ~60 governance
# files. Until 2026-10-04 those citations were SECTION NUMBERS, and the only way
# to tell "master ruleset section 4" from "Jacob_Layout.md section 4" was a
# heuristic: a line naming a .md file was assumed to cite that file, so the line
# was skipped. That skipped 166 of 668 references, and 7 of those 166 were
# broken — including this very file citing a retired section of the ruleset for
# the model register, the exact rot the old check was written to catch.
#
# Numbers are gone. The master ruleset owns prefix-free names, and every other
# document prefixes its own (written here without the section sign, so this
# comment cannot trip the check it documents):
#   performance              AGENTS.md
#   engineering/model-register   rules/Jacob_Engineering.md
#   layout/spine                 rules/Jacob_Layout.md
#   archive/anchor-map           vault/wiki/meta/jacob-ruleset-archive.md
# Anchors are declared on the heading itself, in braces, so the headings are the
# single source of truth and nothing can drift out of sync. A bare numeric
# citation is now meaningless and is reported.
#
# ANCHOR_WARN_ONLY=1 keeps bare numerics at warn during a migration.
hdr "11. §-anchors resolve to governance headings"
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 missing — cannot validate §-anchors"
elif [ ! -f "$RULESET" ]; then
  fail "missing $RULESET — cannot validate §-anchors"
else
  anchor_out=$(cd "$JACOB_ROOT" && ANCHOR_WARN_ONLY="${ANCHOR_WARN_ONLY:-0}" python3 - <<'PY'
import os, re, glob, sys

WARN_ONLY = os.environ.get("ANCHOR_WARN_ONLY") == "1"

# Documents that may declare anchors, and the namespace each one owns.
# The master ruleset owns the PREFIX-FREE namespace (behavior, performance).
# Everything else is prefixed. A prefix is therefore a reserved word: a bare
# 'layout' would be ambiguous with the layout/ namespace, so it is rejected.
ANCHOR_DOCS = {
    "AGENTS.md": "",
    "rules/Jacob_Engineering.md": "engineering",
    "rules/Jacob_Layout.md": "layout",
    "vault/wiki/meta/jacob-ruleset-archive.md": "archive",
}
RESERVED = {ns for ns in ANCHOR_DOCS.values() if ns}
# Aliases: one name for a block of sections that is always cited together.
ALIASES = {"code": ["naming", "performance", "architecture", "frameworks"]}

HEADING = re.compile(r"^#{1,4}\s+.*\{#([a-z][a-z0-9-]*(?:/[a-z0-9-]+)*)\}\s*$")
REF     = re.compile(r"§([a-z][a-z0-9-]*(?:/[a-z0-9-]+)*)")  # a slug, or a namespace/slug
BARE    = re.compile(r"§\d")

anchors, dupes, misowned = {}, [], []
for doc, ns in ANCHOR_DOCS.items():
    if not os.path.isfile(doc):
        continue
    for i, line in enumerate(open(doc, encoding="utf-8", errors="replace"), 1):
        m = HEADING.match(line.rstrip())
        if not m:
            continue
        a = m.group(1)
        if a in anchors:
            dupes.append(f"{a} ({anchors[a]} and {doc}:{i})")
        anchors[a] = f"{doc}:{i}"
        head = a.split("/")[0]
        if ns and head != ns:
            misowned.append(f"{doc}:{i} declares {a}, but that file owns the '{ns}/' namespace")
        elif not ns and head in RESERVED:
            misowned.append(f"{doc}:{i} declares {a}, but '{head}' is a reserved namespace prefix")

for alias, targets in ALIASES.items():
    missing = [t for t in targets if t not in anchors]
    if missing:
        print("FAIL\talias §%s expands to missing anchor(s): %s" % (alias, ", ".join(missing)))
    else:
        anchors[alias] = "alias"

# Files that may CITE anchors.
scope = ["AGENTS.md", "README.md"]
scope += sorted(glob.glob("rules/*.md")) + sorted(glob.glob("rules/output-styles/*.md"))
scope += sorted(glob.glob("commands/*.md")) + sorted(glob.glob("agents/*.md"))
scope += sorted(glob.glob("scripts/*.sh")) + sorted(glob.glob("scripts/evals/*"))
scope += sorted(glob.glob("skills/**/*.md", recursive=True))

# A `track` skill is re-pulled verbatim from upstream, so its prose is not Jacob's
# to rewrite. Upstream files carry their OWN section numbers (ui-ux-pro-max cites
# its quick-reference.md by number), and converting those to Jacob anchors both
# corrupts the vendored text and is undone by the next refresh. Skip them.
try:
    import json
    lock = json.load(open("skills/skills.lock.json"))["skills"]
    vendored = {"skills/%s/" % n for n, v in lock.items()
                if v.get("update_policy") == "track"}
    scope = [f for f in scope if not any(f.startswith(v) for v in vendored)]
except Exception:
    pass  # no lock file is Check 7's problem, not this check's

for d in dupes:
    print("FAIL\tduplicate anchor: %s" % d)
for m in misowned:
    print("FAIL\t%s" % m)

ok = bare = 0
for f in scope:
    if not os.path.isfile(f):
        continue
    for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        if HEADING.match(line.rstrip()):
            continue  # a declaration, not a citation
        for a in REF.findall(line):
            if a in anchors:
                ok += 1
            else:
                print("FAIL\t%s:%d cites §%s — no such anchor" % (f, i, a))
        if BARE.search(line):
            bare += 1
            label = "WARN" if WARN_ONLY else "FAIL"
            print("%s\t%s:%d still cites a bare section number: %s"
                  % (label, f, i, line.strip()[:90]))
print("OK\t%d anchors declared, %d citations resolve, %d bare numeric line(s)"
      % (len([a for a in anchors if a not in ALIASES]), ok, bare))
PY
  )
  while IFS=$'\t' read -r verdict msg; do
    case "$verdict" in
      FAIL) fail "$msg" ;;
      WARN) warn "$msg" ;;
      OK)   pass "$msg" ;;
    esac
  done <<< "$anchor_out"
fi

# --- Check 12: skill/agent frontmatter parses and can actually route ----------
# §agent-engineering: "The description: is load-bearing — it is the entire signal for firing a skill
# or routing to an agent." Nothing checked that the field is even READABLE. It had
# already rotted: skills/unity-system-design declared its description as an unquoted
# plain scalar containing ": " ("...any of these: save/load"), which is invalid YAML.
# Claude Code's parser is lenient and papered over it; a strict one drops the whole
# frontmatter, and a skill with no description cannot route at all. Caught 2026-08-27
# by scripts/evals/build-roster.py, which is the same parse this check runs.
#
# Also warns when frontmatter name: differs from the directory. The harness routes and
# lists by DIRECTORY, so a divergent name: is a decoy: skills/code-review-standards/
# declares name: code-review (which also collides with the built-in /code-review), and
# skills/unity-mcp-skill/ declares unity-mcp-orchestrator. Nothing breaks today, but it
# sent this very eval chasing the wrong expected value. WARN, not fail — the fix is a
# rename someone has to choose, not something doctor should force.
hdr "12. Skill/agent frontmatter parses (description is the routing signal, §agent-engineering)"
if command -v python3 >/dev/null 2>&1; then
  fm_out=$(cd "$JACOB_ROOT" && python3 - <<'PY' 2>/dev/null
import pathlib, sys
try:
    import yaml
except ImportError:
    print("SKIP no PyYAML"); sys.exit(0)
root = pathlib.Path('.')
checked = 0
for p in sorted(list(root.glob('skills/*/SKILL.md')) + list(root.glob('agents/*.md'))):
    if p.name == 'AGENTS.md':
        continue
    checked += 1
    t = p.read_text(encoding='utf-8', errors='replace')
    if not t.startswith('---'):
        print(f"FAIL {p}: no YAML frontmatter"); continue
    end = t.find('\n---', 3)
    if end == -1:
        print(f"FAIL {p}: unterminated frontmatter"); continue
    try:
        d = yaml.safe_load(t[3:end])
    except yaml.YAMLError as ex:
        first = str(ex).split('\n')[0]
        print(f"FAIL {p}: invalid YAML ({first}) — quote it or use a '>-' block")
        continue
    if not isinstance(d, dict):
        print(f"FAIL {p}: frontmatter is not a mapping"); continue
    if not str(d.get('description') or '').strip():
        print(f"FAIL {p}: empty/missing description — cannot route (§agent-engineering)")
    # Agents auto-dispatch on description match (§invocation "Agents fire on their own"),
    # so a role-only description ("The X does Y.") is silently inert: it says what
    # the agent IS, never when to route to it. Assert a routing trigger.
    if p.parent.name == 'agents':
        desc = str(d.get('description') or '').lower()
        if not any(k in desc for k in
                   ('use when', 'use for', 'use after', 'use this agent',
                    '<example>', 'triggers:')):
            print(f"WARN {p}: description has no routing trigger — add 'Use when ...' "
                  f"or 'Triggers: ...' or it will never auto-fire (§invocation, §agent-engineering)")
    if not str(d.get('name') or '').strip():
        print(f"FAIL {p}: empty/missing name")
    elif p.name == 'SKILL.md' and str(d['name']).strip() != p.parent.name:
        print(f"WARN {p}: frontmatter name '{d['name']}' != directory "
              f"'{p.parent.name}' — the harness routes by DIRECTORY, so the "
              f"name: field is a decoy; rename one to match")
print(f"OK {checked}")
PY
)
  if printf '%s' "$fm_out" | grep -q '^SKIP'; then
    warn "PyYAML not installed — cannot validate skill/agent frontmatter"
  else
    while IFS= read -r l; do
      case "$l" in
        FAIL*) fail "${l#FAIL }" ;;
        WARN*) warn "${l#WARN }" ;;
        OK*)   pass "all ${l#OK } skill/agent frontmatter blocks parse with a non-empty description" ;;
      esac
    done <<< "$fm_out"
  fi
else
  warn "python3 not installed — cannot validate skill/agent frontmatter"
fi

# --- 13. claude-obsidian comes from the plugin, and vault/ stays data ---------
# Until 2026-10-01 Jacob vendored the product tree at vendor/claude-obsidian/ and
# symlinked 15 skills out of it, because plugin-install was believed to trigger an
# auto-commit hook. It does not: hooks.json registers only SessionStart and Stop,
# both of which dispatch to hook_adapter.py, a file with no subprocess call, no
# git, and no writes. The tree is gone and the plugin owns the skills.
# Two invariants survive the move. The 15 names must NOT reappear as real
# directories under skills/, because a second copy beside the plugin's is exactly
# the drift the old symlink rule existed to prevent. And vault/ must never regain
# a product tree, since 2.x refuses to run when its own install root is the
# selected vault (claude_obsidian/paths.py PLUGIN_ROOT_IS_NOT_VAULT).
# Vendoring history: vault/MAINTENANCE.md.
hdr "13. claude-obsidian owned by the plugin, vault/ data only"
CO_SKILLS="autoresearch canvas defuddle obsidian-bases obsidian-markdown save think wiki wiki-cli wiki-fold wiki-ingest wiki-lint wiki-mode wiki-query wiki-retrieve"
co_bad=0
for co_name in $CO_SKILLS; do
  if [ -e "$JACOB_ROOT/skills/$co_name" ] || [ -L "$JACOB_ROOT/skills/$co_name" ]; then
    fail "skills/$co_name is back on the spine — the claude-obsidian plugin owns it since 2026-10-01, and a second copy drifts silently (see vault/MAINTENANCE.md)"
    co_bad=$((co_bad+1))
  fi
done
[ "$co_bad" -eq 0 ] && pass "none of the 15 claude-obsidian skills shadow the plugin"
if [ -d "$JACOB_ROOT/vendor/claude-obsidian" ]; then
  fail "vendor/claude-obsidian/ is back — the plugin owns the product tree; re-vendoring reintroduces two copies"
else
  pass "no vendored claude-obsidian product tree"
fi
# The plugin must be installed AND enabled; registration alone does not activate it.
CO_KEY="claude-obsidian@agricidaniel-claude-obsidian"
if command -v jq >/dev/null 2>&1 && [ -f "$CLAUDE_PLUGINS_JSON" ]; then
  if jq -e --arg k "$CO_KEY" '.plugins | has($k)' "$CLAUDE_PLUGINS_JSON" >/dev/null 2>&1; then
    pass "claude plugin installed: $CO_KEY"
  else
    fail "claude plugin NOT installed: $CO_KEY (15 wiki/obsidian skills are unreachable)"
  fi
  if jq -e --arg k "$CO_KEY" '.enabledPlugins[$k] == true' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
    pass "claude plugin enabled: $CO_KEY"
  else
    fail "claude plugin installed but NOT enabled: $CO_KEY"
  fi
fi
if [ -d "$JACOB_ROOT/vault/skills" ] || [ -d "$JACOB_ROOT/vault/claude_obsidian" ]; then
  fail "vault/ contains product code — 2.x refuses a vault that is its own install tree (PLUGIN_ROOT_IS_NOT_VAULT)"
else
  pass "vault/ holds data only (no product tree)"
fi
# The vault pin. Jacob's skills run from SIBLING project directories, where the
# plugin's implicit discovery finds nothing, so CLAUDE_OBSIDIAN_VAULT is the only
# durable selector. It is a machine-local settings.json key and does not survive a
# clone; bootstrap writes it. Without it the skills fail closed on an ambiguous
# vault, which reads as "the skill is broken" rather than "the pin is missing".
if command -v jq >/dev/null 2>&1 && [ -f "$CLAUDE_SETTINGS" ]; then
  co_vault=$(jq -r '.env.CLAUDE_OBSIDIAN_VAULT // ""' "$CLAUDE_SETTINGS" 2>/dev/null)
  if [ "$co_vault" = "$JACOB_ROOT/vault" ]; then
    pass "CLAUDE_OBSIDIAN_VAULT pinned to $co_vault"
  elif [ -n "$co_vault" ]; then
    warn "CLAUDE_OBSIDIAN_VAULT is '$co_vault', not $JACOB_ROOT/vault — deliberate?"
  else
    fail "CLAUDE_OBSIDIAN_VAULT unset — the 15 wiki skills cannot find the vault from a sibling project (run ./scripts/bootstrap.sh)"
  fi
fi

# --- Check 14: no credentials in the committed memory journals ---------------
# .memsearch/memory/*.md is git-tracked and pushed to a public remote (§workspace), and
# its content is written by an LLM summarizing raw transcripts — so a key pasted
# into a session can reach the remote. scripts/memsearch/summarize.txt tells the
# summarizer to omit secrets, but that is a prompt, not a guarantee (§agent-engineering: if it
# must run reliably it is a hook, not a probability). This is the deterministic
# half. FAIL, not WARN: a pushed credential cannot be un-pushed.
hdr "14. No credentials in committed memsearch journals"
if [ -d "$JACOB_ROOT/.memsearch" ]; then
  # name → ERE, bash-3.2 safe (no associative arrays)
  # Every pattern is left-anchored on a non-token char so a key-shaped substring
  # inside a longer slug is not a hit: references/UniTask_Documentation.md
  # carries a Medium URL ending "...unitask-v2-zero-allocation-...-1aa9c96aa7dd",
  # which an unanchored sk- pattern reports as an OpenAI key on every run.
  # Each pattern is tested independently, so ordering does not matter here (a
  # consuming scanner would need sk-ant- before sk-; this one does not).
  # The set past slack-token was widened 2026-09-27 from the hindsight triage:
  # its Memory Defense extension carried 45 patterns against this check's 8.
  # Deliberately NOT taken: aws_secret_key needs (?i), which one shared grep -qE
  # cannot express without flipping case for every pattern; credit_card and
  # ssn_us are noise in engineering transcripts, and their Luhn check exists
  # only because digit count alone redacted timestamps and port lists.
  secret_patterns='google-api-key:(^|[^A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}
anthropic-key:(^|[^A-Za-z0-9_-])sk-ant-[0-9A-Za-z_-]{24,}
openai-key:(^|[^A-Za-z0-9_-])sk-(proj-)?[A-Za-z0-9]{20,}
vendor-key:(^|[^A-Za-z0-9_-])sk-[A-Za-z0-9]{8,}(-[A-Za-z0-9]{4,}){1,3}
github-token:(^|[^A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{36}
aws-access-key:(^|[^A-Za-z0-9_-])AKIA[0-9A-Z]{16}
slack-token:(^|[^A-Za-z0-9_-])xox[baprs]-[0-9A-Za-z-]{10,}
github-fine-grained-pat:(^|[^A-Za-z0-9_-])github_pat_[A-Za-z0-9_]{60,}
gitlab-pat:(^|[^A-Za-z0-9_-])glpat-[A-Za-z0-9_-]{20,}
npm-token:(^|[^A-Za-z0-9_-])npm_[A-Za-z0-9]{30,}
groq-key:(^|[^A-Za-z0-9_-])gsk_[A-Za-z0-9]{20,}
xai-key:(^|[^A-Za-z0-9_-])xai-[A-Za-z0-9]{40,}
huggingface-token:(^|[^A-Za-z0-9_-])hf_[A-Za-z0-9]{30,}
perplexity-key:(^|[^A-Za-z0-9_-])pplx-[A-Za-z0-9]{40,}
google-oauth-token:(^|[^A-Za-z0-9_-])ya29\.[0-9A-Za-z_-]{20,}
aws-session-key:(^|[^A-Za-z0-9_-])ASIA[0-9A-Z]{16}
stripe-secret:(^|[^A-Za-z0-9_-])(sk|rk)_(live|test)_[A-Za-z0-9]{20,}
jwt:(^|[^A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}
db-url-with-creds:(postgres(ql)?|mysql|mongodb(\+srv)?)://[^[:space:]:/@]+:[^[:space:]/@]+@
private-key-block:-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----'
  scanned=0; hits=0
  while IFS= read -r mf; do
    [ -f "$mf" ] || continue
    scanned=$((scanned+1))
    while IFS= read -r entry; do
      [ -n "$entry" ] || continue
      pname="${entry%%:*}"; prx="${entry#*:}"
      if grep -qE "$prx" "$mf" 2>/dev/null; then
        fail "$pname found in ${mf#$JACOB_ROOT/} — this file is committed and pushed; scrub it before committing"
        hits=$((hits+1))
      fi
    done <<< "$secret_patterns"
  done <<< "$(find "$JACOB_ROOT/.memsearch" -name '*.md' -type f 2>/dev/null)"
  if [ "$scanned" -eq 0 ]; then
    skip "no memsearch journals on disk yet"
  elif [ "$hits" -eq 0 ]; then
    pass "$scanned memsearch journal file(s) clean of known credential patterns"
  fi
  # The prompt-side half must actually be wired, or only this gate is protecting us.
  sp="$(memsearch config get prompts.summarize 2>/dev/null || true)"
  if [ -n "$sp" ] && [ -f "$sp" ]; then
    pass "redaction summarize prompt wired: ${sp#$JACOB_ROOT/}"
  else
    warn "prompts.summarize not wired to Jacob's redaction prompt — run: memsearch config set prompts.summarize $JACOB_ROOT/scripts/memsearch/summarize.txt"
  fi
else
  skip "no .memsearch/ in $JACOB_ROOT"
fi
# --- Check 15: Claude Code output style is active -----------------------------
# §behavior's register + answer-shape rules have their canonical home in
# rules/output-styles/<name>.md, which Claude Code loads as its own prompt block. The
# FILE lives in Jacob and is symlinked; the ACTIVATION is a machine-local
# settings.json key. So a fresh clone ships the style inert and nothing else
# notices. That silent-no-op is exactly the drift this script exists to catch.
# Measure the effect with scripts/evals/register-check.py.
hdr "15. Claude Code output style active"
style_file="$JACOB_ROOT/rules/output-styles/$JACOB_OUTPUT_STYLE.md"
if [ ! -f "$style_file" ]; then
  fail "style file missing: rules/output-styles/$JACOB_OUTPUT_STYLE.md (§behavior canonical home)"
else
  pass "style file present: rules/output-styles/$JACOB_OUTPUT_STYLE.md"

  # The symlink must exist or Claude Code cannot see the file at all.
  if [ -L "$HOME/.claude/output-styles" ]; then
    pass "output-styles symlinked into ~/.claude"
  elif [ -d "$HOME/.claude/output-styles" ]; then
    warn "~/.claude/output-styles is a real dir, not a symlink to Jacob (run ./scripts/bootstrap.sh)"
  else
    fail "~/.claude/output-styles not wired (run ./scripts/bootstrap.sh)"
  fi

  # And the settings key must select it, or the file is inert.
  if [ ! -f "$CLAUDE_SETTINGS" ]; then
    warn "claude settings absent: $CLAUDE_SETTINGS (run ./scripts/bootstrap.sh)"
  elif ! command -v jq >/dev/null 2>&1; then
    warn "jq not installed — cannot verify outputStyle activation"
  else
    cur_style=$(jq -r '.outputStyle // ""' "$CLAUDE_SETTINGS" 2>/dev/null)
    if [ "$cur_style" = "$JACOB_OUTPUT_STYLE" ]; then
      pass "outputStyle active: $JACOB_OUTPUT_STYLE"
    elif [ -z "$cur_style" ]; then
      fail "outputStyle unset — style file is inert (run ./scripts/bootstrap.sh)"
    else
      warn "outputStyle is '$cur_style', not '$JACOB_OUTPUT_STYLE' — deliberate? switch via /config"
    fi
  fi
fi

# --- Check 16: transcript provenance is still reachable -----------------------
# Every .memsearch/memory/ entry carries a `transcript:<path>.jsonl` backlink to
# the raw session it summarizes. Claude Code deletes ~/.claude/projects/*.jsonl
# after 30 days, so those backlinks rot on a clock and NOTHING reports it — the
# journal keeps reading fine while its evidence disappears underneath. Measured
# 2026-09-07: 115 of 148 pointers already dead. scripts/backup-transcripts.sh is
# the fix; this check is what makes the next loss loud instead of silent.
# WARN, not FAIL: a dead pointer is unrecoverable, so failing the commit gate
# would block on history nobody can change.
hdr "16. Transcript provenance reachable"
TRANSCRIPT_ARCHIVE="${JACOB_TRANSCRIPT_ARCHIVE:-$HOME/Documents/Claude_Transcripts}"
if [ ! -d "$JACOB_ROOT/.memsearch/memory" ]; then
  skip "no memsearch journals on disk yet"
else
  # Basename index of the archive, built once. A pointer counts as reachable if
  # its session file survives EITHER live or in the archive.
  arch_idx=""
  [ -d "$TRANSCRIPT_ARCHIVE" ] && \
    arch_idx="$(find "$TRANSCRIPT_ARCHIVE" -type f -name '*.jsonl' -exec basename {} \; 2>/dev/null)"
  # Journals dated on or before this cutoff lost their sessions before the
  # archive existed. That loss is permanent, so it reports as a pass line;
  # only a dead link from a later journal warns. A warning that can never clear
  # would hide the next loss instead of making it loud.
  TRANSCRIPT_LOSS_CUTOFF="2026-07-24"
  t_total=0; t_dead=0; t_saved=0; t_known=0
  while IFS=' ' read -r jdate tp; do
    [ -n "$tp" ] || continue
    t_total=$((t_total+1))
    [ -f "$tp" ] && continue                       # still live
    if [ -n "$arch_idx" ] && printf '%s\n' "$arch_idx" | grep -qxF "${tp##*/}"; then
      t_saved=$((t_saved+1))                       # gone live, held by the archive
    elif [[ ! "$jdate" > "$TRANSCRIPT_LOSS_CUTOFF" ]]; then
      t_known=$((t_known+1))                       # lost before the archive began
    else
      t_dead=$((t_dead+1))
    fi
  # Archived journals (fold-journals.sh) keep their backlinks and must stay in
  # scope, or folding a month would silently shrink this check's coverage.
  # Each line is "<journal date> <transcript path>", deduped on the path.
  done <<< "$(grep -o 'transcript:[^ ]*\.jsonl' \
                "$JACOB_ROOT"/.memsearch/memory/*.md \
                "$JACOB_ROOT"/.memsearch/archive/*/*.md 2>/dev/null \
              | sed -E 's|^.*/([0-9]{4}-[0-9]{2}-[0-9]{2})[^/]*\.md:transcript:|\1 |' \
              | sort -u -k2,2)"
  if [ "$t_total" -eq 0 ]; then
    skip "no transcript: backlinks in the journals"
  elif [ "$t_dead" -eq 0 ]; then
    pass "$t_total transcript backlink(s) checked: $t_saved via archive, $t_known known-lost before the archive (journals ≤ $TRANSCRIPT_LOSS_CUTOFF)"
  else
    warn "$t_dead transcript backlink(s) newly unrecoverable (journals after $TRANSCRIPT_LOSS_CUTOFF) — summary survives, verbatim source does not"
  fi
  # Archive freshness. A stale archive means the 30-day clock is winning again.
  if [ ! -d "$TRANSCRIPT_ARCHIVE" ]; then
    warn "no transcript archive at $TRANSCRIPT_ARCHIVE — run ./scripts/backup-transcripts.sh"
  else
    live_n=$(find "$HOME/.claude/projects" -type f -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
    arch_n=$(printf '%s\n' "$arch_idx" | grep -c . || true)
    if [ "$arch_n" -ge "$live_n" ] && [ "$live_n" -gt 0 ]; then
      pass "transcript archive holds $arch_n session(s), $live_n live"
    else
      warn "transcript archive behind ($arch_n archived vs $live_n live) — run ./scripts/backup-transcripts.sh"
    fi
  fi
fi

# --- Check 17: vault pages carry a staleness handle ---------------------------
# §vault: "the vault lags the code; the code wins." That is a rule with no
# mechanism — a page cannot be judged stale without a date to judge it by. All
# 62 pages carry `updated:` today (measured 2026-09-07), so this is a REGRESSION
# GUARD, not a repair: wiki-lint's stale-page rule reads that field, and a new
# page authored without it would be silently exempt from the lint. This checks
# only that the handle exists; the code-vs-page comparison is wiki-lint's.
hdr "17. Vault pages carry updated: frontmatter"
if [ ! -d "$JACOB_ROOT/vault/wiki" ]; then
  skip "no vault/wiki/"
else
  v_total=0; v_missing=0; v_names=""
  while IFS= read -r vp; do
    [ -f "$vp" ] || continue
    head -1 "$vp" | grep -q '^---$' || continue    # no frontmatter block at all
    v_total=$((v_total+1))
    awk '/^---$/{n++; next} n==1 && /^updated:/{found=1} END{exit !found}' "$vp" && continue
    v_missing=$((v_missing+1)); v_names="$v_names ${vp##*/}"
  done <<< "$(find "$JACOB_ROOT/vault/wiki" -name '*.md' -type f 2>/dev/null)"
  if [ "$v_total" -eq 0 ]; then
    skip "no wiki pages with frontmatter"
  elif [ "$v_missing" -eq 0 ]; then
    pass "all $v_total frontmatter page(s) carry updated:"
  else
    warn "$v_missing of $v_total frontmatter page(s) missing updated: —$v_names"
  fi
fi

# --- Check 18: ruleset fits the 40,000-character limit ------------------------
# Some models Jacob runs under expect a rules file under 40,000 characters, and
# the ruleset is resident in all three tools. Characters, not bytes: its arrows
# and em-dashes are multi-byte, so `wc -c` overstates the count. Warn from 38,000
# so shrinking headroom shows up before a commit is blocked.
hdr "18. Ruleset under 40,000 characters"
if [ -f "$RULESET" ]; then
  r_chars=$(python3 -c 'import sys; print(len(open(sys.argv[1], encoding="utf-8").read()))' "$RULESET" 2>/dev/null)
  if [ -z "$r_chars" ]; then
    warn "could not count ruleset characters (python3 missing?)"
  elif [ "$r_chars" -ge 40000 ]; then
    fail "AGENTS.md is $r_chars characters — limit is 40,000. Move detail into a gated rules/ doc."
  elif [ "$r_chars" -ge 38000 ]; then
    warn "AGENTS.md is $r_chars characters — under the 40,000 limit but past the 38,000 warning line"
  else
    pass "AGENTS.md is $r_chars characters (limit 40,000)"
  fi
fi

# --- Check 19: memsearch index matches the files on disk — WARN --------------
# Found 2026-09-27: 811 chunks across 61 files that no longer existed, 23% of the
# whole index, left behind by the obsidian-vault -> vault rename. Indexing cannot
# evict them, because core.py:130 prunes only inside directory roots from that run
# and reindex.sh passes one file at a time. Every vault search competed against
# them. WARN, not fail: the Milvus store is machine-local and gitignored, so a
# commit must never be gated on derived state. Fix with scripts/memsearch/reindex.sh.
hdr "19. memsearch index matches files on disk"
if [ ! -f "$JACOB_ROOT/scripts/memsearch/prune-orphans.py" ]; then
  skip "prune-orphans.py not present"
elif ! ms_py="$("$JACOB_ROOT/scripts/memsearch/ms-python.sh")"; then
  skip "pymilvus not importable — cannot read the index"
else
  # Capture the script's own exit code, not the pipeline's last stage.
  idx_raw=$("$ms_py" "$JACOB_ROOT/scripts/memsearch/prune-orphans.py" --check 2>/dev/null)
  idx_rc=$?
  idx_out=$(printf '%s\n' "$idx_raw" | grep -v '^  ' | head -2 | tr '\n' ' ')
  if [ "$idx_rc" -eq 0 ]; then
    pass "${idx_out:-index clean}"
  else
    warn "${idx_out:-index drift} — run scripts/memsearch/reindex.sh"
  fi
fi

# --- Check 20: wiki/hot.md stays inside its word budget — WARN ---------------
# hot.md is rung 1 of the §vault escalation ladder, so it is read before anything
# else in the vault and its cost lands on every walk. A 500-word ceiling has been
# the working rule since at least 2026-08-30, but it lived only in session
# journals — an oral tradition three sessions re-derived and one session breached
# without noticing. It is now stated in hot.md's own preamble and enforced here.
# WARN, not fail: trimming it is a judgement call about which context still
# earns its place, and a commit must not be blocked waiting on that call.
hdr "20. wiki/hot.md word budget"
HOT_MAX=500
hot="$JACOB_ROOT/vault/wiki/hot.md"
if [ ! -f "$hot" ]; then
  skip "no vault/wiki/hot.md"
else
  hot_words=$(wc -w < "$hot" | tr -d ' ')
  if [ "$hot_words" -gt "$HOT_MAX" ]; then
    warn "hot.md is $hot_words words — ceiling is $HOT_MAX. Fold the oldest dated sections into wiki/log.md."
  else
    pass "hot.md is $hot_words words (ceiling $HOT_MAX)"
  fi
fi

# --- Check 21: vault pages are not lagging their source — WARN ----------------
# §vault says the vault lags the code and the code wins. scripts/vault-lag.sh is
# the only thing that measures it, and until 2026-09-28 nothing called it: the
# staleness half of the rule ran only when a human remembered to type it, while
# every other vault invariant here ran on commit. It exits 0 clean and 2 when a
# page is older than the source it documents. WARN, not fail: re-reading a page
# against source is authoring work, and a commit must not block on it.
# It also warns when no page could be checked. A green line that checked
# nothing read as clean for weeks while every root pointed at a deleted repo.
hdr "21. vault pages are not lagging source"
if [ ! -x "$JACOB_ROOT/scripts/vault-lag.sh" ]; then
  skip "scripts/vault-lag.sh not present or not executable"
else
  lag_raw=$(bash "$JACOB_ROOT/scripts/vault-lag.sh" 2>/dev/null)
  lag_sum=$(printf '%s\n' "$lag_raw" | sed -n 's/^vault-lag: //p' | head -1)
  lag_n=$(printf '%s\n' "$lag_sum" | sed -n 's/^\([0-9]*\) lagging.*/\1/p')
  if [ -z "$lag_n" ]; then
    warn "vault-lag.sh printed no summary line — run it directly"
  elif [ "$lag_n" -gt 0 ]; then
    lag_who=$(printf '%s\n' "$lag_raw" | sed -n 's/^  ✗  *\([^ ]*\).*/\1/p' | tr '\n' ' ')
    warn "$lag_sum — re-read against source, then bump updated: $lag_who"
  else
    lag_cur=$(printf '%s\n' "$lag_sum" | sed -n 's/^[0-9]* lagging, \([0-9]*\) current.*/\1/p')
    lag_unv=$(printf '%s\n' "$lag_sum" | sed -n 's/.* \([0-9]*\) unverifiable.*/\1/p')
    if [ "${lag_cur:-0}" -eq 0 ] && [ "${lag_unv:-0}" -gt 0 ]; then
      warn "$lag_sum — no page could be checked here; clone the roots in vault/.vault-meta/source-roots.json"
    else
      pass "$lag_sum"
    fi
  fi
fi

# --- Check 22: every wiki group is classified, project pages carry path: — WARN
# Check 17 proves a page carries `updated:`, the date half of the staleness rule.
# `path:` is the other half, and scripts/vault-lag.sh:34 drops any page without
# one — silently, without counting it as unverifiable. Measured 2026-09-28: both
# pages in one game's wiki group carried `updated:` and no `path:`, and the group had no
# entry in source-roots.json at all, so a whole project group sat outside the
# check while the report read "0 lagging". A group is classified by appearing in
# `roots` (a project; `null` when no checkout exists on this machine) or in
# `non_project` (knowledge-only, documenting no source tree). An unclassified
# group is the regression this guards. WARN, not fail: deciding what source a
# page documents is authoring work, same as Check 21.
hdr "22. wiki groups classified, project pages carry path:"
VMAP="$JACOB_ROOT/vault/.vault-meta/source-roots.json"
if [ ! -d "$JACOB_ROOT/vault/wiki" ]; then
  skip "no vault/wiki/"
elif [ ! -f "$VMAP" ]; then
  warn "no vault/.vault-meta/source-roots.json — every group is unclassified"
else
  vp_out=$(python3 - "$JACOB_ROOT/vault/wiki" "$VMAP" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
wiki, mapf = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads(mapf.read_text())
roots, nonproj = m.get("roots", {}), set(m.get("non_project", []))

def has_key(p, key):
    lines, seen = p.read_text(errors="replace").splitlines(), 0
    for ln in lines:
        if ln.rstrip() == "---":
            seen += 1
            if seen == 2:
                return False
            continue
        if seen == 1 and ln.startswith(key + ":"):
            return True
    return False

unclassified, missing, groups = [], [], 0
for d in sorted(p for p in wiki.iterdir() if p.is_dir() and not p.name.startswith(".")):
    g = d.name
    if g in nonproj:
        continue
    groups += 1
    if g not in roots:
        unclassified.append(g)
        continue
    for pg in sorted(d.glob("*.md")):
        if not pg.read_text(errors="replace").startswith("---"):
            continue
        if not has_key(pg, "path"):
            missing.append(f"{g}/{pg.name}")
print(f"GROUPS={groups}")
print("UNCLASSIFIED=" + ",".join(unclassified))
print("MISSING=" + ",".join(missing))
sys.exit(1 if (unclassified or missing) else 0)
PY
)
  vp_rc=$?
  vp_groups=$(printf '%s\n' "$vp_out" | sed -n 's/^GROUPS=//p')
  vp_unc=$(printf '%s\n' "$vp_out" | sed -n 's/^UNCLASSIFIED=//p')
  vp_mis=$(printf '%s\n' "$vp_out" | sed -n 's/^MISSING=//p')
  if [ -z "$vp_groups" ]; then
    warn "could not read source-roots.json or the wiki groups"
  elif [ "$vp_rc" -eq 0 ]; then
    pass "all $vp_groups project group(s) classified, every page carries path:"
  else
    [ -n "$vp_unc" ] && warn "wiki group(s) in neither roots nor non_project: $vp_unc — add to vault/.vault-meta/source-roots.json"
    [ -n "$vp_mis" ] && warn "project page(s) with no path: — invisible to vault-lag.sh: $vp_mis"
  fi
fi

# --- 23. autoharness create-bar hook wired -----------------------------------
# Without this PreToolUse entry, autoharness creates skills unjudged and nothing
# reports it: the reflector just lands whatever it stages. bootstrap writes the entry.
# Spec: docs/superpowers/specs/2026-11-06-autoharness-create-bar-design.md
hdr "23. autoharness create-bar hook wired"
if ! command -v jq >/dev/null 2>&1; then
  warn "jq not installed — cannot read $CLAUDE_SETTINGS"
else
  cb_cmd=$(jq -r '[.hooks.PreToolUse[]? | select(.matcher == "mcp__plugin_autoharness_stage_skill__stage_skill")
             | .hooks[]? | .command // "" | select(endswith("scripts/hooks/create_bar.py"))] | first // ""' \
           "$CLAUDE_SETTINGS" 2>/dev/null)
  cb_path="${cb_cmd##* }"
  if [ -z "$cb_cmd" ]; then
    fail "create-bar hook not wired; run ./scripts/bootstrap.sh"
  elif [ ! -f "$cb_path" ]; then
    fail "create-bar hook points at a missing file: $cb_path"
  else
    pass "create-bar hook wired: $cb_path"
  fi
fi

# --- Summary -----------------------------------------------------------------
hdr "Summary"
printf '%s%d fail%s, %s%d warn%s\n' "$([ "$fails" -gt 0 ] && echo "$RED" || echo "$GREEN")" "$fails" "$RESET" \
       "$([ "$warns" -gt 0 ] && echo "$YELLOW" || echo "$DIM")" "$warns" "$RESET"
[ "$fails" -eq 0 ] && printf '%shealthy%s\n' "$GREEN" "$RESET" || printf '%sneeds attention%s\n' "$RED" "$RESET"
exit $([ "$fails" -eq 0 ] && echo 0 || echo 1)
