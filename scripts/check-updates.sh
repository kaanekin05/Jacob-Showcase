#!/usr/bin/env bash
#
# check-updates.sh — read-only freshness report for Jacob's external sources.
#
# Jacob vendors, cherry-picks, and depends on things that live upstream: skills
# (skills.lock.json), Claude Code plugins (installed_plugins.json), MCP servers
# (mcp/servers.json), pip packages, and the §vault Obsidian vault environment (desktop
# app + community plugins, installed by hand with no git pin). They drift silently.
# This script asks each upstream "have you moved?". The weekly `/check-updates` engine.
#
# NOT covered, deliberately: model rosters. Claude model selection is manual and
# user-owned — this script does not inspect or grade it.
#
# It WRITES NOTHING and never mutates a pin — applying an update is a separate,
# human-gated step (see skills/check-updates/SKILL.md). Exit is always 0; this is
# a report, not a gate (that is scripts/doctor.sh's job).
#
# Signal source: `git ls-remote` (unauthenticated, un-rate-limited) for the
# "repo moved" signal; the GitHub releases API only for release-pinned entries.
# Set GITHUB_TOKEN to raise the API limit (60/hr -> 5000/hr) if you hit it.
#
# update_policy (from skills.lock.json) decides what we do per skill:
#   track   -> clean vendor; safe to re-pull. We compare pin vs upstream HEAD.
#   adapted -> modified after copying; NEVER blind-overwrite. We only report that
#              upstream moved so you can 3-way diff.
#   frozen  -> upstream gone/bundled (theone 404, cate-*). Listed, not checked.
#   native  -> authored in Jacob, no upstream. Skipped.
#
# Usage: ./check-updates.sh [--help]
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
LOCK="$JACOB_ROOT/skills/skills.lock.json"
PLUGINS_JSON="${PLUGINS_JSON:-$HOME/.claude/plugins/installed_plugins.json}"
MKT_DIR="${MKT_DIR:-$HOME/.claude/plugins/marketplaces}"
MCP_FILE="$JACOB_ROOT/mcp/servers.json"

[ "${1:-}" = "--help" ] && { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
command -v jq  >/dev/null 2>&1 || { echo "jq required"; exit 0; }
command -v git >/dev/null 2>&1 || { echo "git required"; exit 0; }

CACHE=$(mktemp -d); trap 'rm -rf "$CACHE"' EXIT
GH_AUTH=(); [ -n "${GITHUB_TOKEN:-}" ] && GH_AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")
short() { printf '%s' "$(printf '%s' "${1:-}" | cut -c1-8)"; }

# Memoized `git ls-remote` HEAD for a repo+ref (many skills share one repo).
remote_head() { # $1=repo_url $2=ref
  local key f
  key=$(printf '%s@%s' "$1" "$2" | tr -c 'a-zA-Z0-9' '_')
  f="$CACHE/$key"
  # A bare branch name is a suffix pattern: `main` also matches
  # refs/heads/changeset-release/main. Pin it to the exact head ref.
  local ref="$2"; [ "$ref" = "HEAD" ] || ref="refs/heads/$ref"
  [ -f "$f" ] || git ls-remote "$1" "$ref" 2>/dev/null | awk 'NR==1{print $1}' > "$f"
  cat "$f"
}

remote_latest_tag() { # $1=repo_url — newest semver tag (v1.2.3 or 1.2.3), or nothing
  local f
  f="$CACHE/tags_$(printf '%s' "$1" | tr -c 'a-zA-Z0-9' '_')"
  [ -f "$f" ] || git ls-remote --tags --refs "$1" 2>/dev/null \
    | awk -F/ '{print $3}' | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 > "$f"
  cat "$f"
}

behind=0; uptodate=0; review=0; unknown=0

# ------------------------------------------------------------------ Skills ----
echo "# Jacob update report — $(date -u +%Y-%m-%dT%H:%MZ)"
echo
echo "## 1. Skills (vendored / adapted)"
echo
echo "| skill | policy | pinned | upstream HEAD | status |"
echo "|---|---|---|---|---|"

while IFS=$'\x1f' read -r name policy url branch commit release; do
  case "$policy" in native|frozen) continue ;; esac
  if [ -z "$url" ]; then
    printf '| %s | %s | — | — | ? no source_url |\n' "$name" "$policy"; continue
  fi
  path=${url#https://github.com/}
  owner=$(printf '%s' "$path" | cut -d/ -f1)
  repo=$(printf '%s' "$path"  | cut -d/ -f2)
  rest=$(printf '%s' "$path"  | cut -d/ -f3-)
  ref="$branch"
  [ "${rest%%/*}" = "tree" ] && ref=$(printf '%s' "$rest" | cut -d/ -f2)
  [ -z "$ref" ] && ref="HEAD"
  repo_url="https://github.com/$owner/$repo.git"

  # Release-pinned entries: compare against latest GitHub release tag.
  if [ -n "$release" ]; then
    latest=$(curl -fsSL ${GH_AUTH[@]+"${GH_AUTH[@]}"} \
      "https://api.github.com/repos/$owner/$repo/releases/latest" 2>/dev/null \
      | jq -r '.tag_name // empty')
    if [ -z "$latest" ]; then st="? release unreachable"; unknown=$((unknown+1))
    elif [ "$latest" = "$release" ]; then st="✓ up-to-date"; uptodate=$((uptodate+1))
    else st="⬆ BEHIND (latest $latest)"; behind=$((behind+1)); fi
    printf '| %s | %s | %s | %s | %s |\n' "$name" "$policy" "$release" "$latest" "$st"
    continue
  fi

  head=$(remote_head "$repo_url" "$ref")
  hs=$(short "$head")
  if [ -z "$head" ]; then
    printf '| %s | %s | %s | — | ? repo unreachable |\n' "$name" "$policy" "$(short "$commit")"
    unknown=$((unknown+1)); continue
  fi
  if [ "$policy" = "adapted" ]; then
    if [ "$commit" = "$head" ]; then
      printf '| %s | adapted | %s | %s | ✓ up-to-date |\n' "$name" "$(short "$commit")" "$hs"
      uptodate=$((uptodate+1)); continue
    fi
    printf '| %s | adapted | %s | %s | ⚑ review diff vs %s |\n' \
      "$name" "$([ -n "$commit" ] && short "$commit" || echo "branch:$ref")" "$hs" "$hs"
    review=$((review+1)); continue
  fi
  # track
  if [ -z "$commit" ]; then
    printf '| %s | track | branch:%s | %s | ~ no commit pin — re-pull to compare |\n' "$name" "$ref" "$hs"
    unknown=$((unknown+1))
  elif [ "$commit" = "$head" ]; then
    printf '| %s | track | %s | %s | ✓ up-to-date |\n' "$name" "$(short "$commit")" "$hs"
    uptodate=$((uptodate+1))
  else
    printf '| %s | track | %s | %s | ⬆ BEHIND (repo moved) |\n' "$name" "$(short "$commit")" "$hs"
    behind=$((behind+1))
  fi
done < <(jq -r '.skills | to_entries[] | [
  .key, (.value.update_policy//"?"), (.value.source_url//""),
  (.value.source_branch//""), (.value.source_commit//""), (.value.source_release//"")
] | join("\u001f")' "$LOCK")

echo
echo "> \`git ls-remote\` reports repo-level HEAD, not the skill's subfolder — \"BEHIND\""
echo "> means the upstream repo moved, confirm the skill's own path changed before applying."

# ----------------------------------------------------------------- Plugins ----
echo
echo "## 2. Claude Code plugins"
echo
echo "| plugin@marketplace | installed | source | status |"
echo "|---|---|---|---|"
# Plugins whose skills Jacob ALSO vendors. §workspace and §invocation forbid refreshing these
# through the marketplace: that updates Claude Code's copy only and breaks
# single-source. Refreshing the vendored skill is the whole action, so a moved
# marketplace here is not a to-do and must not render as one — a ⬆ in this
# section should always mean "do something". Match on the bare plugin name,
# before the @marketplace suffix.
VENDORED_PLUGINS=()   # none since 2026-10-01 — Jacob vendors no plugin subset

if [ -f "$PLUGINS_JSON" ]; then
  jq -r '.plugins | to_entries[] | [.key, .value[0].version, (.value[0].gitCommitSha//"")] | @tsv' "$PLUGINS_JSON" |
  while IFS=$'\t' read -r key ver sha; do
    mkt=${key##*@}
    name=${key%%@*}
    for _v in "${VENDORED_PLUGINS[@]}"; do
      if [ "$name" = "$_v" ]; then
        printf '| %s | v%s | (vendored in Jacob) | ~ vendored — refresh the skill, not the plugin |\n' "$key" "$ver"
        continue 2
      fi
    done
    # Read the plugin's own source in marketplace.json first. It has one of two shapes:
    #  - An object naming a repo (`url` for source "url" or "git-subdir", `repo` for "github").
    #    The plugin comes from that upstream, pinned by `sha` or following branch `ref`.
    #  - A path string ("./plugins/x"). The plugin lives inside the marketplace repo itself.
    # A URL-sourced install must be compared with its own pin or branch, never with the
    # marketplace repo's HEAD. effortless installs from branch `stable` (7912a6cc) while its
    # marketplace repo's HEAD is `main` (e5c590df), so the old check said "marketplace moved"
    # on a current install (2026-11-03). Until the same day, a marketplace Claude Code syncs
    # without git (claude-plugins-official) was never checked at all, which hid superpowers v7.0.1.
    src=$(jq -c --arg n "$name" '.plugins[]? | select(.name==$n) | .source' \
            "$MKT_DIR/$mkt/.claude-plugin/marketplace.json" 2>/dev/null | head -1)
    url=$(printf '%s' "$src" | jq -r 'if type!="object" then empty
            elif .url then .url elif .repo then "https://github.com/\(.repo).git" else empty end' 2>/dev/null)
    if [ -n "$url" ]; then
      pin=$(printf '%s' "$src" | jq -r '.sha // empty')
      ref=$(printf '%s' "$src" | jq -r '.ref // empty')
      tag=$(remote_latest_tag "$url")
      newest=$(printf '%s\n%s\n' "${ver#v}" "${tag#v}" | sort -V | tail -1)
      if [ -n "$pin" ]; then want="$pin"; how="marketplace pins"
      else want=$(remote_head "$url" "${ref:-HEAD}"); how="upstream ${ref:-HEAD} is at"; fi
      if [ -z "$sha" ]; then st="~ no install sha"
      elif [ -n "$want" ] && [ "$want" != "$sha" ]; then
        st="⬆ $how $(short "$want") — run claude plugin update $key"
      elif [ -n "$tag" ] && [ "$newest" != "${ver#v}" ]; then
        st="⬆ upstream released $tag; the source the marketplace installs from does not have it yet"
      elif [ -n "$tag" ]; then st="✓ up-to-date (newest tag $tag)"
      else st="✓ up-to-date (${ref:+$ref at }$(short "$sha"); no release tags)"; fi
      printf '| %s | v%s | %s | %s |\n' "$key" "$ver" "$url" "$st"; continue
    fi
    remote=$(git -C "$MKT_DIR/$mkt" remote get-url origin 2>/dev/null)
    if [ -z "$remote" ]; then
      # A path-sourced plugin in a marketplace Claude Code syncs without git has no upstream to ask.
      printf '| %s | v%s | (Claude-managed) | ~ managed by Claude Code |\n' "$key" "$ver"; continue
    fi
    head=$(remote_head "$remote" HEAD)
    if [ -z "$sha" ]; then st="~ no install sha"
    elif [ "$sha" = "$head" ]; then st="✓ up-to-date"
    else st="⬆ marketplace moved ($(short "$head"))"; fi
    printf '| %s | v%s | %s | %s |\n' "$key" "$ver" "$remote" "$st"
  done
else
  echo "| — | — | — | installed_plugins.json not found |"
fi
echo
echo "> Note: VENDORED_PLUGINS is EMPTY as of 2026-10-01 — Jacob vendors no plugin"
echo "> subset today, so no row should render as \`~ vendored\`. If one ever does again,"
echo "> refresh the vendored skill and never the plugin (§workspace and §invocation): routing through the"
echo "> marketplace updates Claude Code's copy alone and breaks single-source."

# --------------------------------------------------------------- Pip packages ----
echo
echo "## 3. Pip packages"
echo
echo "| package | installed | latest (PyPI) | status |"
echo "|---|---|---|---|"
# memsearch ships as BOTH a pip package and a Claude Code plugin, versioned
# separately — 0.4.21 here against the plugin's 0.4.20 on 2026-09-28. A gap
# between the two rows is normal and is not drift in either one.
PIP_PACKAGES=("memsearch")
for pkg in "${PIP_PACKAGES[@]}"; do
  installed=$(pip show "$pkg" 2>/dev/null | awk '/^Version:/{print $2}')
  # Linux: PEP 668 blocks pip on system python3, so the package is a uv tool.
  [ -z "$installed" ] && installed=$(uv tool list 2>/dev/null | awk -v p="$pkg" '$1==p{sub(/^v/,"",$2); print $2}')
  if [ -z "$installed" ]; then
    printf '| %s | — | — | ? not installed |\n' "$pkg"
    unknown=$((unknown+1)); continue
  fi
  latest=$(curl -fsSL "https://pypi.org/pypi/$pkg/json" 2>/dev/null | jq -r '.info.version // empty')
  if [ -z "$latest" ]; then
    printf '| %s | %s | — | ? PyPI unreachable |\n' "$pkg" "$installed"
    unknown=$((unknown+1))
  elif [ "$installed" = "$latest" ]; then
    printf '| %s | %s | %s | ✓ up-to-date |\n' "$pkg" "$installed" "$latest"
    uptodate=$((uptodate+1))
  else
    printf '| %s | %s | %s | ⬆ BEHIND |\n' "$pkg" "$installed" "$latest"
    behind=$((behind+1))
  fi
done
echo
echo "> Tracked pip packages: ${PIP_PACKAGES[*]}. Add more to the PIP_PACKAGES array."

# --------------------------------------------------------------------- MCP ----
echo
echo "## 4. MCP servers"
echo
if [ -f "$MCP_FILE" ]; then
  # Servers are stdio (command + args) or HTTP (url). Branch, and default a
  # missing args to [] — CoplayMCP is url-only and made join(" ") throw on null.
  jq -r 'to_entries[]
    | if .value.url then "- **\(.key)**: `\(.value.url)` (HTTP)"
      else "- **\(.key)**: `\(.value.command) \((.value.args // []) | join(" "))`"
      end' "$MCP_FILE"
else
  echo "mcp/servers.json not found."
fi

# ----------------------------------------------------------------- Skipped ----
echo
echo "## 5. Skipped (frozen / native — no upstream to check)"
echo
jq -r '.skills | to_entries[] | select(.value.update_policy=="frozen" or .value.update_policy=="native")
  | "- **\(.key)** (\(.value.update_policy))"' "$LOCK"

# ------------------------------------------------- Watched idea-sources ----
# Upstreams Jacob does NOT vendor but monitors for importable ideas. Not in
# skills.lock.json (nothing on disk to validate) and not plugin-installed —
# just "did they ship something worth harvesting?". Mirrors PIP_PACKAGES:
# config lives here as "name|repo_url|pinned_commit|note".
echo
echo "## 6. Watched idea-sources (not vendored)"
echo
echo "| source | pinned | upstream HEAD | status |"
echo "|---|---|---|---|"
# NOTE: these elements are double-quoted, so a bare backtick or $( in a note
# is command substitution that runs at array-definition time. Escape both.
WATCHED_REPOS=(
  "ponytail|https://github.com/DietrichGebert/ponytail.git|96608e078b2d5ea607c5c3b8b5a54d1c1fba6846|Grok Build integration + VS Code Copilot detection 2026-08-07 reviewed 2026-08-18: tool-specific, no universal pattern. Earlier: reduction ladder + // SHORTCUT: marker harvested into §behavior and \`tech-debt\` 2026-07-13 Reviewed 2026-10-10 (95 commits, v4.10 to v5.1): per-host install docs, OpenCode 2 port, releases, translations. CONTRIBUTING.md now gates ruleset changes on a benchmark, which Jacob already requires (better needs an eval). Nothing harvested. Re-triaged 2026-11-03 (v5.3.3, 50 commits): option drop-the-harvest-and-install-whole REJECTED. Core rules changed one line since pin. The plugin injects 473w plus a regex code map into every session and subagent, which raises resident context; its statusline nudge is a second writer on the bootstrap-owned statusLine; its debt grep is case-sensitive and misses the 14 Workspace .cs files using SHORTCUT:. Band/ledger rejected as vanity. Harvested into karpathy-guidelines: list the reach, equal-size edge-case tiebreak, move/merge keeps validation. Its benchmark measures vs no skill, never vs Jacob. Re-review trigger: a Unity A/B on benchmarks/agentic shows it beats Jacob, or the rules ship hook-free as a resident file."
  "fable-method|https://github.com/Sahir619/fable-method.git|88b5cf36b10ee3679e08ee0f0181b9774d481508|INTENT gate + TWINS line + numeric stop thresholds harvested into §behavior 2026-07-16"
  "everything-game-dev-code|https://github.com/MRCalderon3D/everything-game-dev-code.git|623a9963a96baf3cafaf1d4bfc478853c48db38d|6-topic system-design gap map (save/telemetry/anim/AI/physics/netcode) harvested into skills/unity-system-design 2026-07-18; MCP doc updates only since 2026-07-27 Reviewed 2026-08-30 (10 commits): harness adapters only — Grok Build, Kilo, Cursor slash-command wrappers, a harness-adapter registry and a new:harness generator. Same verdict as ponytail's: tool-specific, and Jacob's own spine (scripts/bootstrap.sh + symlinks) already solves multi-harness. Nothing harvested."
  "adhd|https://github.com/UditAkhourii/adhd.git|dd08acc38693127cd0ca2325fe6bf9579131ede1|anchor-stripping pre-pass + symmetric strength signal harvested into §behavior/divergent 2026-08-18; earlier: single-context divergent-ideation moves 2026-07-26 Reviewed 2026-08-30 (5 commits, 2 files): README only — docs link, slimmed README, ADOPTERS, Discord, image fix. Nothing harvested."
  "i-have-adhd|https://github.com/ayghri/i-have-adhd.git|723af7d9afaf43eb871dbcce6129e2bf80de90d5|v0.2.0 2026-08-17 reviewed 2026-08-18: documentation + infrastructure updates only (contributing guide, PR template, labels), no behavioral changes. Earlier: action-first/one-next-action/visible-wins harvested into §behavior/output; response-quality eval harness vendored to scripts/evals/response-quality 2026-07-26 Reviewed 2026-08-30 (7 commits, 4 files): SessionStart hook timeout, Pi alwaysOn/hideStatus config, AI Agora comment routing. Tool-specific config, nothing durable. Nothing harvested. Reviewed 2026-10-10 (16 commits): OpenCode V2 plugin migration and reworded SKILL.md examples. Nothing harvested."
  "awesome-llm-apps|https://github.com/Shubhamsaboo/awesome-llm-apps.git|dc676965bc39bcd4fbe164bc3ea31bb75091e0c1|PyPDF/pathlib migration + link fixes 2026-08-13 to 2026-08-17 reviewed 2026-08-18: maintenance only, no new techniques. Earlier: eval criteria harvested into skills/forge Phase 5 2026-08-03. WATCH agent_skills/ ONLY (huge aggregator repo — HEAD moves constantly for unrelated demos). Reviewed 2026-08-30 (14 commits): sponsor banners, renamed-repo URL fixes, pydantic migration, new demo agents. Exactly ONE file under the watched agent_skills/ path changed (advisor-orchestrator-worker/SKILL.md, +3/-2 description rewording). Nothing harvested."
  "mattpocock-skills|https://github.com/mattpocock/skills.git|49dd158d1076134a641b33efb035946536778336|2026-10-10 FULL RE-TRIAGE from scratch at 49dd158d. VENDORED writing-for-agents as a track skill (completion criteria, leading words, negation, no-op pruning had no Jacob home; skills.lock.json carries it, so a move there is a re-pull, not a skim). Harvested two sentences: grilling's word-each-question-so-yes-accepts into §behavior/analysis, and diagnosing-bugs' diff-against-a-pristine-copy check into the bug-trace Phase 0 gate. The PLUGIN (now in claude-plugins-official, no second writer) stays rejected: 11 model-invoked descriptions compete with superpowers (tdd, diagnosing-bugs, code-review vs built-in /code-review), and the spec/ticket flow needs an issue tracker Jacob does not use. domain-modeling's ADR gate REJECTED for §vault: it would suppress WHY pages for workarounds. WATCH retro only: re-check once autoharness has run 2 weeks; if autoharness never proposes a deterministic check, retro fills that gap. Earlier history: skill invocation hierarchy (user-invoked cannot call user-invoked) harvested into §agent-engineering AI & Agent Engineering 2026-08-18; multi-writer grilling noted for future. Earlier: grilling facts-vs-decisions + dependency-ordered questions harvested into §behavior/analysis 2026-08-03. Reviewed 2026-08-30 (18 commits): the real find is #911 — an unquoted colon-space in a YAML description silently invalidates the frontmatter, so skills.sh skipped six of their skills during discovery entirely; it was introduced BY their own repo-wide em-dash sweep (#905). NOT harvested: Jacob already has the stronger deterministic form — scripts/doctor.sh Check 12 fails with 'invalid YAML (mapping values are not allowed here) — quote it or use a >- block', verified 2026-08-30 against a planted fixture, and 0 of 59 live descriptions are exposed. Their em-dash ban is explicitly NOT adopted: it is what caused the bug. Re-triaged 2026-09-07 against the pinned sha after a first pass triaged the aihero.dev marketing pages instead of the source and invented a Superpowers 'grilling' skill that does not exist (full report: vault/wiki/meta/aihero-skills-triage.md). Four of the nine skills asked about are 7-15 line shims. HARVESTED: diagnosing-bugs' repro-loop gate, minimise step, ranked falsifiable hypotheses and seam-absence-is-the-finding rule into bug-trace Phase 0/4/5/6, plus karpathy-guidelines section 4 and the §behavior root-cause bullet -- the hypothesis rule deliberately OVERRIDES superpowers:systematic-debugging Phase 3 ('Form Single Hypothesis'), which contradicted §behavior/divergent and nobody had noticed. code-review's 12-smell Fowler baseline and two-axes-never-merged rule into code-review-standards (new references/smell-baseline.md, Phase 3b Spec axis, split Phase 8 verdicts) -- its issue-tracker plumbing not taken. improve-codebase-architecture's deletion test and git-log hot-spot bias into tech-debt Phase 2A, and DEEPENING.md's two-adapter seam rule into karpathy-guidelines -- its Tailwind/Mermaid HTML report rejected as a third rendering path beside archify and Artifacts (the archify half is VOID since 2026-10-05, archify removed in a0bb787; as a second path beside Artifacts the reject still stands). wait-what's use-the-project's-vocabulary clause into commands/brief.md (deleted 2026-10-04; the clause is no longer live); its ASD-STE100 register rejected, rules/output-styles/jacob-plain.md is the single home. REJECTED: grilling (already harvested 2026-08-03; its whole-frontier-per-round batching stays rejected in favour of §behavior's one-decision-at-a-time), grill-me, grill-with-docs, implement (all shims), prototype (brainstorming's Spike path owns it, and both branches are web-only). WATCH: domain-modeling's three-condition ADR gate (hard to reverse + surprising without context + real trade-off), which is tighter than §vault's WHY-page trigger. Do NOT add aihero/* pins -- same repo, marketing name."
  "moyu|https://github.com/uucz/moyu.git|f276e3cc8a7fba8a71a6aa2180ffb991c138bbc3|Anti-over-engineering framework. Severity tiers + named anti-patterns + regression guards harvested into skills/karpathy-guidelines 2026-08-26 (Jacob-adapted: tier-5 hotfix rewritten to a stop-the-bleeding + // SHORTCUT: rule, and the 3-file cap replaced with a reason-count rule that does not fight §behavior's TWINS sweep). WATCH — new severity levels or anti-patterns."
  "context-engineering-kit|https://github.com/NeoLabHQ/context-engineering-kit.git|23e2428e809d77717f8acc9659c374a3a1fcb93e|Multi-plugin kit. Harvested 2026-08-26: plugins/reflexion → §behavior/self-refine; plugins/ddd → §architecture DDD Mapping table; plugins/review → skills/code-review-standards review lenses. plugins/sdd NOT taken (superpowers:writing-plans already owns that ground). WATCH — new plugins only; the four already reviewed."
  "skillreaper|https://github.com/thousandflowers/skillreaper.git|1cfd85dce3ac922df37ff4c86f281ae3f695c8d8|Skill-lifecycle audit from transcripts (usage metrics, dead-skill detection). Reviewed 2026-08-27: the IDEA is sound but the mechanism needs per-invocation telemetry Jacob does not record — transcripts log that a skill fired, never whether it succeeded. NOT harvested; revisit if Claude Code ever exposes skill outcome data. See scripts/evals/overlap-audit.py for the redundancy half, which Jacob already has."
  "keep-the-why|https://github.com/oliver-zehentleitner/keep-the-why.git|d01ac7209ca7b57126f096aa9bf13f907d658d9c|Preserving decision rationale in-repo. WHY.md pattern (decision / alternatives / rejection reasons / code location + a // WHY: vault:// backlink) harvested into §vault 2026-08-26. Reviewed 2026-10-10 (203 commits, mostly the dashboard): HARVESTED rule 10, match depth to non-obviousness, plus none-found-is-valid for alternatives, into the §vault WHY-page rule. Its per-entry UUID Id and Superseded-by chain feed the temporal-validity gap already deferred in the mempalace and agent-memory pins; WATCH that, not the dashboard or registry."
  "modem-skills|https://github.com/modem-dev/skills.git|edcdedb38a545f67c065f4084b3627517f0d79cf|write-discoverable-code: names-as-search-queries, 2-4 word symbols, anti-matching names. Harvested into skills/theone-unity-standards references/csharp/quality-hygiene.md 2026-08-26 as the canonical home; §naming keeps a one-line pointer. WATCH — other skills in the repo not yet reviewed."
  "prompt-master|https://github.com/nidhinjs/prompt-master.git|2bd92518e26bf659e21e3d9ab90573fcf3ddeccb|Cross-tool prompt-engineering skill (12k*, MIT). Vendored NOTHING 2026-08-30 — 940 lines of volatile per-model routing claims would be an adapted tail forever, and its PRIMACY-ZONE output lock is a second canonical home for §behavior output shape. Harvested: the frame-is-a-hat-not-a-character clause into §behavior/divergent, and its outward twin (do not build fake deliberation into an authored artifact) into skills/forge reliability techniques. NOT taken: hidden-CoT rule and generalized model-recency gate — deferred, separate decisions. WATCH — new durable craft rules only, not model-table refreshes."
  "headroom|https://github.com/headroomlabs-ai/headroom.git|d13e1966f820220b482a33c30bde1e926743939a|Context compression (library/proxy/MCP). Spiked 2026-08-30 in headroom-exp worktree with v0.37.0+[code]: JSON tool results compressed 50.7% losslessly, but plaintext build logs and real Unity C# returned router:noop / router:excluded:tool at 0% across 5 shapes — the advertised 15-20% coding-agent saving did NOT reproduce without the [ml] extra (Kompress-v2-base + ONNX 1.24+), and the shortfall is SILENT. NOT adopted: headroom learn writes to CLAUDE.md/AGENTS.md which are symlinks into AGENTS.md (§workspace and §agent-engineering); headroom wrap is a second writer into tool configs (Coplay failure mode); cross-agent memory duplicates memsearch. WATCH — revisit only if Jacob gains an MCP-output wrapper to host the JSON path, or if text compression ships in the base install."
  "one-skill-to-rule-them-all|https://github.com/rebelytics/one-skill-to-rule-them-all.git|56e890712273ce231b478adc56ee2eb81101c3d6|Session-observation meta-skill (task-observer). Reviewed 2026-08-30: NOT vendored — the 524-line always-resident core violates §agent-engineering, and its observation log / weekly review / staged-delivery model duplicates memory type:feedback, memsearch:memory-to-skill, forge and check-updates while contradicting §workspace edit-in-Jacob. Same category as skillreaper (declined 2026-08-27). Harvested: enforcement-trigger design rule → Jacob_Engineering.md §agent-engineering; deferral-as-decision → §behavior/analysis; TWINS extended to governance artifacts → §behavior. WATCH — new enforcement/methodology prose in SKILL.md only, not the log/review machinery. Reviewed 2026-09-28 (105 commits). HARVESTED its sibling-check rule into section 13 root-cause and mirrored the format into unity-yaml-editing: every EXCLUSION names its ground, the file and section read showing it does not apply, or the literal assumed; inclusions need none. Their argument is the asymmetry -- a wrongly included sibling costs one redundant paragraph at the next review, a wrongly excluded one leaves silently and for good, because nothing downstream acts on a negative verdict. Their sharpest line: recording the verdict is not recording its evidence, so once the sweep is habitual the failure moves from the missing line to the confidently filled one. Jacob's TWINS line recorded pattern and hits only, and that gap was demonstrated the same day: a sweep for the identifier curated_skills found SKILL.md and silently missed check-updates.sh, which repeated the same two wrong claims in prose without naming the identifier. Hence the added rule that the pattern you chose is itself an exclusion. NOT taken: their siblings_checked frontmatter field and linter gate, which need a per-entry manifest Jacob has no surface for. Reviewed 2026-10-10 (98 commits): HARVESTED the deferral probe (check read-only that the deferred action can be taken at all; a failed probe means decide now) into §behavior/analysis. Checked and dropped: the unquoted-description space-before-# rule (0 Jacob descriptions exposed) and the empty-probe stop signal (covered by the negative-claims bullet)."
  "taste-skill|https://github.com/leonxlnx/taste-skill.git|f624f37a8c650b9cc550253104925efe4c8de246|Anti-slop web-frontend skills, 13 of them (82k*, MIT). Vendored NOTHING 2026-08-30 — every rule is a literal Tailwind/CSS/React token (50 web-token hits vs 0 for unity/ugui/uxml/monobehaviour/canvas-scaler/tmp_text), so nothing transfers to UGUI/UI Toolkit. DECISIVE: its core mechanism, the THREE DIALS (DESIGN_VARIANCE/MOTION_INTENSITY/VISUAL_DENSITY, 1-10), is already shipped by the vendored ui-ux-pro-max as --variance/--motion/--density — same names, same scale, same banding, but as executable flags over a 192-row database instead of prose the model must self-honor across 1,206 lines. output-skill additionally BANS the '// ...' placeholder that AGENTS.md:184 mandates. Harvested: countable-not-judgeable self-audit form (SKILL.md:256,933) into skills/forge reliability table. NOT taken: §architecture AI TELLS — a real gap in Jacob (ui-ux-pro-max has usability Don'ts, no looks-machine-made taxonomy) but every tell is a web landing-page tell; the Unity equivalent must be authored from Unity ground truth. WATCH — new AI-tell taxonomy only, not the token lists. RE-TRIAGED 2026-10-16 after v2.0.0 (2026-10-13): v2 drops the dials, so the dial-duplication ground no longer applies to it. v2 is a genuine tool: a Chrome DevTools inspector, licensed photo sourcing via assets.mjs, and a dated tells registry. Still rejected because it builds marketing sites only and excludes dashboards and app screens. No web work was found in the journals, artifacts belong to artifact-design, and there is still 0 Unity content. install.sh symlinks into ~/.claude/skills, so it is a second writer. For a one-off web project outside Jacob, use npx skills use. Harvested nothing: its tells age with fashion, while ui-taste.md technical tells do not. WATCH: a Unity or app-screen scope, or an engine-neutral tell. 2026-11-03 NOTE: the no-web-work ground is stale. Web/HTML output is now in scope (see ui-skills). The reject still stands on the marketing-only scope and the second-writer install.sh."
  "claude-code-best-practice|https://github.com/shanraisshan/claude-code-best-practice.git|63e587bf0ae13a344866c2e8f55cc0605d6a35d3|Claude Code feature/best-practice reference (65k*, MIT). Triaged 2026-08-31; vendored NOTHING — its .claude/ tooling, hooks and sound pack are second writers against the §workspace spine. Harvested: the subagent skills: preload field (full skill content injected at agent startup, verified against code.claude.com/docs/en/sub-agents) into Jacob_Engineering.md §workspace + forge Phase 3 — Jacob's 18 agents used none of it and grant no Skill tool, so agents/unity-reviewer.md enforced §naming/§architecture and §frameworks while unable to reach theone-unity-standards. REJECTED as duplicates: RPI (Research/Plan/Implement) is superpowers brainstorming→writing-plans→subagent-driven-development, and the cross-model Claude-plans/Codex-reviews loop is §behavior's dispatched-reviewer discipline, whose Jacob form is stronger (adversarial framing + finding-precedence ladder). DEFERRED, not rejected: .claude/rules/ with paths: frontmatter is real path-scoped lazy loading and a genuine fit for the 359-line always-resident ruleset, but moving §code there hides them from opencode/Antigravity, which read AGENTS.md — a §workspace single-source break needing its own decision. WATCH — new durable craft rules and harness fields only, not feature-table refreshes. 2026-10-01 UPDATE: the stated blocker is VOID — opencode and Antigravity were dropped, so nothing but Claude Code reads AGENTS.md and path-scoped rules can no longer hide §code from a second consumer. The deferral now rests on nothing. Re-decide it on its merits at the next triage. Reviewed 2026-10-10 (142 commits, 11 files): every commit is a changelog or star-count drift entry from its own scheduled bot. Nothing harvested."
  "addyosmani-agent-skills|https://github.com/addyosmani/agent-skills.git|301b02b12bff98e4688e6984af6556802322bbde|25-skill software-lifecycle pack (91k*, MIT). Triaged three times (2026-07-12, 2026-08-18, 2026-08-30); vendored NOTHING — 23 of the 25 skills duplicate superpowers or Jacob (TDD/debugging/planning/spec/ship, code-review-standards, karpathy-guidelines, architecture-decision, ui-ux-pro-max, §manifest, §behavior/divergent) or are web-stack out of domain, and its CONSTRAINTS.md is a second canonical home for §judgment while its three hooks are second writers against the §workspace spine. Harvested 2026-08-30: doubt-driven-development's reviewer-dispatch discipline (hand over artifact+contract never the claim, adversarial framing overrides a review agent's balanced-verdict shape, contract-misread/actionable/trade-off/noise precedence, the rubber-stamp signal) into §behavior/self-refine; constraint-driven-development's a-budget-with-no-verdict-command-is-an-aspiration rule into §judgment; scripts/validate-reference-links.js reimplemented Jacob-native as scripts/doctor.sh Check 4b (narrowed to markdown-link syntax so forge's illustrative backticked paths do not false-positive). NOT taken: run-evals.js rank-1 ratchet (scripts/evals/ already has the trigger corpus + overlap audit; a baseline ratchet is a Jacob-internal call, not this repo's). WATCH — new durable craft rules only, not new lifecycle skills. Reviewed 2026-09-28 (132 commits). HARVESTED three eval-methodology rules into forge Phase 5: a fired-indicator is not a score (a loaded description shapes the reply even with no invocation, so pair it with a grader on the reply itself); firing is stochastic, so run several trials and report the rate rather than one green run (TRIALS= in scripts/evals/run-trigger-eval.sh is the existing knob); and test the phrasings a user actually types, because when only the jargon phrasing fires, the description is the defect and must never be fixed by rewriting the eval prompt. Their measurement is recorded as theirs, not adopted as Jacob's: their review skill fired 5 of 7 runs on a prompt naming its axes and 0 of 6 on three plain review-this-diff phrasings. NOT taken: their ADR status-and-date grader, since section 3.5 already carries the superseded callout with an ISO date and a dated updated: field. Reviewed 2026-10-10 (87 commits): HARVESTED the #anchor check from validate-reference-links.js into doctor.sh Check 4b, whose regex had required .md) and so skipped anchored links entirely (5 live, all in unity-mcp-skill). Its spec-keys-only frontmatter validator NOT taken: Claude Code needs allowed-tools and disable-model-invocation. Reviewed 2026-11-03 (130 commits, no new skills): HARVESTED strip-reasoning-not-evidence into §behavior/self-refine, regression-vs-pre-existing labels into code-review-standards, prove-a-gate-can-fail into Jacob_Engineering §engineering/validation, real-boundary crash test into the unity-system-design Save / Persistence test gate. Pack reject unchanged: hooks still ship, 23 of 25 skills still duplicate."
  "cxpak|https://github.com/Barnett-Studios/cxpak.git|85d0f27b5471e54d8724423207d745c0c52940cf|Rust code-intelligence plane (43 langs, MCP/LSP/HTTP, Apache-2.0). NOT vendored 2026-08-31 -- the engine duplicates the spine's code-review-graph (10,432 nodes / 91,468 edges live on this repo) and a second graph MCP is a routing collision, two tools answering 'who calls this'. It also shares the IDENTICAL Unity blind spot: prefab/ScriptableObject/scene/.meta GUID wiring, already assigned to unity-yaml-editing at AGENTS.md:83, so swapping engines closes nothing there. Harvested: token-budgeted progressive degradation (Full > Trimmed > Signature > Stub) into 3.6 as 'budget the manifest, do not just rank it'. NOT taken: conventions extraction + changed-lines-only verify -- a REAL gap (0 hits for 'convention profile' across skills/, references/, ruleset) but there is no Jacob-native mechanism to host it, same call as skillreaper 2026-08-27. Also rejected: visual D3 dashboards (archify covers diagramming -- VOID since 2026-10-05, archify was removed in a0bb787; the built-in Artifact tool + artifact-diagramming now hold that ground, so the reject still stands), column-level SQL lineage (no data layer here), WASM plugin loader (author states it does not run plugins, issue #42). WATCH -- conventions scoring and the RRF ranker only, not releases. 2026-10-01 UPDATE: code-review-graph was CUT, so the duplicates-the-incumbent half of this reject is VOID. Its graph had indexed only Jacob itself (4,630 nodes, zero .cs) in two and a half months. Re-ground or re-open before the next triage: the routing-collision argument is gone, the Unity prefab/.meta blind spot argument still stands on its own."
  "riper-5|https://github.com/tony/claude-code-riper-5.git|fd1d93be26e5c16c659a0540882b2f12814f11bd|RIPER phase workflow, Research/Innovate/Plan/Execute/Review (93*, MIT, markdown only). Vendored NOTHING 2026-08-31 -- all five phases are already owned by the Superpowers two-phase table at AGENTS.md:228-236 plus brainstorming / writing-plans / subagent-driven-development / requesting-code-review, and its memory-bank duplicates memory/ + memsearch + commands:save. TWO CONFLICTS: its review agent hardcodes pnpm lint / pnpm test / pnpm test:e2e, which section 2 forbids suggesting at this root; and its mandatory [MODE: X] prefix on every response contradicts section 13 'lead with the actionable line' (:188). Its one structural idea, phases enforced by real agent tools: frontmatter rather than by prompt text, Jacob already ships -- unity-reviewer and unity-performance are Read/Grep/Glob, verifier adds Bash. WATCH -- low priority."
  "understand-anything|https://github.com/Egonex-AI/Understand-Anything.git|4e6d3299017a7432da15957874992837a315c5b4|Multi-agent codebase-to-knowledge-graph plugin (90k*, MIT, TS, v2.9.8). Triaged 2026-08-31, RE-TRIAGED 2026-11-03 because both pillars of the first verdict died on 2026-10-01: install.sh writes only ~/.agents/skills, which no longer exists, and code-review-graph was cut. The Claude Code route is a marketplace plugin under its own name, sanctioned like superpowers. Still REJECTED, nothing vendored or harvested. (1) No proven gap: AGENTS.md:64 routes mapping to grep + vault + on-demand graphify, the 2026-10-05 567-file .cs bench showed graph tools lose to grep on tokens, and this one also spends LLM tokens per file at first scan. (2) Unity blind spot: C# parsed (csharp-extractor.ts) but nothing reads .prefab/.unity/.meta, so Inspector-wired references are missing edges, same as cxpak. (3) .ua/ per-file summaries would be a second orientation store beside the vault. (4) 9 skills + 10 agents add 19 always-listed descriptions. (5) Auto-update hooks say 'Do not ask the user for confirmation' and re-run after every commit, against the section-behavior ask-gate. Copy-vendoring needs a pnpm monorepo build (section-workspace). WATCH on /understand-knowledge CLOSED: scripts/vault-suggest-links.py covers implicit vault edges. Re-open only if it extracts Unity serialized references, or the user wants a human-facing dashboard to onboard a person onto a Unity repo; then install at project scope in that repo, never user scope."
  "mempalace|https://github.com/MemPalace/mempalace.git|8c4865f70c49b6346c53474a9e5684c5f17d3fa9|Local-first verbatim agent memory, 163k LOC Python (MIT, release 3.9.0). Triaged 2026-09-07 at snapshot e809834; pinned forward to current HEAD because this repo lands commits daily and the verdict rests on structural conflicts, not on any one commit. Vendored NOTHING -- installs via \`npx skills add\` into ~/.claude/skills, which IS Jacob's own skills/ through the symlink (same call as understand-anything and ECC), its default chroma store is a second vector index beside the live Milvus Lite that memsearch owns, and its Stop hook BLOCKS the agent every 15 human messages to force a save, which fights section 13 lead-with-the-actionable-line and lands in a settings.local.json that bootstrap.sh does not manage (unportable, section 2 suitcase). DECISIVE FIND, and the reason this triage was worth running: its 39-line tools/backup_claude_jsonls.sh exposed a real silent loss -- .memsearch journals carry transcript: backlinks into ~/.claude/projects, which Claude Code prunes at 30 days, and 115 of 152 were already unrecoverable. Closed Jacob-native with scripts/backup-transcripts.sh + doctor Check 16, no daemon and no second index. Its temporal knowledge graph (SQLite triples with valid_from/valid_to windows) is the one piece Jacob has no answer for; deferred like skillreaper and cxpak conventions, since there is no Jacob-native surface to host it. WATCH -- the knowledge_graph.py temporal model ONLY, not releases, backends, or benchmark numbers."
  "everything-claude-code|https://github.com/affaan-m/ECC.git|d3b8a3e908904e242ed2dbe66af62cca71131419|Claude Code config pack, 286 skills / 68 agents (244k*, MIT). Declined three times (omo-vs-ecc, 2026-07-11, 2026-08-31); vendored NOTHING -- all JS/TS/web with zero Unity, and every part has an incumbent: memory-persistence duplicates .memsearch + memory/, eval-harness is prose where scripts/evals/ is runnable (pass@k already shipped as TRIALS= in run-trigger-eval.sh:25), verification-loop duplicates the verifier agent, continuous-learning duplicates memsearch + forge + save. TWO CONFLICTS: continuous-learning writes to ~/.claude/skills/learned/, which IS Jacob's own skills/ via the symlink (same call as understand-anything 2026-08-31); and verification-loop plus hooks.json hardcode npm/pnpm/cargo/pytest pipelines that section 2 forbids at this root (same call as riper-5 2026-08-31). Triaged via the stale unlicensed worldflowai/everything-claude-code mirror (snapshot of 2026-01-23, LICENSE stripped) -- use the upstream, never the mirror. WATCH -- new durable craft rules in skills/ and rules/ only, NOT the agent/command/skill count, which moves constantly."
  "vercel-skills-cli|https://github.com/vercel-labs/skills.git|7407f3893ad4dceab546ac002c3ef806e4000c73|Upstream of the vendored find-skills skill (30k*, MIT). CLI itself REJECTED 2026-09-06 -- src/agents.ts:156 targets ~/.claude/skills, a symlink into this repo, so add/update/remove/check are section 2 second writers (check is a plain alias of update, cli.ts:391-393). Harvested: npx skills use as the sanctioned no-install path (src/use.ts:160 materializes to mkdtemp only, zero installer references), plus a telemetry disclosure -- find sends the query to add-skill.vercel.sh (telemetry.ts:1, find.ts:345,383). The bundled find-skills/SKILL.md NOT re-vendored; Jacob adapted copy is stricter. WATCH -- new read-only subcommands and changes to use write surface only, not agent-adapter additions."
  "jakubkrehel-skills|https://github.com/jakubkrehel/skills.git|267330e1adfc66a718fb65fa6918c1f06d0a689e|11-skill interface pack (MIT, markdown). Triaged 2026-09-06 (family) and 2026-09-07 (better-writing). Vendored NOTHING -- three cross-refs point at sibling skills Jacob will not take, its Block/Approve reporting harness has no Jacob equivalent, and its description ('Focuses on improving product copy in your project.') would never fire on Unity work, per section 18. Harvested from better-writing 2026-09-07: verb-first button labels + confirmation-repeats-the-consequence, one-capitalization-policy, single flow vocabulary, toggle-describes-ON-state, no-sentence-concatenation-around-a-variable (a localization bug AND a section 8 allocation), and forward-pointing empty states -- all into Jacob_Framework_Rules.md ## UI System, under the existing section 10 gate. The 2026-09-06 blanket reject of the better-* family is AMENDED for this one skill: ui-ux-pro-max owns copy STRUCTURE as rule ids (error-clarity, error-recovery, input-labels, empty-data-state) and has zero coverage of voice, label grammar, capitalization, or flow vocabulary; the only adjacent Jacob line is agents/unity-ui-specialist.md:189, which is plumbing. Unlike taste-skill (50 web tokens, 0 Unity), better-writing is 11 web-token hits with 8 inside a single HTML snippet, so nine of twelve sections transfer to UGUI as written. NOT taken: link-text-describes-destination (screen-reader link list, web-only), placeholder-is-not-a-label and error-states-how-to-fix (already ui-ux-pro-max), tone-by-stakes matrix (games carry deliberate voice by design). WATCH -- better-interface and interface-review only, the two not yet read."
  "threejs-game-skills|https://github.com/majidmanzarpour/threejs-game-skills.git|8286774b22a2566bf894dbc825825c16921866af|Nine-skill Three.js browser-game pack (1.7k*, MIT). Vendored NOTHING 2026-09-07 -- install.sh:166,171 targets ~/.claude/skills and ~/.agents/skills, which ARE Jacob's own skills/ through the symlink (verified: both resolve to /Users/kaan/Workspace/Jacob/skills), so installing would write 9 untracked directories into the repo -- same call as understand-anything, ECC and mempalace. Every line of code is TypeScript against a WebGL renderer, so §code have no contact with it. Harvested: references/game-feel.md's five-layer ordering (input latency > response curves > contact feedback > camera > audio-visual sync), the readability rule (an effect that hides the player's next decision is a bug, not polish), and trauma-squared-with-a-hard-cap, into skills/unity-system-design as a new §naming Game Feel, Unity-authored against Feel/DOTween/§performance and §architecture -- AGENTS.md:323 already named the nouns and demanded numbers but gave no order, and a grep for the terms hitstop, trauma, squash, coyote, game feel and juice across skills/, agents/ and references/Jacob_* returned only the Feel-library assignment at Jacob_Framework_Rules.md:100 plus agent routing lines. REJECTED: references/physics-engine-selection.md (unity-system-design section 5 already owns simulated-vs-authored-vs-faked, FixedUpdate-only, one-owner collision response and tunneling/CCD; Rapier/cannon-es/Jolt are web-only), the 10-category AAA visual scorecard (its measured half is a Playwright canvas inspector and its calibration anchors are Three.js screenshots), the director (superpowers brainstorming>plans>SDD plus §judgment scope-is-a-deliverable), and the 3D/image/audio generators (paid external APIs, out of domain). WATCH -- genre-design.md's 8 fun-factor tests and qa-release's declare-the-evidence-set-before-capture rule (never delete a failing slot to make the manifest pass), both real but deferred; not the scaffold, the Playwright templates, or the generators."
  "attention-span|https://github.com/alexgreensh/attention-span.git|2714c965e6be1fa2597510e66651e63bc67cb448|Three Claude Code output styles + 4 user-invoked skills + a /style switcher + a deterministic benchmark harness (968*, AGPL-3.0). Triaged 2026-09-07. Vendored NOTHING. The styles land on an OCCUPIED slot: rules/output-styles/jacob-plain.md is the single canonical home for register and shape (scripts/doctor.sh:731, bootstrap.sh:53, settings.json outputStyle), and the same one-home call was made against i-have-adhd's output hook in 2026-07. Their format rules also INVERT Jacob's -- attention-kind mandates heavy bold and its own metric scores higher bold density as better, where jacob-plain caps it at three. /style is a second writer on the outputStyle key that bootstrap.sh:711-720 owns (section 2). code-eval is Python tasks against a Unity ruleset, and adapters.py duplicates the --setting-sources isolation runners.json already has. FIRST PASS WAS WRONG and the user caught it: a file-level slot-collision verdict got applied to rule-level content, the same error the jakubkrehel amendment warns about. The rule-by-rule diff found EIGHT keepers, THREE of them corrections to Jacob own text, not imports. DECISIVE FIND: jacob-plain.md contained zero occurrences of warning, caveat, or risk while its shape check instructed 'cut a point' to meet the 150-word cap -- a hard ceiling with an explicit drop-content instruction and no protected class, so the risk line was the likeliest casualty. Harvested into jacob-plain: short-does-not-mean-fewer-points, a-warning-is-cut-last, requested-depth-suspends-the-ceiling, a-deliverable-is-not-an-answer (all as a new ceiling-cuts-elaboration-never-substance block), no-scope-widening and no-flattening-a-two-sided-fact into the register rules, acknowledgment-turns-get-one-line into the ceiling bullet, and blocking-question-placement as a fifth countable rule; the shape check no longer says 'cut a point'. Mirrored to CLAUDE.md section 13 so opencode and Antigravity carry them. Its deterministic-scoring-without-an-LLM-judge idea reimplemented Jacob-native as scripts/evals/answer-shape.py (no AGPL code copied; its thresholds are inverted for Jacob). NOT taken: the arrow/block-marker regime (fights the three-bold cap), the tone list (no-ai-slop owns it), re-anchoring (superpowers todo lists own it). WATCH -- new deterministic metrics in benchmarks/harness/ ONLY, not the style wording, not the star count."
  "hindsight|https://github.com/vectorize-io/hindsight.git|ccfe85b4851957ac2adf88b4a9ddf9668b2882f1|Agent memory system, retain/recall/reflect over PostgreSQL+pgvector (35.2k*, MIT, 416MB monorepo). Triaged 2026-08-28 (rejected, never pinned -- which is why it was re-triaged from scratch) and again 2026-09-27. Vendored NOTHING. The server is a second vector index beside the live Milvus Lite that memsearch owns, same call as mempalace. DECISIVE: hindsight-integrations/coding-agents/src/core/skill-dirs.ts:19,21-22 writes into ~/.claude/skills AND ~/.agents/skills, both of which resolve to /Users/kaan/Workspace/Jacob/skills, and core/skill-sync.ts re-copies on drift at EVERY session start -- a standing second writer, worse than the one-time installers in understand-anything, ECC, mempalace and threejs-game-skills; installer.ts:695,715,722 additionally writes ~/.gemini/config/hooks.json, mcp_config.json and Antigravity settings.json, all owned by scripts/bootstrap.sh. The five skills/ entries are vendor-product skills, and hindsight-architect (858 lines) designs Hindsight bank configs with zero Unity contact. HARVESTED: extensions/memory_defense.py:167-238 exposed that doctor.sh Check 14 carried 8 credential patterns against its 45 -- 12 patterns added plus a PGP widening (verified 18/18 planted positives matched, 12/12 negatives clean, 51 live journals still pass), on a file that is git-tracked and pushed and already leaked an OmniRoute key once (Jacob_Layout.md:139); its aws_secret_key, credit_card and ssn_us deliberately cut -- the first needs (?i) that one shared grep -qE cannot express, the other two are noise in engineering transcripts. coding-agents/src/core/survey.ts:137-141's never-ingest-agent-instruction-files rule into scripts/memsearch/summarize.txt -- Jacob guarded the READ side only (recalled memories reflect what was true when written) and 693 section-references already live in the journals. NOTED not harvested: survey.ts:156 states --allowedTools does not reliably block unlisted tools in headless claude -p (verified by them against v2.1.218), but Jacob's one headless call (scripts/evals/run-trigger-eval.sh:88) allow-lists nothing, so no rule has a surface to sit on. WATCH -- knowledge pages / mental models / the temporal validity model ONLY, the same deferred gap as mempalace's knowledge_graph.py; not releases, not benchmark numbers, not the integration count."
  "graphify|https://github.com/Graphify-Labs/graphify.git|35adf432b9d50f6f3d530ab5d7ec316819ef081c|tree-sitter code/doc knowledge graph, CLI + graph.json (124k*, Apache-2.0, Python, v0.9.76). Vendored 2026-07, replaced by code-review-graph 2026-07-20. Re-triaged 2026-10-05, NOTHING vendored; the user's goal was cutting tokens. Bench: 567 first-party .cs files from a Unity game repo. Caller recall equals code-review-graph (4/4, 4/4, 11/11, 2/2), so the 2026-08-30 'single-file call resolution only' premise is VOID. But it costs MORE tokens than grep for callers (643 vs 143, 1,614 vs 187), and only 'explain' saves (634 vs 3,720 for reading GameSession.cs), and only on files you will not edit. KEPT as an on-demand onboarding tool: 'uvx --from graphifyy graphify extract . --code-only', no install. NEVER run 'graphify install': it writes ~/.claude/skills/graphify, which resolves into Jacob's skills/. Re-open only if a grep-baseline token benchmark shows a win. WATCH releases."
  "code-review-graph|https://github.com/tirth8205/code-review-graph.git|6b12d11625cbec3b6773e076cb3d136464fa90e5|MCP-first code graph, about 30 tools, SQLite (32k*, MIT, Python, v2.3.9). Vendored 2026-07-20, CUT 2026-10-01: in 2.5 months it graphed Jacob itself (zero .cs) and produced one empty database. REJECTED 2026-10-05 on tokens, the user's stated goal. Same 567-file bench as graphify, same caller recall, but the most tokens of the three on every question (2,043 vs grep's 143; 9,625 vs 187), because the JSON repeats absolute paths and metadata. Its '63x' headline divides by loading the whole repo, and its README admits no grep-baseline result has been published. Its review context is below 1x on small commits. Re-open only for diff review on one long-lived repo, or if a published agent_baseline result beats grep."
  "agent-memory|https://github.com/tigerless-labs/agent-memory.git|aca58578ab386e4d422a97bcf32c2af2f3e57316|Markdown-truth agent memory runtime, FTS5+optional vector recall, sleep-time Manage (3.4k*, MIT, Python, v0.1.0, no PyPI). Triaged 2026-10-05 (watched-only, never pinned -- hence the re-triage) and from scratch 2026-10-10. Vendored NOTHING. DECISIVE: adopting adds a THIRD memory store beside memory/ and memsearch rather than merging them; its distiller has no secret redaction (prompts.py/distiller.py grep: none) while archive/sessions copies full traces, so a Jacob-hosted store would push raw transcripts that Check 14 + scripts/memsearch/summarize.txt exist to keep out; and setup.py:27 writes skills/agent-memory/SKILL.md beside ~/.claude/settings.json, i.e. into Jacob/skills via the symlink. Its bundled skill is useless without the mem runtime; Muse/OpenRouter/Vertex adapters target hosts Jacob does not run. WATCH -- the valid_from/invalid_at supersede chain + recall --as-of + proposal-only sleep deletion ONLY: it is the first candidate HOST for the temporal-validity gap deferred in the mempalace and hindsight pins. Re-triage as full-replace for memsearch only when (a) the distiller redacts secrets, (b) it ships a release, and (c) a real stale-memory failure shows the gap costs something."
  "xerj|https://github.com/xerj-org/xerj.git|5d9932fbed61cfa7dafea8eff29082670e818c7c|Local Rust search node (BM25+kNN, tree-sitter incl. C#, CLI + MCP; 6k*, Apache-2.0). Triaged 2026-10-16, vendored NOTHING. Engine WATCHED: first candidate to publish a grep baseline (9,982 vs 26,477 output tokens, 16/16) but on purpose-built libraries, and its own skill says retrieval is overhead on memorised code. User declined the a Unity game repo bench 2026-10-16. Re-open only if that 567-file grep-baseline bench (graphify row) is run and shows a token win, or for references/ (Odin 138 MB). REJECTED: xerj-code skill (needs runtime, no Unity corpora), /_memory (third memory store, see agent-memory), and running 'xerj init' at Jacob root (writes .claude/skills/ into Jacob). Project-scoped init in a game repo is fine."
  "caveman|https://github.com/JuliusBrussee/caveman.git|d262ab3882952a59312ff3537cd86d894523c5ab|REJECT 2026-10-16, re-triaged at v4.0 (six rocks; 100k*, Apache-2.0). The 2026-09-14 reject was never pinned -- hence the re-triage. Vendored NOTHING. Voice skill: 14 register rules already harvested into jacob-plain 2026-09-14 (96e1156e); the plugin's SessionStart hook would be a second register home beside the native output style. Proxy rocks (Read less, Auto, warm cache): write ANTHROPIC_BASE_URL into bootstrap-managed ~/.claude/settings.json, break Remote Control (INSTALL.md:438), telemetry on by default. Work-pattern, commit, review, compress skills duplicate karpathy-guidelines/superpowers/§commits. Re-review trigger: Read-less input compression ships as a hook (no base-URL proxy), since rtk does not cover Read or MCP output. Blocks lives in caveman-ai/blocks, pre-release, watch only."
  "awesome-gamedev-agent-skills|https://github.com/gamedev-skills/awesome-gamedev-agent-skills.git|0a70cfc64672d512c5b5b6006b5dcb5cf90dbdbd|74 cross-engine game-dev SKILL.md files + a router (2.2k*, Apache-2.0). Triaged 2026-10-21. Vendored NOTHING, harvested NOTHING. Installers: npx skills add writes ~/.claude/skills (= Jacob skills/ via symlink); the plugin marketplace route is banned by section workspace. Both sanctioned routes priced and declined. REJECTED: 8 Unity skills (tutorial depth; coroutines as default timing vs Jacob_Framework_Rules.md:34-38, unprefixed serialized fields vs section naming, logic in MonoBehaviour vs section architecture, public SO fields); 15 disciplines (game-feel/save/AI/physics-tuning are second homes for unity-system-design sections 1/4/5/7); router (duplicates native description routing); other engines/genres/workflows (out of domain). WATCH: genres/puzzle (6 of 8 rules already in vault patterns/new-project-playbook.md, level-designer.md:40 and section architecture; only cascade-to-stability and undo-restores-RNG uncovered, too thin) and disciplines/create-game-assets (real gap in art direction + Pillow QA scripts, no art-production use case yet). Re-open if puzzle gains Unity-specific depth or an art-generation workflow appears."
  "archify|https://github.com/tt-a1i/archify.git|25cf37080fc8b1dbe758a4efc3935b55f3327083|REJECT 2026-10-23, third look (88k*, MIT, JS). Vendored 2026-08-30, removed a0bb787 2026-10-05: used once in 5 weeks, and the adapted entry carried 7 local_mods (notifier strip, test removal, bin/ gitignore exception). Built-in Artifact + artifact-diagramming covers ad-hoc diagrams. Still decisive at 3.2.0: in-skill update notifier (second home beside /check-updates), 17 MB skill dir, near-daily releases; new explainer mode is a third answer-rendering path beside Artifacts and jacob-plain. Use npx skills use tt-a1i/archify@archify for one-off source-backed diagrams. Re-open only if code-backed diagrams become recurring AND upstream drops the notifier."
  "claude-code-game-studios|https://github.com/Donchitos/Claude-Code-Game-Studios.git|05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418|REJECT template 2026-10-30, third look at v1.2.0 (29.7k*, MIT): must own the repo's .claude, CLAUDE.md and project.yaml, which conflicts with Jacob's spine; its four-game rigor measurement is README-only, with no data shipped. Harvested observe-before-done into Jacob_Framework_Rules.md Testing. Three adapted skills stay lock-tracked. Re-open if it ships a plugin install, or published evidence of finished games. WATCH prototype and release skills only."
  "chisle|https://github.com/JayPokale/Chisle.git|1b3203fe394ee84ca143a1e8636fafa8e9e1f906|REJECT 2026-11-03 (v3.8.1, 737*, MIT, JS). Vendored NOTHING; same class as caveman + ponytail. Prose ruleset ('drop articles, fragments OK') contradicts jacob-plain and its SessionStart injection would be a second register home. YAGNI ladder duplicates the §behavior reduction ladder, which also carries the never-on-the-chopping-block list Chisle lacks. PostToolUse compressor: Bash already rtk-filtered (upstream replay: dedup 0 hits on an rtk corpus, ~61k tokens over 171 sessions); Read excluded by design; content-block shapes (MCP, likely Agent) skipped by rebuildResponse; failed Bash unreachable via PostToolUseFailure; and it is gated on the .chisle-active flag the prose SessionStart hook writes, so it cannot be taken alone. mcp wrap never touches Claude Code. Re-review trigger: compressor decoupled from prose mode AND rebuilds content-block arrays, or it compresses Read safely."
  "ui-skills|https://github.com/ibelick/ui-skills.git|73fb128d046d1f0d74c2909cd26eb616e3415567|9 design-engineer skills + registry site (10.5k*, MIT). Triaged 2026-11-03 under a widened scope (web/HTML output Jacob machines produce, not Unity-only). VENDORED fixing-accessibility + fixing-motion-performance by copy, track, verbatim: a file-audit mode (quote line, why, fix) and render-pipeline depth that ui-ux-pro-max lacks (0 hits on animation-timeline). WATCH improve-ui (proof-gated design audit; needs a product repo with a design system) and fixing-metadata (needs a public site). REJECTED baseline-ui (hard Tailwind/motion-react/Base UI mandates; second home for taste rules artifact-design owns), create-design-md/create-canvas/component-canvas (React product-repo tooling), ui-skills-root+CLI+MCP (runtime remote fetch = an unpinned second channel beside skills.lock). WATCH: a public web project or a design-system repo appearing; re-vendor the two fixing-* skills when they move."
  "herdr-app|https://github.com/herdrdev/herdr-app.git|f6fe216e3078225619621174e62b8b4d8cc56513|WATCH 2026-11-03 as an Orca alternative, not adopted (Rust native agent ADE, v0.1.12, repo created 2026-10-16, no GitHub release, 1.7k*). Wins on file-based themes/layouts/mods and SSH machines. Loses on: no phone client found, status only via OSC 7501 (unconfirmed for Claude Code), and switching orphans the vendored orca-cli + orchestration skills. HEAD moves daily, so a MOVED row alone means nothing. Re-evaluate only when the repo has a tagged release (gh api repos/herdrdev/herdr-app/releases) or a mobile client lands."
  "obscura|https://github.com/h4ckf0r0day/obscura.git|3e811654bd7e86f003ea55b78aab1b420aef7a1a|Rust headless browser (own V8+DOM+renderer, not Chromium; CDP, MCP server, one SKILL.md), 30.2k*, Apache-2.0. REJECTED 2026-11-03, nothing vendored. No gap: WebFetch reads pages, Claude in Chrome and the built-in browser drive real Chromium with sign-ins, and no journal, vault or memory entry records a JS-rendered page Jacob failed to read. Its edge is stealth scraping (fingerprint randomization, tracker blocking) and low per-session memory, neither a Jacob job. Its own renderer makes it the wrong tool for checking web UI. README ships tarballs and Nix only, so bootstrap and check-updates would gain a hand-managed binary. skills/obscura/SKILL.md is a manual for that binary, worthless without it. Re-triage only if a headless session (cron or cloud, no Chrome) needs JS-rendered pages that WebFetch cannot read."
  "context-mode|https://github.com/mksglu/context-mode.git|7164222685f71510e26bc0f60b177300fa370f4f|Claude Code plugin: MCP sandbox (ctx_execute, FTS5/BM25 ctx_search) + 6 hooks, 33.3k*, ELv2. REJECTED 2026-11-03, nothing vendored. No gap: rtk shrinks Bash output, memsearch + Claude Code compaction carry continuity, and no journal records a compaction loss. Conflicts: its PreToolUse Bash hook rewrites updatedInput beside rtk's (two writers on one input); it denies every WebFetch and turns curl/wget into an echo; SessionStart injects an ~8 KB routing block whose artifact_policy (return only path + 1 line) is a second home for answer shape against jacob-plain. Its Read hook is advisory and MCP output is not shrunk, so caveman's Read/MCP watch stays open. Pinned forward to HEAD: the verdict rests on these conflicts, not a commit. Re-triage only if it ships a hook-only mode that shrinks Read/MCP output without routing the model to new tools."
  "gstack|https://github.com/garrytan/gstack.git|9af5e540402bc161935814f85c0966ae32e069ac|Garry Tan skill pack, 138.8k stars, MIT. Triaged 2026-11-03: pack REJECTED, nothing vendored. Installer clones into ~/.claude/skills/gstack, which is Jacob/skills through the symlink, and symlinks about 70 skills beside it; team mode adds an hourly SessionStart auto-update, a standing second writer. Copy-vendoring also fails: every SKILL.md runs gstack/bin skill-start, telemetry and gbrain, so skills do not work without the runtime. Lifecycle skills all have superpowers or Jacob incumbents; ETHOS Boil the Ocean contradicts the judgment section's cutting rule; browser, iOS and deploy are out of domain. HARVESTED: Gate Integrity catalog into code-review-standards references/gate-integrity.md plus a verifier item, Unity C# tags; test-audit's four-question value bar into Framework Rules Testing. Careful/freeze guard not taken: use permissions.deny. WATCH review/gate-integrity.md and test-audit only. Re-triage the pack only if skills stop requiring gstack/bin."
  "voltagent-subagents|https://github.com/VoltAgent/awesome-claude-code-subagents.git|ed74d115b7fb7026a22a4f816a8e3250f425e3b4|REJECT 2026-11-03 (166 agents, 26.3k*, MIT). Vendored NOTHING. 126/166 share one template with a JSON protocol calling a context-manager agent that does not exist (129 files); install-agents.sh writes ~/.claude/agents = Jacob/agents; marketplace would add ~166 competing descriptions. csharp-developer is ASP.NET/Blazor, game-developer has one Unity line. Already a find-skills source (references/sources.md:33). Harvested the trigger line from surgeon-reviewer (upstream LucianFord/agent-pack) into agents/verifier.md. Watch for: a Unity or game-engine category with real content."
)
for entry in "${WATCHED_REPOS[@]}"; do
  IFS='|' read -r wname wurl wpin wnote <<< "$entry"
  whead=$(remote_head "$wurl" HEAD)
  if [ -z "$whead" ]; then
    printf '| %s | %s | — | ? repo unreachable |\n' "$wname" "$(short "$wpin")"
    unknown=$((unknown+1))
  elif [ "$wpin" = "$whead" ]; then
    printf '| %s | %s | %s | ✓ no change |\n' "$wname" "$(short "$wpin")" "$(short "$whead")"
    uptodate=$((uptodate+1))
  else
    # Size the move, so a 73-commit skill rewrite does not read like a 1-commit badge
    # bump. One compare call per moved GitHub repo; the API caps the file list at 300.
    wsize=""
    if [[ "$wurl" =~ github\.com/([^/]+)/([^/.]+) ]]; then
      wsize=$(curl -fsSL ${GH_AUTH[@]+"${GH_AUTH[@]}"} \
        "https://api.github.com/repos/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/compare/$wpin...$whead" 2>/dev/null \
        | jq -r '"+\(.ahead_by) commits, \(.files | length)\(if (.files | length) >= 300 then "+" else "" end) files"' 2>/dev/null)
    fi
    printf '| %s | %s | %s | ⬆ MOVED (%s) — review changelog for importable ideas, do NOT vendor |\n' \
      "$wname" "$(short "$wpin")" "$(short "$whead")" "${wsize:-size unknown}"
    behind=$((behind+1))
  fi
done
echo
echo "> Watched = idea-source only. A move is a prompt to skim upstream for something"
echo "> worth harvesting into a Jacob-native surface — never to clone/vendor/plugin-install."
echo "> After harvesting, bump the pinned commit in the WATCHED_REPOS array."

# --------------------------------- Description-overlap (routing collisions) ---
# §agent-engineering: the description is the whole routing signal, so overlapping descriptions
# mis-route (one prompt plausibly fires two skills). scripts/evals/overlap-audit.py measures
# description COMPETITION (TF-IDF cosine), not firing. Report-only, no network.
echo
echo "## 7. Skill/agent description overlap (routing-collision audit)"
echo
if command -v python3 >/dev/null 2>&1 && [ -f "$JACOB_ROOT/scripts/evals/overlap-audit.py" ]; then
  echo '```'
  python3 "$JACOB_ROOT/scripts/evals/overlap-audit.py" 0.35
  echo '```'
  echo
  echo "> Competition, not a verdict — a flagged pair may be intentional (a skill + its agent"
  echo "> twin). For real firing behavior, run scripts/evals/run-trigger-eval.sh (§agent-engineering)."
else
  echo "- (python3 or scripts/evals/overlap-audit.py absent — overlap audit skipped)"
fi

# ------------------------------------------------- Resident context weight ---
# §agent-engineering: "Context is the scarce resource... before adding anything always-resident,
# ask what it displaces." The ruleset is loaded on EVERY turn of EVERY tool, so its
# size is a standing cost, not a one-off. There is no correct absolute cap — the
# actionable signal is DIRECTION: did the always-resident set grow since the last
# commit, and was that growth traded against something removed? Measured against
# git HEAD so it needs no stored baseline. ~4 bytes/token is a rough English
# estimate, not a tokenizer — treat it as a trend line, not an invoice.
echo
echo "## 8. Resident context weight (always-loaded, every turn)"
echo
echo "| file | bytes | ~tokens | vs HEAD |"
echo "|---|---|---|---|"
resident_now=0; resident_head=0
for rf in AGENTS.md; do
  [ -f "$JACOB_ROOT/$rf" ] || continue
  now=$(wc -c < "$JACOB_ROOT/$rf" | tr -d ' ')
  head_b=$( (cd "$JACOB_ROOT" && git show "HEAD:$rf" 2>/dev/null | wc -c) | tr -d ' ')
  resident_now=$((resident_now+now))
  [ -n "$head_b" ] && [ "$head_b" -gt 0 ] 2>/dev/null && resident_head=$((resident_head+head_b))
  delta=$((now-head_b))
  if [ "$delta" -gt 0 ]; then d="+$delta B (+$((delta/4)) tok)"
  elif [ "$delta" -lt 0 ]; then d="$delta B ($((delta/4)) tok)"
  else d="unchanged"; fi
  printf '| %s | %s | ~%s | %s |\n' "$rf" "$now" "$((now/4))" "$d"
done
echo
printf -- '- Always-resident total: **~%s tokens** (%s bytes)' "$((resident_now/4))" "$resident_now"
if [ "$resident_head" -gt 0 ]; then
  rdelta=$((resident_now-resident_head))
  pct=$(( resident_head > 0 ? (rdelta*100)/resident_head : 0 ))
  printf -- ' — %s%s%% vs HEAD\n' "$([ "$rdelta" -ge 0 ] && echo '+')" "$pct"
  if [ "$pct" -ge 5 ]; then
    echo "- ⚑ **grew ≥5% since HEAD.** §agent-engineering gate: name what this displaced. If nothing was"
    echo "  removed, the addition is competing for attention on every turn of every tool —"
    echo "  push the detail into a gated \`references/\` file and leave a §-row pointer."
  fi
else
  printf -- '\n'
fi
echo
echo "> Direction, not a cap. Detail belongs one gate away (§context READ FIRST rows); the"
echo "> resident file carries invariants and indexes only."

# --------------------------------------------- Obsidian vault environment ---
# §vault's vault is the one Jacob dependency that lives OUTSIDE git: the Obsidian
# desktop app and its community plugins are installed by hand, in a GUI, and drift
# with no local pin to compare against. obsidianmd/obsidian-releases is the canonical
# registry, so it answers all three questions cheaply: is the app behind, was a plugin
# pulled from the catalog, is the installed version deprecated. Plugins are keyed by
# MANIFEST id, not folder name — they diverge (Thino ships in a thino/ folder declaring
# id obsidian-memos), and a folder not in the registry is self-distributed (BRAT), which
# means no review and no removal signal, not necessarily abandoned.
echo
echo "## 9. Obsidian vault environment (§vault — installed by hand, no git pin)"
echo
VAULT_DIR="${VAULT_DIR:-$JACOB_ROOT/vault}"
OBS_APP="${OBS_APP:-/Applications/Obsidian.app}"
REG_BASE="https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master"

if [ ! -d "$VAULT_DIR/.obsidian" ]; then
  echo "- (no \`$VAULT_DIR/.obsidian\` — vault environment check skipped)"
else
  reg_ok=true
  for f in desktop-releases community-plugins community-plugins-removed community-plugin-deprecation; do
    curl -fsSL --max-time 25 "$REG_BASE/$f.json" -o "$CACHE/$f.json" 2>/dev/null || reg_ok=false
    [ -s "$CACHE/$f.json" ] || reg_ok=false
  done

  if [ "$reg_ok" != true ]; then
    echo "- ? obsidian-releases registry unreachable — app/plugin freshness unknown this run."
    unknown=$((unknown+1))
  else
    # --- desktop app: installer version on disk vs latest published ---
    latest=$(jq -r '.latestVersion // empty' "$CACHE/desktop-releases.json")
    installer=""
    [ -f "$OBS_APP/Contents/Info.plist" ] && installer=$(defaults read "$OBS_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null)
    running=""
    command -v obsidian >/dev/null 2>&1 && running=$(obsidian version 2>/dev/null | head -1)
    if [ -z "$installer" ]; then
      echo "- ? Obsidian.app not found at \`$OBS_APP\` — desktop version unknown."
      unknown=$((unknown+1))
    else
      # Obsidian self-updates in place, so Info.plist pins the INSTALLER, not the build
      # actually running — they legitimately differ (1.13.7 running on a 1.12.7 installer).
      # The running build is the truth; fall back to the installer only when Obsidian is
      # closed, and say so rather than reporting a version gap that does not exist.
      run_ver=${running%% *}
      if [ "${run_ver:-$installer}" = "$latest" ]; then
        echo "- ✓ Obsidian **$latest** — current."
        [ -n "$run_ver" ] && [ "$installer" != "$latest" ] && \
          echo "  - (installer bundle still reports $installer; the app self-updated in place — not drift.)"
        uptodate=$((uptodate+1))
      elif [ -n "$run_ver" ]; then
        echo "- ⬆ Obsidian **$run_ver** running vs latest **$latest** — update in-app."
        behind=$((behind+1))
      else
        echo "- ~ Obsidian installer **$installer** vs latest **$latest**; could not query the"
        echo "  running build (\`obsidian version\` needs Obsidian open with command line access"
        echo "  enabled), so this may be a stale installer string rather than a real gap."
        unknown=$((unknown+1))
      fi
    fi

    # --- community plugins: resolve folder -> manifest id, then ask the registry ---
    echo
    echo "| folder | manifest id | version | enabled | status |"
    echo "|---|---|---|---|---|"
    enabled_json="$VAULT_DIR/.obsidian/community-plugins.json"
    : > "$CACHE/seen_ids"
    for pdir in "$VAULT_DIR"/.obsidian/plugins/*/; do
      [ -d "$pdir" ] || continue
      folder=$(basename "$pdir")
      man="$pdir/manifest.json"
      if [ ! -f "$man" ]; then
        printf '| %s | — | — | — | ? no manifest.json |\n' "$folder"; unknown=$((unknown+1)); continue
      fi
      pid=$(jq -r '.id // empty' "$man"); pver=$(jq -r '.version // empty' "$man")
      on="no"
      [ -f "$enabled_json" ] && jq -e --arg f "$folder" 'index($f) != null' "$enabled_json" >/dev/null 2>&1 && on="**yes**"
      printf '%s\t%s\n' "$pid" "$folder" >> "$CACHE/seen_ids"

      removed_reason=$(jq -r --arg id "$pid" 'map(select(.id==$id)) | .[0].reason // empty' "$CACHE/community-plugins-removed.json")
      deprecated=$(jq -r --arg id "$pid" --arg v "$pver" '((.[$id] // []) | index($v)) != null' "$CACHE/community-plugin-deprecation.json")
      listed=$(jq -r --arg id "$pid" 'any(.[]; .id==$id)' "$CACHE/community-plugins.json")

      if [ -n "$removed_reason" ]; then
        st="⬆ REMOVED from catalog — $removed_reason"; behind=$((behind+1))
      elif [ "$deprecated" = "true" ]; then
        st="⬆ version $pver DEPRECATED upstream — update it"; behind=$((behind+1))
      elif [ "$listed" = "true" ]; then
        st="✓ listed"; uptodate=$((uptodate+1))
      else
        st="~ not in registry (self-distributed/BRAT — no review or removal signal)"; unknown=$((unknown+1))
      fi
      printf '| %s | %s | %s | %s | %s |\n' "$folder" "${pid:-—}" "${pver:-—}" "$on" "$st"
    done

    # --- two folders declaring one id: Obsidian enables by folder, resolves by id ---
    dupes=$(cut -f1 "$CACHE/seen_ids" | sort | uniq -d)
    if [ -n "$dupes" ]; then
      echo
      for d in $dupes; do
        echo "- ⚑ **duplicate install:** id \`$d\` is declared by $(grep -c "^$d	" "$CACHE/seen_ids") folders —"
        grep "^$d	" "$CACHE/seen_ids" | while IFS=$'\t' read -r _ fol; do
          echo "  - \`$fol\` (v$(jq -r '.version // "?"' "$VAULT_DIR/.obsidian/plugins/$fol/manifest.json"))"
        done
        echo "  Obsidian enables by FOLDER but resolves identity by manifest id, so the enabled"
        echo "  folder wins even when a newer copy sits beside it. Delete the one you are not running."
        review=$((review+1))
      done
    fi
  fi
  echo
  echo "> Registry-sourced, report-only. A plugin is installed through Obsidian's GUI, so"
  echo "> applying any of this is a manual step in the app — never a script action (§workspace)."
fi

# ------------------------------------------------------------------ Summary ---
echo
echo "## Summary"
echo
echo "- ⬆ behind: $behind   ✓ up-to-date: $uptodate   ⚑ adapted (review): $review   ~/? needs manual check: $unknown"
echo "- Applying updates is a separate, per-item, human-gated step — see skills/check-updates/SKILL.md §Apply."
exit 0
