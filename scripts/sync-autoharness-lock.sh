#!/usr/bin/env bash
# sync-autoharness-lock.sh — keep skills.lock.json in step with the skills the autoharness plugin
# writes into skills/ (its global layer is ~/.claude/skills, which IS this folder via the spine).
#
# autoharness lands, patches, merges and archives its own skills from a background session, so no
# hook event marks "a skill just landed". The pre-commit gate runs this first, then doctor.sh, so the
# lock is correct at the exact moment Check 1 reads it. Safe to run by hand any time.
#
# Ownership: a folder is autoharness's when its .sidecar.json says "created_by": "agent". This script
# only ever adds, updates or removes lock entries whose source is "autoharness" — never yours.
# It writes the lock only when something changed, via temp file + rename (concurrent sessions).
set -euo pipefail

JACOB_ROOT="${JACOB_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SKILLS="$JACOB_ROOT/skills"
LOCK="$SKILLS/skills.lock.json"
command -v jq >/dev/null 2>&1 || { echo "sync-autoharness-lock: jq missing, skipped" >&2; exit 0; }
[ -f "$LOCK" ] || exit 0

# One JSON object per autoharness skill on disk: {name, description, file_count}.
found=$(for d in "$SKILLS"/*/; do
  dir="${d%/}"; name=$(basename "$dir")
  [ "$(jq -r '.created_by // ""' "$dir/.sidecar.json" 2>/dev/null)" = "agent" ] || continue
  desc=$(awk 'NR==1 && $0!="---"{exit} NR>1 && $0=="---"{exit}
              NR>1 && /^description:/{sub(/^description:[ ]*/,""); print; exit}' "$dir/SKILL.md" 2>/dev/null \
         | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')
  count=$(find "$dir" -type f ! -name '.sidecar.json' ! -name '.ledger.jsonl' ! -name '*.lock' | wc -l | tr -d ' ')
  jq -n --arg n "$name" --arg d "$desc" --argjson c "$count" '{name:$n, description:$d, file_count:$c}'
done | jq -s '.')

now=$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)
new=$(jq --argjson found "$found" --arg now "$now" '
  ($found | map({key: .name, value: .}) | from_entries) as $f
  | .skills |= (
      # drop autoharness entries whose folder is gone (archived or merged away)
      with_entries(select(.value.source != "autoharness" or ($f[.key] != null)))
      # add new ones, refresh changed ones; never touch an entry another source owns
      | reduce ($found[]) as $s (.;
          if .[$s.name] == null then
            .[$s.name] = {name: $s.name, description: $s.description, source: "autoharness",
                          installed_at: $now, updated_at: $now, version: null,
                          files_hash: null, file_count: $s.file_count, update_policy: "native"}
          elif .[$s.name].source == "autoharness"
               and (.[$s.name].description != $s.description or .[$s.name].file_count != $s.file_count) then
            .[$s.name] += {description: $s.description, file_count: $s.file_count, updated_at: $now}
          else . end))' "$LOCK")

# Name collision: autoharness folder whose lock entry belongs to someone else. Report, don't fix.
jq -r --argjson found "$found" '$found[].name as $n | select(.skills[$n].source != "autoharness") | $n' <<<"$new" \
  | while read -r n; do echo "sync-autoharness-lock: skills/$n has an autoharness sidecar but a non-autoharness lock entry — left alone" >&2; done

if [ "$new" != "$(cat "$LOCK")" ]; then
  tmp=$(mktemp "$SKILLS/.skills.lock.json.XXXXXX")
  printf '%s\n' "$new" > "$tmp" && chmod 644 "$tmp" && mv "$tmp" "$LOCK"
  echo "sync-autoharness-lock: skills.lock.json updated (not staged — commit it with the next batch)" >&2
fi
