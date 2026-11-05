#!/usr/bin/env bash
#
# backup-transcripts.sh — copy Claude Code session transcripts out from under
# Anthropic's 30-day delete.
#
# Why this exists (measured 2026-09-07, mempalace triage):
#
#   .memsearch/memory/*.md is a LOSSY layer. Each entry carries a provenance
#   backlink of the form `transcript:/Users/.../<session>.jsonl`, and those
#   files live in ~/.claude/projects, which Claude Code prunes after 30 days
#   (docs.claude.com/en/docs/claude-code/data-usage). No cleanupPeriodDays is
#   set here, so the default clock is running.
#
#   At the time this was written, 115 of 148 referenced transcripts were
#   already gone — 78% of the journal's own provenance, destroyed silently.
#   The summary survived; the verbatim source did not. This script is the
#   raw-archive floor under memsearch (episodic) and vault (curated).
#
#   It is deliberately rsync and nothing else. The alternative considered and
#   rejected was MemPalace (163k LOC, second vector store, turn-blocking
#   hooks) — see scripts/check-updates.sh WATCHED_REPOS. A verbatim archive does
#   not need a daemon.
#
# It NEVER deletes, modifies, or writes inside ~/.claude/. Re-run any time.
#
# Usage:
#   scripts/backup-transcripts.sh            # incremental sync
#   scripts/backup-transcripts.sh --dry-run  # show what would copy
#
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
SRC="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
# Default lives under ~/Documents because that is what Time Machine / iCloud
# actually back up. Overridable, but never inside the repo — see guard below.
DST="${JACOB_TRANSCRIPT_ARCHIVE:-$HOME/Documents/Claude_Transcripts}"

DRY=""; [ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

[ -d "$SRC" ] || { echo "backup-transcripts: no transcripts at $SRC — nothing to do"; exit 0; }

# The archive grows without bound (178 MB at first run). Jacob's repo versions
# docs and config only (§workspace), so an archive inside it would be committed.
case "$(cd "${DST%/*}" 2>/dev/null && pwd)/${DST##*/}" in
  "$JACOB_ROOT"|"$JACOB_ROOT"/*)
    echo "backup-transcripts: refusing to archive inside JACOB_ROOT ($DST)" >&2; exit 1 ;;
esac

mkdir -p "$DST" || exit 1
rsync -a --times $DRY "$SRC/" "$DST/" || { echo "backup-transcripts: rsync failed" >&2; exit 1; }

src_n=$(find "$SRC" -type f -name '*.jsonl' | wc -l | tr -d ' ')
dst_n=$(find "$DST" -type f -name '*.jsonl' | wc -l | tr -d ' ')
printf 'backup-transcripts: %s live → %s archived%s\n  %s\n' \
  "$src_n" "$dst_n" "${DRY:+ (dry run)}" "$DST"
# dst < src would mean the sync did not take; dst > src is normal and is the
# whole point — those are the sessions Claude Code has already deleted.
[ "${DRY:-}" = "--dry-run" ] || [ "$dst_n" -ge "$src_n" ] || {
  echo "backup-transcripts: archive has FEWER files than live — sync incomplete" >&2; exit 1; }
