#!/usr/bin/env bash
#
# fold-journals.sh — move journals past the retention window out of the index.
#
# Why this exists (gap 4, decided 2026-09-27):
#
#   .memsearch/memory/ only ever grows. 49 files, 1.7 MB over five months, with
#   no mechanism to retire anything. Every recall searches the whole pile, and
#   four-month-old episodic context competes with today's.
#
# Why this ARCHIVES instead of summarizing:
#
#   `memsearch compact` looks like the tool for this and is not. Its --source
#   takes one file, not a month, and core.py:283 appends its summary back into
#   memory/YYYY-MM-DD.md — it grows the corpus it was meant to shrink. It also
#   ships journal text to an LLM, and these journals carry transcript paths and
#   are pushed to a public remote.
#
#   Moving the file out of the indexed root does the whole job for free.
#   prune-orphans.py then evicts its chunks, because the source path is gone.
#   Nothing is deleted: the file stays on disk and stays tracked in git, so
#   grep and git log still reach it. Reversible with one `git mv` back.
#
# Retention: 3 months. §3.5 splits the layers — vault/ holds the durable
# knowledge, .memsearch/memory/ holds "where we left off". Episodic context
# older than a quarter is not where-we-left-off any more.
#
# Usage:
#   scripts/memsearch/fold-journals.sh              # dry run, lists what would move
#   scripts/memsearch/fold-journals.sh --apply      # move them, then prune the index
#   RETAIN_MONTHS=6 scripts/memsearch/fold-journals.sh --apply
#
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
MEMORY_DIR="$JACOB_ROOT/.memsearch/memory"
ARCHIVE_DIR="$JACOB_ROOT/.memsearch/archive"
RETAIN_MONTHS="${RETAIN_MONTHS:-3}"

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

[ -d "$MEMORY_DIR" ] || { echo "no journal dir: $MEMORY_DIR" >&2; exit 1; }

# Cutoff in python3, not `date -v`, so this is not BSD-only.
CUTOFF="$(python3 -c "
import datetime
m = $RETAIN_MONTHS
t = datetime.date.today()
y, mo = t.year, t.month - m
while mo <= 0:
    mo += 12; y -= 1
print(datetime.date(y, mo, min(t.day, 28)).isoformat())
")"
[ -n "$CUTOFF" ] || { echo "could not compute cutoff" >&2; exit 1; }

echo "retention: $RETAIN_MONTHS month(s) — journals dated before $CUTOFF"
[ "$APPLY" -eq 1 ] || echo "(dry run — pass --apply to move them)"

moved=0
total_kb=0
for f in "$MEMORY_DIR"/*.md; do
  [ -f "$f" ] || continue
  day="$(basename "$f" .md)"
  # Only fold YYYY-MM-DD journals. Anything else in here is not ours to move.
  case "$day" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) continue ;;
  esac
  [[ "$day" < "$CUTOFF" ]] || continue

  month="${day%-*}"
  kb=$(( $(wc -c < "$f") / 1024 ))
  total_kb=$((total_kb + kb))
  moved=$((moved + 1))

  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$ARCHIVE_DIR/$month"
    # git mv when tracked, so history follows the file; plain mv otherwise.
    if git -C "$JACOB_ROOT" ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      git -C "$JACOB_ROOT" mv "$f" "$ARCHIVE_DIR/$month/$day.md"
    else
      mv "$f" "$ARCHIVE_DIR/$month/$day.md"
    fi
    printf '  moved %s -> archive/%s/ (%d KB)\n' "$day" "$month" "$kb"
  else
    printf '  would move %s -> archive/%s/ (%d KB)\n' "$day" "$month" "$kb"
  fi
done

if [ "$moved" -eq 0 ]; then
  echo "nothing older than $CUTOFF — index unchanged"
  exit 0
fi

echo "$moved journal(s), $total_kb KB"

if [ "$APPLY" -eq 1 ]; then
  # Their chunks are now orphaned, because the source path no longer exists.
  "$("$(dirname "$0")/ms-python.sh" || echo python3)" "$(dirname "$0")/prune-orphans.py"
fi
