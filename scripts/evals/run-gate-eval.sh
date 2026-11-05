#!/usr/bin/env bash
# Gate eval — does a session READ the gated reference file before it answers a coding prompt?
#
# §context says a READ FIRST row must be read before you write code in that area. This is the
# behavior check for that rule: a real `claude -p` session runs each prompt in a real project
# directory, and the saved tool-call stream says which files it opened.
#
# WHAT IT MEASURES (and what it does not): whether a `Read`, `Grep` or `Glob` call names the gate
# file. It does NOT show the file was understood, that the answer obeyed it, or that the read
# came BEFORE the code. It also counts a read that returned an error, since the call still names
# the file. A pass means "the session looked"; it does not mean "the answer is right."
#
# SAFETY: `--tools` is an allow-list. The session gets Read, Grep, Glob and Skill, and MCP is
# empty. A deny-list was tried first and missed about 11 built-in tools (CronCreate,
# PublishPlugin, SendMessage, ...), so do not go back to `--disallowedTools`.
# --permission-mode bypassPermissions is there because, without it, a permission prompt in -p
# mode would silently deny the read of a gate file and score a FAIL the model did not earn.
# It is safe only because of the allow-list.
# --no-session-persistence keeps eval sessions out of ~/.claude/projects, where they would
# pollute any later transcript audit of the case's project. Plugin hooks still fire, so the
# harness is the real one.
#
# VERDICTS
#   PASS          every gate was read (control case: no watched file was read)
#   FAIL          a gate was never read (control case: a watched file was read)
#   INCONCLUSIVE  expects_code is true, no gate was read, and the final answer holds no fenced
#                 code block. The session stopped before writing code, so it never reached the
#                 decision under test. Re-run these. Do not count them as a gate failure.
#
# NOT DETERMINISTIC. Like the trigger eval, one failure is not a finding. Re-run the case
# before changing a rule on the strength of it.
#
# Cost: one full tool-using session per case (the --verbose stream carries the real
# total_cost_usd). Draws on your own session quota. Filter to the case you care about.
#
# Usage:
#   ./scripts/evals/run-gate-eval.sh                       # all cases
#   ./scripts/evals/run-gate-eval.sh unitask               # only cases whose id contains "unitask"
#   MODEL=haiku ./scripts/evals/run-gate-eval.sh control   # cheap dry run
#   OUT_DIR=./out ./scripts/evals/run-gate-eval.sh         # keep raw streams somewhere known
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
CASES="$JACOB_ROOT/scripts/evals/gate-cases.jsonl"
MODEL="${MODEL:-sonnet}"
FILTER="${1:-}"
OUT_DIR="${OUT_DIR:-$(mktemp -d)}"

command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }
command -v claude >/dev/null || { echo "claude CLI required" >&2; exit 1; }
[ -f "$CASES" ] || { echo "missing $CASES" >&2; exit 1; }
mkdir -p "$OUT_DIR" || { echo "cannot create OUT_DIR $OUT_DIR" >&2; exit 1; }

# --- Pre-flight: pick the cases, and check every cwd before any model call ----------
# A missing cwd would otherwise surface as a CLI failure and abort a run that cost money.
n_sel=0
while IFS= read -r line <&3; do
  [ -n "$line" ] || continue
  id=$(printf '%s' "$line" | jq -r '.id')
  if [ -n "$FILTER" ] && [[ "$id" != *"$FILTER"* ]]; then continue; fi
  cwd=$(printf '%s' "$line" | jq -r '.cwd')
  [ -d "$cwd" ] || { echo "case $id: cwd does not exist: $cwd" >&2; exit 1; }
  n_sel=$((n_sel+1))
done 3< "$CASES"
[ "$n_sel" -gt 0 ] || { echo "no case id contains '$FILTER'" >&2; exit 1; }

# --- Stream helpers -----------------------------------------------------------------
# `fromjson?` skips any non-JSON line instead of killing the parse.
# tool_uses: one compact {id,name,input} object per tool_use block in any assistant message.
# awk drops exact duplicate lines, so a block that appears twice in the stream counts once.
tool_uses() {
  jq -cR 'fromjson? | select(.type=="assistant") | .message.content[]?
          | select(.type=="tool_use") | {id, name, input}' "$1" | awk '!seen[$0]++'
}
# result_line: the last `result` message in the stream, or nothing.
result_line() {
  jq -cR 'fromjson? | select(.type=="result")' "$1" | tail -1
}
# was_read <tool-uses-file> <basename>: succeeds when a Read, Grep or Glob call names the file.
was_read() {
  local n
  n=$(jq -c --arg g "$2" \
        'select((.name=="Read" or .name=="Grep" or .name=="Glob") and ((.input|tojson)|contains($g)))' \
        "$1" | wc -l | tr -d ' ')
  [ "$n" -gt 0 ]
}

echo "# Gate eval — $(date -u +%Y-%m-%dT%H:%MZ)"
echo
echo "model: $MODEL · cases: $n_sel · OUT_DIR: $OUT_DIR"
echo
printf '| id | model | gates read | gates missed | tool calls | cost USD | verdict |\n|---|---|---|---|---|---|---|\n'

pass=0; fail=0; inconclusive=0; i=0; total_cost=0
declare -a FAILURES=()

while IFS= read -r line <&3; do
  [ -n "$line" ] || continue
  id=$(printf '%s' "$line" | jq -r '.id')
  if [ -n "$FILTER" ] && [[ "$id" != *"$FILTER"* ]]; then continue; fi
  i=$((i+1))

  cwd=$(printf '%s' "$line" | jq -r '.cwd')
  prompt=$(printf '%s' "$line" | jq -r '.prompt')
  expects_code=$(printf '%s' "$line" | jq -r '.expects_code // false')
  control=$(printf '%s' "$line" | jq -r '.control // false')
  gates=$(printf '%s' "$line" | jq -r '(.gates // []) | join(" ")')
  watch=$(printf '%s' "$line" | jq -r '(.watch // []) | join(" ")')

  raw="$OUT_DIR/$id.jsonl"
  err="$OUT_DIR/$id.stderr"

  # `</dev/null`: the case file is read on fd 3, but claude must not touch any stdin either.
  # --mcp-config takes inline JSON (confirmed in `claude --help`). --max-turns is not listed
  # by `claude --help`, so it is not passed.
  ( cd "$cwd" && claude -p "$prompt" \
      --model "$MODEL" \
      --output-format stream-json --verbose \
      --permission-mode bypassPermissions \
      --tools Read Grep Glob Skill \
      --no-session-persistence \
      --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
      --add-dir "$JACOB_ROOT" \
      </dev/null ) >"$raw" 2>"$err"
  rc=$?

  res=$(result_line "$raw")
  is_error=true
  [ -n "$res" ] && is_error=$(printf '%s' "$res" | jq -r '.is_error // false')

  # A CLI failure (quota, auth, network, crash) is not a gate verdict. Scoring it would
  # manufacture a number, so abort. No result message, a non-zero exit, or is_error all count.
  if [ "$rc" -ne 0 ] || [ -z "$res" ] || [ "$is_error" != "false" ]; then
    echo
    echo "**ABORTED at case $i ($id) — the CLI did not return a clean result.**"
    echo
    echo "exit code: $rc · result message: $([ -n "$res" ] && echo present || echo missing) · is_error: $is_error"
    echo
    echo '```'
    {
      [ -n "$res" ] && printf '%s' "$res" | jq -r '.result // empty'
      cat "$err"
      [ -z "$res" ] && tail -n 5 "$raw"
    } 2>/dev/null | head -8
    echo '```'
    echo
    echo "Ran $((i-1)) of $n_sel cases; **$pass passed, $fail failed, $inconclusive inconclusive** in that partial run."
    echo "This is a partial result — do NOT quote it as a pass rate, and do not change any"
    echo "rule from it. Re-run when the cause above is cleared. Raw stream: $raw"
    exit 2
  fi

  cost=$(printf '%s' "$res" | jq -r '.total_cost_usd // 0')
  answer=$(printf '%s' "$res" | jq -r '.result // ""')
  total_cost=$(awk -v a="$total_cost" -v b="$cost" 'BEGIN{printf "%.6f", a+b}')

  tu="$OUT_DIR/$id.tooluse.jsonl"
  tool_uses "$raw" > "$tu"
  n_tools=$(wc -l < "$tu" | tr -d ' ')

  has_fence=false
  printf '%s\n' "$answer" | grep -qE '^[[:space:]]*(```|~~~)' && has_fence=true

  read_list=""; missed_list=""; verdict=""
  if [ "$control" = "true" ]; then
    # Control: a concept question that needs no READ FIRST row. Reading a watched file is the failure.
    for w in $watch; do
      was_read "$tu" "$w" && read_list="${read_list:+$read_list, }$w"
    done
    if [ -z "$read_list" ]; then verdict="PASS"; else verdict="FAIL"; fi
    gates_read_cell="control: watched read ${read_list:-none}"
    gates_missed_cell="-"
  else
    for g in $gates; do
      if was_read "$tu" "$g"; then read_list="${read_list:+$read_list, }$g"
      else missed_list="${missed_list:+$missed_list, }$g"; fi
    done
    if [ -z "$missed_list" ]; then verdict="PASS"
    elif [ "$expects_code" = "true" ] && [ -z "$read_list" ] && [ "$has_fence" = "false" ]; then
      verdict="INCONCLUSIVE"
    else verdict="FAIL"; fi
    gates_read_cell="${read_list:--}"
    gates_missed_cell="${missed_list:--}"
  fi

  case "$verdict" in
    PASS) pass=$((pass+1)) ;;
    INCONCLUSIVE) inconclusive=$((inconclusive+1)); FAILURES+=("$id|$verdict|$gates_read_cell|$gates_missed_cell|$has_fence") ;;
    *) fail=$((fail+1)); FAILURES+=("$id|$verdict|$gates_read_cell|$gates_missed_cell|$has_fence") ;;
  esac

  printf '| %s | %s | %s | %s | %s | %.4f | %s |\n' \
    "$id" "$MODEL" "$gates_read_cell" "$gates_missed_cell" "$n_tools" "$cost" "$verdict"
done 3< "$CASES"

echo
echo "**$pass/$i passed** · INCONCLUSIVE: $inconclusive · FAIL: $fail · total cost: \$$(printf '%.4f' "$total_cost")"

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo
  echo "## Not passed — read before changing any rule"
  echo
  for f in "${FAILURES[@]}"; do
    IFS='|' read -r fid fv fr fm ff <<< "$f"
    echo "**$fid** — $fv"
    echo "- read: $fr · missed: $fm · answer had a fenced code block: $ff"
    echo "- stream: $OUT_DIR/$fid.jsonl · tool calls: $OUT_DIR/$fid.tooluse.jsonl"
    echo
  done
  echo "> INCONCLUSIVE means the session never wrote code, so the gate was never tested. Re-run it."
  echo "> A FAIL is a behavior signal, not automatically a rule bug: re-run before editing anything."
fi

# Exit 0 = every case ran (any verdict); the pass rate is real. Exit 2 = the run aborted
# mid-way and the numbers are partial. A FAIL alone never fails the run — this is a
# measurement, not a build gate (§agent-engineering).
exit 0
