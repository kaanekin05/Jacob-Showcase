#!/usr/bin/env python3
"""overlap-audit.py — flag skill/agent descriptions that COMPETE for the same prompts.

The `description:` is the entire signal the model matches to fire a skill or route to an
agent (§agent-engineering). When two descriptions overlap heavily, one prompt can plausibly trigger both
— silent mis-routing. This tool measures that overlap (TF-IDF cosine over each artifact's
real description + any `Triggers:` phrases) and prints the competing pairs.

HONESTY BOUNDARY: this measures *description competition*, NOT which skill actually fires
(that needs a model in the loop — run trigger-cases.jsonl; see scripts/evals/README.md). A flagged
pair may be fine by design; an unflagged pair can still mis-route. Signal, not verdict.

Report-only. Exit 0 always. Usage: python3 scripts/evals/overlap-audit.py [threshold=0.35]
"""
import json
import math
import os
import re
import sys

ROOT = os.environ.get("JACOB_ROOT", "/Users/kaan/Workspace/Jacob")
SKILLS_DIR = os.path.join(ROOT, "skills")
AGENTS_DIR = os.path.join(ROOT, "agents")
LOCK = os.path.join(SKILLS_DIR, "skills.lock.json")

STOP = set("""a an the and or of to for in on with without into over under from by is are be as
that this it its your you their our we they what when where which who how does do use used using
new via not never always only both check make turn help want add""".split())

WORD = re.compile(r"[a-z][a-z0-9+#-]{2,}")


def read_frontmatter_description(path):
    """Extract the `description:` value from a markdown file's --- frontmatter.
    Handles single-line and YAML block scalars (`description: >` / `|`)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ""
    if not lines or lines[0].strip() != "---":
        return ""
    # frontmatter = lines[1 .. next '---')
    fm = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        fm.append(ln)
    desc, capturing = [], False
    for ln in fm:
        m = re.match(r"^description:\s*(.*)$", ln)
        if m:
            rest = m.group(1).strip()
            if rest in (">", "|", ">-", "|-", ""):
                capturing = True  # block scalar follows
            else:
                return rest.strip('"').strip("'")
            continue
        if capturing:
            if re.match(r"^\S+:\s", ln):  # next top-level key ends the block
                break
            if ln.strip():
                desc.append(ln.strip())
    return " ".join(desc)


def tokens(text):
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def collect():
    """Return list of (label, kind, token_list)."""
    docs = []
    # Skills: real description from skills/<name>/SKILL.md, fall back to lock text.
    lock_desc = {}
    try:
        with open(LOCK, encoding="utf-8") as fh:
            for name, meta in json.load(fh).get("skills", {}).items():
                lock_desc[name] = meta.get("description", "")
    except OSError:
        pass
    for name in sorted(lock_desc):
        skill_md = os.path.join(SKILLS_DIR, name, "SKILL.md")
        desc = read_frontmatter_description(skill_md) or lock_desc[name]
        toks = tokens(desc)
        if toks:
            docs.append((name, "skill", toks))
    # Agents: description from agents/<name>.md frontmatter.
    for fn in sorted(os.listdir(AGENTS_DIR)):
        if not fn.endswith(".md") or fn in ("AGENTS.md", "README.md"):
            continue
        toks = tokens(read_frontmatter_description(os.path.join(AGENTS_DIR, fn)))
        if toks:
            docs.append((fn[:-3], "agent", toks))
    return docs


def tfidf_vectors(docs):
    n = len(docs)
    df = {}
    for _, _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
    vecs = []
    for _, _, toks in docs:
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        vec = {t: (c / len(toks)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vecs.append({t: v / norm for t, v in vec.items()})
    return vecs


def cosine(a, b):
    small, big = (a, b) if len(a) < len(b) else (b, a)
    return sum(v * big.get(t, 0.0) for t, v in small.items())


def main():
    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.35
    docs = collect()
    vecs = tfidf_vectors(docs)
    pairs = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            s = cosine(vecs[i], vecs[j])
            if s >= threshold:
                pairs.append((s, docs[i], docs[j]))
    pairs.sort(reverse=True, key=lambda p: p[0])

    print(f"# Description-overlap audit — {len(docs)} artifacts, threshold {threshold}")
    print("# Measures description COMPETITION, not firing. Signal, not verdict (§agent-engineering).\n")
    if not pairs:
        print(f"No pairs at/above cosine {threshold}. (Lower the threshold to see more.)")
        return
    print(f"{'cos':>5}  pair")
    print("-" * 60)
    for s, (na, ka, _), (nb, kb, _) in pairs:
        print(f"{s:5.2f}  {na} ({ka})  ⇄  {nb} ({kb})")
    print(f"\n{len(pairs)} competing pair(s). Tighten the weaker description, or confirm the")
    print("overlap is intentional. Real firing behavior: run scripts/evals/run-trigger-eval.sh (§agent-engineering).")


if __name__ == "__main__":
    main()
