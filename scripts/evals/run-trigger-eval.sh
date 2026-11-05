#!/usr/bin/env bash
# Trigger eval — does each prompt route to the skill we think it does?
#
# §agent-engineering: "The description: is load-bearing — it is the entire signal for firing a skill
# or routing to an agent... 'Better' requires an eval, not vibes." This is that eval.
#
# WHAT IT MEASURES (and what it does not): the model is handed the real roster —
# every name + description pulled live from the spine — and asked which single skill
# it would invoke for a prompt. That isolates the routing decision to the descriptions,
# which is the thing under test. It is NOT a full harness run: no skill body is read,
# no tool is called, and a skill can still misbehave after firing correctly. A pass
# here means "the description routes"; it does not mean "the skill works."
#
# Cost: one model call per case. Read-only — never edits a skill.
#
# ROUTING IS NOT DETERMINISTIC. Cases have flipped between back-to-back runs with no
# intervening change, so a single run cannot tell variance from a real regression.
# Before rewording anything on the strength of one failure, re-run that case with
# TRIALS=3 — a case that fails 3/3 is signal; 1/3 is noise, and rewriting a
# description to chase it is the "vibes, not evals" trap §agent-engineering warns about.
#
# Usage:
#   ./scripts/evals/run-trigger-eval.sh                 # all cases, 1 trial each
#   ./scripts/evals/run-trigger-eval.sh find-skills     # only cases whose expect/note matches
#   TRIALS=3 ./scripts/evals/run-trigger-eval.sh find-skills  # 3 trials/case, majority scored
#   MODEL=claude-sonnet-5 ./scripts/evals/run-trigger-eval.sh
set -uo pipefail

JACOB_ROOT="${JACOB_ROOT:-/Users/kaan/Workspace/Jacob}"
CASES="$JACOB_ROOT/scripts/evals/trigger-cases.jsonl"
SKILLS_DIR="$JACOB_ROOT/skills"
MODEL="${MODEL:-claude-opus-5}"
TRIALS="${TRIALS:-1}"
FILTER="${1:-}"
case "$TRIALS" in ''|*[!0-9]*|0) echo "TRIALS must be a positive integer" >&2; exit 1 ;; esac

command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }
command -v claude >/dev/null || { echo "claude CLI required" >&2; exit 1; }
[ -f "$CASES" ] || { echo "missing $CASES" >&2; exit 1; }

# --- Build the roster ----------------------------------------------------------
# Delegated to build-roster.py: the frontmatter uses folded '>-' blocks that a shell
# one-liner silently truncates to ">-", which puts skills in the roster with an empty
# description and reads as under-firing. Parse it properly (see that file's docstring).
roster=$(python3 "$JACOB_ROOT/scripts/evals/build-roster.py" 2>/dev/null)
[ -n "$roster" ] || { echo "roster build failed — run: python3 scripts/evals/build-roster.py" >&2; exit 1; }
n_roster=$(printf '%s\n' "$roster" | grep -c '^- ' || true)

echo "# Trigger eval — $(date -u +%Y-%m-%dT%H:%MZ)"
echo
echo "Roster: $n_roster entries (skills + agents + mirrored plugin skills) · model: $MODEL"
echo
printf '| # | prompt | expected | got | ok |\n|---|---|---|---|---|\n'

pass=0; fail=0; i=0
declare -a FAILURES=()

while IFS= read -r line; do
  [ -n "$line" ] || continue
  prompt=$(printf '%s' "$line" | jq -r '.prompt')
  expect=$(printf '%s' "$line" | jq -r '.expect')
  note=$(printf '%s'   "$line" | jq -r '.note // ""')

  if [ -n "$FILTER" ] && ! printf '%s %s' "$expect" "$note" | grep -qi -- "$FILTER"; then
    continue
  fi
  i=$((i+1))

  # The roster mixes skills and dispatchable agents. An earlier version of this prompt
  # said "at most one skill" and headed the list "Available skills:", so agent-shaped
  # cases scored `none` — the model was never told agents were an option. That looked
  # like a description problem and nearly cost two skills a needless rewrite.
  sys="You are routing a user prompt to at most one skill or agent.
Available skills and agents (some entries are agents you would dispatch rather than
skills you would load — both are valid answers):
$roster

Answer with ONLY the name exactly as listed, or the single word none if nothing
should fire. No punctuation, no explanation, no other words."

  # Run TRIALS times and take the majority answer; ties resolve to the first reply.
  # With TRIALS=1 this is exactly one call, same as before.
  declare -A tally=(); got=""; best=0; trial_detail=""
  t=0
  while [ "$t" -lt "$TRIALS" ]; do
    t=$((t+1))
    raw=$(printf '%s' "$prompt" \
      | claude -p --model "$MODEL" --append-system-prompt "$sys" 2>&1)
    rc=$?
    ans=$(printf '%s' "$raw" | tr -d '\r' | tr -s ' \n' ' ' | sed 's/^ *//; s/ *$//' | tr -d '`.')

    # Distinguish two very different non-answers:
    #   (a) the CLI failed — quota, auth, network. Scoring that as a routing miss
    #       manufactures a number that looks like a measurement, so ABORT.
    #   (b) the model named something not on the roster. That IS routing signal —
    #       score it as a normal failure and keep going.
    # (a) is recognised by a non-zero exit, empty output, or a reply too long to be
    # a name; anything else is treated as the model's answer.
    word_count=$(printf '%s' "$ans" | wc -w | tr -d ' ')
    if [ "$rc" -ne 0 ] || [ -z "$ans" ] || [ "$word_count" -gt 3 ]; then
      echo
      echo "**ABORTED at case $i (trial $t) — the CLI did not return a routing answer.**"
      echo
      echo '```'
      printf '%s\n' "$raw" | head -5
      echo '```'
      echo
      echo "Ran $((i-1)) of $(grep -c . "$CASES") cases; **$pass passed, $fail failed** in that partial run."
      echo "This is a partial result — do NOT quote it as a pass rate, and do not reword any"
      echo "description from it. Re-run when the cause above is cleared."
      exit 2
    fi

    tally["$ans"]=$(( ${tally["$ans"]:-0} + 1 ))
    if [ "${tally["$ans"]}" -gt "$best" ]; then best=${tally["$ans"]}; got="$ans"; fi
  done
  # Show the spread when trials disagree — that disagreement IS the finding.
  if [ "$TRIALS" -gt 1 ] && [ "${#tally[@]}" -gt 1 ]; then
    for k in "${!tally[@]}"; do trial_detail="$trial_detail ${k}×${tally[$k]}"; done
    trial_detail=" [split:$trial_detail ]"
  fi

  # Flag an answer that is not on the roster at all — usually a near-miss on a skill
  # whose frontmatter name differs from its directory (doctor Check 12 lists those).
  offroster=""
  if [ "$got" != "none" ] && ! printf '%s\n' "$roster" | grep -qE "^- ${got//./\\.}( \(agent\))?:"; then
    offroster=" (not on roster)"
  fi

  if [ "$got" = "$expect" ]; then ok="✓"; pass=$((pass+1))
  else ok="✗"; fail=$((fail+1)); FAILURES+=("$i|$prompt|$expect|${got}${offroster}${trial_detail}|$note"); fi

  short=$(printf '%s' "$prompt" | cut -c1-58)
  [ "${#prompt}" -gt 58 ] && short="${short}..."
  printf '| %d | %s | `%s` | `%s`%s | %s |\n' "$i" "$short" "$expect" "$got" "$trial_detail" "$ok"
done < "$CASES"

echo
total=$((pass+fail))
[ "$total" -gt 0 ] && rate=$(( pass*100/total )) || rate=0
echo "**$pass/$total passed ($rate%)**"

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo
  echo "## Failures — read before changing any description"
  echo
  for f in "${FAILURES[@]}"; do
    IFS='|' read -r fi fp fe fg fn <<< "$f"
    echo "**$fi.** \`$fp\`"
    echo "- expected \`$fe\`, got \`$fg\`"
    [ -n "$fn" ] && echo "- case note: $fn"
    echo
  done
  echo "> A failure is a routing signal, not automatically a bug: confirm the case's"
  echo "> \`expect\` is still the right answer before rewording the skill it names."
fi

# Exit 0 = every case ran (pass or fail); the pass rate is real. Exit 2 = the run
# aborted mid-way and the numbers are partial. A routing miss alone never fails the
# run — this is a measurement, not a build gate, and applying any fix it suggests is
# a separate human-gated step (§agent-engineering).
exit 0
