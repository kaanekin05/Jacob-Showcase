#!/usr/bin/env python3
"""register-check.py — measure whether Jacob's answer-shape rules actually land.

§agent-engineering says "better requires an eval, not vibes". This is that eval for §behavior's
register and answer-shape rules (canonical home: rules/output-styles/jacob-plain.md).

It reads Claude Code's own transcripts under ~/.claude/projects/*/*.jsonl,
extracts assistant prose, and reports four countable signals:

  words/answer          length          trend only -- there is NO word ceiling
  2nd-clause sentences  register        target: trending down
  bold spans/answer     emphasis        <= 3, operationalizing a prose rule
  volunteered options   scope creep     target: trending down

WHY words/answer HAS NO TARGET. This script used to assert `median <= 150`,
quoting a ceiling jacob-plain.md carried until commit f932936 (2026-09-29)
deleted it. The style now says only "a report is as long as the work was, and
no longer" -- proportionality, with no number, because a hard cap plus a "cut
elaboration" instruction put warnings at risk (see the attention-span harvest).
A script cannot measure proportionality: it does not know how big the work was.
So the distribution is reported and nothing is scored against it. Do not
reintroduce a cap here; the number would be this script's invention, not a rule.

POPULATION CAVEAT, and it applies to every figure below. jacob-plain exempts
three whole categories from brevity -- requested depth ("walk me through it"),
a deliverable the user asked you to produce, and a re-answer after a failed
short one. This script cannot tell those apart from an ordinary task report, so
they sit in the denominator. A percentage here is therefore NOT a violation
rate. Compare two runs; do not read one run as a score.

Read-only. Never writes to a transcript, never leaves the machine.

NOT a duplicate of scripts/evals/response-quality/. That harness is prospective: synthetic
prompts, a blind human judge, real dollars, and a release gate answering "will this
change make responses better?". It also isolates itself from the user's config on
purpose (`--setting-sources ""`), so it structurally cannot see whether an output
style is active in real sessions. This script is retrospective: real transcripts,
zero cost, deterministic counting, no judging, answering "did the answers I actually
got change?". Use response-quality to decide whether to ship a rule. Use this one to
find out whether the shipped rule landed.

Usage:
  scripts/evals/register-check.py                 # last 30 days
  scripts/evals/register-check.py --days 14
  scripts/evals/register-check.py --since 2026-08-30
  scripts/evals/register-check.py --split 2026-08-31   # before/after a change
  scripts/evals/register-check.py --project Jacob      # substring filter on project dir

Caveat on the 2nd-clause number: it counts em-dashes, mid-sentence colons,
semicolons and parentheses in prose after stripping code. It is a proxy, not a
parse. Absolute value is rough; the trend between two runs is what matters.
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys

PROJECTS = os.path.expanduser("~/.claude/projects")

# Answers shorter than this are tool acknowledgements, not answers.
MIN_CHARS = 200

# No word target: jacob-plain.md has no ceiling (see the module docstring).
TARGET_BOLD = 3   # operationalizes "bold is what you would underline once on paper"


def load(since_ts, project_filter):
    """Return [(project, iso_timestamp, text)] for assistant prose since a cutoff."""
    out = []
    pattern = os.path.join(PROJECTS, "*", "*.jsonl")
    for path in glob.glob(pattern):
        if os.path.getmtime(path) < since_ts:
            continue
        project = os.path.basename(os.path.dirname(path))
        if project_filter and project_filter not in project:
            continue
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    if '"assistant"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("type") != "assistant":
                        continue
                    blocks = rec.get("message", {}).get("content", [])
                    if not isinstance(blocks, list):
                        continue
                    text = "".join(
                        b.get("text", "")
                        for b in blocks
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                    if len(text.strip()) < MIN_CHARS:
                        continue
                    out.append((project, rec.get("timestamp", ""), text))
        except OSError:
            continue
    return out


def prose(text):
    """Strip fenced code and inline code so counts reflect prose only."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "X", text)


def sentences(text):
    body = prose(text)
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", body) if len(s.split()) > 3]


SECOND_CLAUSE = re.compile(r"—|\s-\s|\w: \w|\(|;")
VOLUNTEERED = re.compile(
    r"\bTwo (ways|options)\b|\bOption A\b|if you want|Say the word|Want me to",
    re.I,
)


def measure(group):
    n = len(group)
    if not n:
        return None
    words, bold, dense, total_sent, volunteered, tables = [], [], 0, 0, 0, 0
    for _, _, text in group:
        words.append(len(prose(text).split()))
        bold.append(len(re.findall(r"\*\*[^*]+\*\*", text)))
        for s in sentences(text):
            total_sent += 1
            if SECOND_CLAUSE.search(s):
                dense += 1
        if VOLUNTEERED.search(text):
            volunteered += 1
        if len(re.findall(r"^\|", text, re.M)) > 3:
            tables += 1
    return {
        "n": n,
        "median_words": st.median(words),
        "mean_words": st.mean(words),
        "p90_words": sorted(words)[int(0.9 * (n - 1))],
        "mean_bold": st.mean(bold),
        "over_bold": 100 * sum(b > TARGET_BOLD for b in bold) / n,
        "dense_pct": 100 * dense / total_sent if total_sent else 0.0,
        "volunteered_pct": 100 * volunteered / n,
        "table_pct": 100 * tables / n,
    }


def report(label, m):
    if m is None:
        print(f"{label}: no answers in range")
        return
    print(f"\n{label}  (n={m['n']} answers)")
    print(f"  prose words     median {m['median_words']:>5.0f}   mean {m['mean_words']:>5.0f}   p90 {m['p90_words']:>5.0f}"
          f"   (no ceiling -- trend only)")
    print(f"  bold spans      mean {m['mean_bold']:>6.1f}                        over {TARGET_BOLD}: {m['over_bold']:.1f}%")
    print(f"  2nd-clause sentences  {m['dense_pct']:.1f}%   (proxy, compare trend not absolute)")
    print(f"  volunteers options    {m['volunteered_pct']:.1f}%")
    print(f"  uses a table          {m['table_pct']:.1f}%")
    print("  NOTE: percentages are not violation rates -- requested depth and")
    print("        deliverables are exempt by the style and cannot be filtered out.")


def delta(before, after):
    if before is None or after is None:
        return
    print("\nchange")
    rows = [
        ("median prose words", "median_words", "%.0f", True),
        ("mean bold spans", "mean_bold", "%.1f", True),
        ("2nd-clause %", "dense_pct", "%.1f", True),
        ("volunteers options %", "volunteered_pct", "%.1f", True),
    ]
    for name, key, fmt, lower_is_better in rows:
        b, a = before[key], after[key]
        diff = a - b
        good = (diff < 0) if lower_is_better else (diff > 0)
        arrow = "better" if diff and good else ("worse" if diff else "flat")
        print(f"  {name:<22} {fmt % b} -> {fmt % a}   {arrow}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30, help="lookback window (default 30)")
    ap.add_argument("--since", help="ISO date overriding --days, e.g. 2026-08-01")
    ap.add_argument("--split", help="ISO date; report before/after it separately")
    ap.add_argument("--project", help="substring filter on the project directory name")
    args = ap.parse_args()

    if args.since:
        start = dt.datetime.fromisoformat(args.since)
    else:
        start = dt.datetime.now() - dt.timedelta(days=args.days)

    msgs = load(start.timestamp(), args.project)
    if not msgs:
        print(f"No assistant answers found since {start.date()}. "
              f"Checked {PROJECTS}/*/*.jsonl", file=sys.stderr)
        return 1

    scope = f"since {start.date()}"
    if args.project:
        scope += f", project ~ {args.project}"
    print(f"register-check: {len(msgs)} answers over {MIN_CHARS} chars, {scope}")

    if args.split:
        before = [m for m in msgs if m[1] < args.split]
        after = [m for m in msgs if m[1] >= args.split]
        mb, ma = measure(before), measure(after)
        report(f"before {args.split}", mb)
        report(f"from {args.split}", ma)
        delta(mb, ma)
    else:
        report("all", measure(msgs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
