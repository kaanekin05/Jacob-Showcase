#!/usr/bin/env bash
#
# reindex.sh — rebuild Jacob's memsearch index from its two markdown sources.
#
# Why this exists (two reasons, both learned the hard way 2026-08-30):
#
#  1. The memsearch plugin only ever watches/indexes .memsearch/memory/. Jacob
#     also wants vault/wiki/ in the SAME collection, so the
#     memory-recall skill can surface an authoritative WHY page next to the
#     episodic journal that references it (§3.5). core.py:127 only prunes
#     deleted files "inside directory roots from this run", so the watcher's
#     memory-dir passes never evict the vault chunks added here. The flip side
#     is that a renamed or deleted page leaks its chunks forever, so this script
#     calls prune-orphans.py after indexing. That leak cost 811 stale chunks,
#     23% of the whole index, before it was found on 2026-09-27.
#
#  2. Indexing a whole directory in one pass kills milvus_lite partway through
#     on this corpus ("Cannot invoke RPC on closed channel!"), leaving a
#     half-built collection. One short-lived index call per file completes
#     reliably. Slower, but it finishes.
#
# Usage:
#   scripts/memsearch/reindex.sh           # incremental (unchanged files skipped)
#   scripts/memsearch/reindex.sh --force   # re-embed everything
#
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
STATE="$JACOB_ROOT/.memsearch/.index-state.json"

# Collection name comes from the state file the plugin itself writes, so this
# script never has to re-derive the plugin's hashing scheme.
COLLECTION="$(python3 -c "import json,sys; print(json.load(open('$STATE'))['collection'])" 2>/dev/null || true)"
[ -n "$COLLECTION" ] || { echo "cannot resolve collection from $STATE" >&2; exit 1; }

FORCE=""
[ "${1:-}" = "--force" ] && FORCE="--force"

# index_one FILE: succeeds only when memsearch reports an Indexed line with no failed files.
# A failure still prints "Indexed 0 chunks from 0 files (1 files failed)", so matching
# "^Indexed" alone counted failures as successes. Retry once after 3 s: milvus_lite serves
# one process at a time, and a concurrent memsearch hook in another session makes a single
# call fail with "Fail connecting to server" (seen 2026-11-03; the retry indexed 28 chunks).
index_one() {
  local out try
  for try in 1 2; do
    out=$(memsearch index "$1" --collection "$COLLECTION" $FORCE 2>&1)
    if printf '%s\n' "$out" | grep -qE "^Indexed" \
       && ! printf '%s\n' "$out" | grep -qE "\([1-9][0-9]* files? failed\)|Exception"; then
      return 0
    fi
    [ "$try" = 1 ] && sleep 3
  done
  return 1
}

index_tree() {
  local root="$1" label="$2" ok=0 fail=0 failed=""
  [ -d "$root" ] || { printf '  %-22s (absent, skipped)\n' "$label"; return 0; }
  while IFS= read -r f; do
    if index_one "$f"; then
      ok=$((ok+1))
    else
      fail=$((fail+1)); failed="$failed $(basename "$f")"
    fi
  done <<< "$(find "$root" -name '*.md' -type f | sort)"
  printf '  %-22s %d indexed, %d failed%s\n' "$label" "$ok" "$fail" \
         "$([ -n "$failed" ] && echo ":$failed")"
  [ "$fail" -eq 0 ]
}

echo "collection: $COLLECTION ${FORCE:+(force)}"
rc=0
index_tree "$JACOB_ROOT/.memsearch/memory" "memory journals" || rc=1
index_tree "$JACOB_ROOT/vault/wiki" "vault wiki" || rc=1

# Evict chunks whose source file is gone. Indexing cannot do this for per-file
# passes (see reason 1 above), so it is a separate step.
"$("$(dirname "$0")/ms-python.sh" || echo python3)" "$(dirname "$0")/prune-orphans.py" || rc=1

memsearch stats --collection "$COLLECTION" 2>/dev/null | grep -i total
exit $rc
