#!/usr/bin/env bash
#
# vault-lag.sh — report which vault wiki pages are older than the code
# they document.
#
# Why this exists: §vault states "the vault lags the code; the code wins" and then
# gives no way to tell WHICH page lags. Pages already carry `updated:` and a
# project-relative `path:`; .vault-meta/source-roots.json supplies the missing
# half, the project checkout each group folder documents. This joins the three.
#
# Read-only. Deterministic, so wiki-lint invokes it rather than re-deriving the
# comparison in prose (§agent-engineering: if it must run reliably it is not a probability).
#
# Freshness comes from `git log -1 --format=%cs -- <path>` when the project is a
# git checkout, because a fresh clone resets every file mtime and would report
# the whole vault as stale. Mtime is the fallback for non-git trees.
#
# Usage: scripts/vault-lag.sh
# Exit:  0 = no page lags · 2 = at least one lags · 1 = could not run
#
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
VAULT="$JACOB_ROOT/vault"
MAP="$VAULT/.vault-meta/source-roots.json"

[ -d "$VAULT/wiki" ] || { echo "vault-lag: no wiki/ at $VAULT" >&2; exit 1; }
[ -f "$MAP" ] || { echo "vault-lag: no source-roots.json — every page unverifiable" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "vault-lag: python3 required" >&2; exit 1; }

fm() { awk -v k="^$2:" '/^---$/{n++;next} n==1 && $0~k {sub(/^[a-z_]+: */,""); gsub(/"/,""); print; exit}' "$1"; }

lagging=0; checked=0; unverifiable=0
while IFS= read -r page; do
  pth="$(fm "$page" path)";  [ -n "$pth" ] || continue
  upd="$(fm "$page" updated)"; [ -n "$upd" ] || continue
  group="$(basename "$(dirname "$page")")"
  root="$(python3 -c "import json,sys; print(json.load(open('$MAP'))['roots'].get('$group') or '')" 2>/dev/null)"
  # A brace set (`Scripts/{UI,Utilities}`) documents several siblings; compare
  # against their common parent rather than dropping the page from the report.
  [ "${pth}" != "${pth%%\{*}" ] && pth="${pth%%\{*}"
  tgt="$root/${pth%/}"
  if [ -z "$root" ] || [ ! -e "$tgt" ]; then
    if [ -z "$root" ]; then why="group '$group' has no root in source-roots.json"
    else why="path not in $(basename "$root"): ${pth%/}"; fi
    printf '  ?  %-42s unverifiable — %s\n' "$(basename "$page")" "$why"
    unverifiable=$((unverifiable+1)); continue
  fi
  checked=$((checked+1))
  code_date="$(cd "$root" && git log -1 --format=%cs -- "${pth%/}" 2>/dev/null)"
  [ -n "$code_date" ] || code_date="$(date -r "$tgt" +%F 2>/dev/null)"
  if [[ "$code_date" > "$upd" ]]; then
    printf '  ✗  %-42s page %s < code %s\n' "$(basename "$page")" "$upd" "$code_date"
    lagging=$((lagging+1))
  else
    printf '  ✓  %-42s page %s ≥ code %s\n' "$(basename "$page")" "$upd" "$code_date"
  fi
done <<< "$(find "$VAULT/wiki" -name '*.md' -type f | sort)"

printf '\nvault-lag: %d lagging, %d current, %d unverifiable\n' \
  "$lagging" "$((checked-lagging))" "$unverifiable"
[ "$lagging" -eq 0 ] && exit 0 || exit 2
