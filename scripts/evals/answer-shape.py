#!/usr/bin/env python3
"""Count jacob-plain's answer-shape contract against a real answer.

`rules/output-styles/jacob-plain.md` is the SOLE definer of the contract. This
script only counts; it never decides. If a rule changes, change it there first.

jacob-plain no longer states numeric ceilings for prose length, sentence length,
bold spans, or volunteered items (removed 2026-09-29: fixed output caps written
for an older model's verbosity starve reasoning on hard problems). Those four are
now REPORTED as plain counts with no pass/fail. LONG_SENTENCE_WORDS below is this
script's own observation threshold, not a rule — nothing in jacob-plain sets it.
The checks that still FLAG are the ones jacob-plain still states in words: line 1
restating the request, a question that is not the last block, and a compression
that dropped a number or a scope word.

What it cannot see: volunteered material is counted only when it sits under an
`Also noticed:` or `Suggestions` heading. Three unrequested points scattered as
loose paragraphs count as zero, because the form is countable and the intent is
not. A clean run on that metric is not proof the answer stayed on scope.

It reports and always exits 0. It is not a doctor check and not a gate: an answer
may be long for a reason jacob-plain names (a design decision, a plan the user
asked for, a real tradeoff, requested depth, or a deliverable), and no script can
tell which. FLAG means "look at this", not "this is wrong".

Written Jacob-native. The idea of scoring answer shape deterministically, with no
LLM judge, came from alexgreensh/attention-span (AGPL-3.0); none of its code is
used here, and its scoring is inverted for Jacob (it rewards heavy bold, which
jacob-plain treats as noise).

Usage:
  python3 scripts/evals/answer-shape.py answer.md
  python3 scripts/evals/answer-shape.py --stdin < answer.md
  python3 scripts/evals/answer-shape.py responses.jsonl --field response
  python3 scripts/evals/answer-shape.py new.md --against old.md   # what compression dropped
"""

import argparse
import json
import re
import sys
from pathlib import Path

# This script's own reporting threshold, NOT a jacob-plain rule. jacob-plain asks
# for sentences "short enough to parse on one pass" and sets no number.
LONG_SENTENCE_WORDS = 25

FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")
TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.M)
BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", re.S)
WORD = re.compile(r"[A-Za-z0-9§][\w'\-§]*")
ALSO = re.compile(r"^\s*(?:\*\*)?(?:Also noticed|Suggestions)\b", re.I | re.M)
# jacob-plain: "Never restate the request. Never announce what you are about to do."
ANNOUNCE = re.compile(
    r"^\s*(?:\*\*)?(i'?ll\b|i will\b|let me\b|let's\b|here'?s\b|here is\b|sure[,.!]|"
    r"certainly|of course|absolutely|got it|okay[,.!]|ok[,.!]|i'?m going to\b|"
    r"looking at\b|first[,.]|to (?:answer|address|start)\b|great question)", re.I)
# Numbers and scope words are the two things compression must never drop.
NUMERIC = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:ms|s|mb|kb|gb|%|x)?(?![\w])", re.I)
SCOPE = re.compile(r"\b(only|never|unless|except|always|must not|cannot|not|no|non-)\b", re.I)
# A hard-wrapped line continues its sentence unless the next line opens a list item,
# heading, or quote. Sentences end at . ! ? followed by whitespace, or at a line break.
WRAP = re.compile(r"\n(?!\s*(?:[-*+]|\d+\.|#+|>)\s)(?!\s*\n)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def prose(text):
    """Text with everything jacob-plain exempts removed: code blocks, tables,
    inline code (which is where file paths and commands live)."""
    t = FENCE.sub(" ", text)
    t = TABLE_LINE.sub(" ", t)
    return INLINE_CODE.sub(" ", t)


def blocks(text):
    return [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]


def first_line(text):
    return next((l.strip() for l in text.strip().splitlines() if l.strip()), "")


def volunteered_items(text):
    m = ALSO.search(text)
    if not m:
        return 0
    tail = text[m.end():]
    return sum(1 for l in tail.splitlines() if l.strip())


def blocking_placement(text):
    """jacob-plain: a blocking question is the last block, nothing after it.
    Returns None when the answer asks nothing (the rule does not apply)."""
    if "?" not in text:
        return None
    bs = blocks(text)
    last_q = max(i for i, b in enumerate(bs) if "?" in b)
    return last_q == len(bs) - 1


def long_sentences(p):
    """Sentences long enough to be worth re-reading. Splitting is heuristic, so
    "e.g." ends a sentence early. That can only undercount, never overcount."""
    units = SENTENCE_END.split(WRAP.sub(" ", p))
    return [s.strip() for s in units if len(WORD.findall(s)) > LONG_SENTENCE_WORDS]


def measure(text):
    p = prose(text)
    return {
        "prose_words": len(WORD.findall(BOLD.sub(r"\1", p))),
        "long_sentences": long_sentences(BOLD.sub(r"\1", p)),
        "bold_spans": len(BOLD.findall(p)),
        "volunteered": volunteered_items(text),
        "announces": bool(ANNOUNCE.match(first_line(text))),
        "question_last": blocking_placement(text),
    }


def dropped(old, new):
    """What a compression removed. jacob-plain: never drop the number that makes
    a claim actionable, and never widen a scoped rule into a blanket one."""
    o, n = prose(old), prose(new)
    nums = sorted(set(NUMERIC.findall(o)) - set(NUMERIC.findall(n)))
    scopes = len(SCOPE.findall(o)) - len(SCOPE.findall(n))
    return nums, max(0, scopes)


def report(label, text, against=None):
    m = measure(text)
    flags = []
    if m["announces"]:
        flags.append(f'line 1 announces or restates: "{first_line(text)[:60]}"')
    if m["question_last"] is False:
        flags.append("a question is not in the last block (blocking? then move it last)")

    print(f"\n{label}")
    print(f"  prose {m['prose_words']:>4}w | long {len(m['long_sentences']):>2} | "
          f"bold {m['bold_spans']:>2} | "
          f"volunteered {m['volunteered']} | question-last "
          f"{'n/a' if m['question_last'] is None else m['question_last']}")
    if m["long_sentences"]:
        print(f'  note  longest sentence starts: "{m["long_sentences"][0][:60]}"')
    if against is not None:
        nums, scopes = dropped(against, text)
        if nums:
            flags.append(f"numbers dropped in compression: {', '.join(nums)}")
        if scopes:
            flags.append(f"{scopes} scope word(s) dropped — check for a widened rule")
    for f in flags:
        print(f"  FLAG  {f}")
    if not flags:
        print("  ok    nothing jacob-plain states in words is violated")
    return len(flags)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", help="markdown answer, or .jsonl of answers")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--field", default="response", help="jsonl field holding the answer")
    ap.add_argument("--against", help="prior version, to report what compression dropped")
    a = ap.parse_args()

    prior = Path(a.against).read_text(encoding="utf-8") if a.against else None
    if a.stdin:
        report("<stdin>", sys.stdin.read(), prior)
    elif not a.path:
        ap.error("give a path or --stdin")
    elif a.path.endswith(".jsonl"):
        total = 0
        for i, line in enumerate(Path(a.path).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                row = json.loads(line)
                total += report(f"{a.path}:{i}", row.get(a.field, ""), prior)
        print(f"\n{total} flag(s) across the file.")
    else:
        report(a.path, Path(a.path).read_text(encoding="utf-8"), prior)
    return 0


if __name__ == "__main__":
    sys.exit(main())
