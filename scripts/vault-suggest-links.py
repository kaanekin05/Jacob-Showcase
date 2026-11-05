#!/usr/bin/env python3
"""vault-suggest-links.py — report vault pages that look related but share no link.

Why this exists (gap 3, 2026-09-27):

  Obsidian builds its graph from [[wikilinks]] only, so a link exists exactly
  where an agent typed one. Two pages about the same problem stay strangers
  unless somebody noticed the connection. wiki-lint finds orphans, which is the
  one-sided version: a page with no inbound link at all. It cannot find the pair
  that should be linked and is not.

  This is the half Cognee and Graphiti do with a derived graph. Jacob does not
  need their machinery, because the vault is already embedded in Milvus by
  scripts/memsearch/reindex.sh. This reads those vectors back, so it costs no
  embedding pass, no API call and no new dependency.

Scoring: a page pair scores the MAX cosine similarity over their chunk pairs, and
the report names the two headings that matched. Max, not mean, because one
near-identical passage is the signal worth reading; a mean would drown it in a
long page's unrelated sections.

Boilerplate is dropped first. Max scoring is defeated by template text: the
references/skills/ pages all carry a verbatim "How to think (10-principle
mapping)" section, which put six false pairs in the first twelve rows. A chunk
that matches chunks in more than --boiler-pages other pages above
--boiler-score is template, not subject, so it is excluded before pairing.

references/ is excluded by default. Those 26 pages are vendored copies of
external skill docs, not Jacob's own reasoning, and a missing link between two
of them is not knowledge work. Tightening --boiler-pages instead was tried and
rejected: at 2 it killed the legitimate lint-report pair while the template row
survived, so repetition count is the wrong lever. --include-refs brings them back.

No threshold is hardcoded. Cosine values are only comparable within one
embedding model, so the report prints scores and ranks them, and you calibrate.

READ-ONLY. It writes no file and edits no page. Deterministic: same index, same
output, ordered by score then path.

Usage:
  scripts/vault-suggest-links.py                 # top 20 unlinked pairs
  scripts/vault-suggest-links.py --top 50
  scripts/vault-suggest-links.py --min-score 0.8
  scripts/vault-suggest-links.py --include-hubs  # keep log/hot/index pages in
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

JACOB_ROOT = Path(os.environ.get("JACOB_ROOT", "/Users/kaan/Workspace/Jacob"))
STATE = JACOB_ROOT / ".memsearch/.index-state.json"
WIKI = JACOB_ROOT / "vault/wiki"

# Aggregator pages relate to everything by design, so they would fill the report
# with true-but-useless rows. log.md and hot.md are chronological digests and
# index pages are tables of contents.
HUB_STEMS = {"log", "hot", "index", "_index"}

# Vendored copies of external skill documentation, not Jacob knowledge.
REF_DIRS = ("references/",)

# [[name]], [[name|alias]], [[name#heading]], [[folder/name]]
LINK_RE = re.compile(r"\[\[([^\]\|#]+)")


def wikilink_targets(text: str) -> set[str]:
    """Return the link targets in *text*, reduced to bare page stems."""
    return {m.split("/")[-1].strip() for m in LINK_RE.findall(text) if m.strip()}


def load_link_graph() -> dict[str, set[str]]:
    """Map each page stem to the stems it links to."""
    graph: dict[str, set[str]] = {}
    for page in WIKI.rglob("*.md"):
        try:
            graph[page.stem] = wikilink_targets(page.read_text(encoding="utf-8"))
        except OSError:
            graph[page.stem] = set()
    return graph


def load_vault_chunks(collection: str):
    """Return (sources, headings, matrix) for every indexed vault chunk."""
    from pymilvus import MilvusClient

    client = MilvusClient(uri=os.path.expanduser("~/.memsearch/milvus.db"))
    if not client.has_collection(collection):
        sys.exit(f"collection {collection} does not exist — run scripts/memsearch/reindex.sh")

    rows = []
    offset = 0
    while True:
        batch = client.query(
            collection_name=collection,
            filter='source like "%/vault/wiki/%"',
            output_fields=["source", "heading", "embedding"],
            limit=1000,
            offset=offset,
        )
        if not batch:
            break
        rows += batch
        offset += len(batch)

    if not rows:
        sys.exit("no vault chunks indexed — run scripts/memsearch/reindex.sh")

    import numpy as np

    # Sort first, so the matrix layout (and therefore tie order) is stable.
    rows.sort(key=lambda r: (r["source"], r.get("heading") or "", str(r["embedding"][:2])))
    sources = [Path(r["source"]).stem for r in rows]
    rels = [str(Path(r["source"]).relative_to(WIKI)) if str(WIKI) in r["source"]
            else r["source"] for r in rows]
    headings = [(r.get("heading") or "(preamble)") for r in rows]
    matrix = np.asarray([r["embedding"] for r in rows], dtype="float32")
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
    return sources, headings, matrix, rels


def main() -> int:
    ap = argparse.ArgumentParser(description="Suggest missing vault wikilinks.")
    ap.add_argument("--top", type=int, default=20, help="rows to print (default 20)")
    ap.add_argument("--min-score", type=float, default=0.0, help="drop pairs below this cosine")
    ap.add_argument("--include-hubs", action="store_true", help="keep log/hot/index pages")
    ap.add_argument("--include-refs", action="store_true",
                    help="keep vault/wiki/references/ (vendored skill doc copies)")
    ap.add_argument("--boiler-score", type=float, default=0.85,
                    help="similarity at which chunks count as repeated (default 0.85)")
    ap.add_argument("--boiler-pages", type=int, default=3,
                    help="a chunk repeated across more than this many other pages is template (default 3)")
    args = ap.parse_args()

    if not STATE.exists():
        sys.exit(f"no index state at {STATE}")
    collection = json.loads(STATE.read_text())["collection"]

    graph = load_link_graph()
    sources, headings, matrix, rels = load_vault_chunks(collection)
    in_refs = {sources[i] for i, r in enumerate(rels) if r.startswith(REF_DIRS)}

    import numpy as np

    sim = matrix @ matrix.T

    # Drop template chunks. A section repeated near-verbatim across many pages is
    # boilerplate, and max scoring would rank every pair that shares it.
    page_idx = np.array([hash(s) for s in sources])
    boiler = np.zeros(len(sources), dtype=bool)
    for i in range(len(sources)):
        hits = np.where(sim[i] >= args.boiler_score)[0]
        others = {sources[j] for j in hits if sources[j] != sources[i]}
        if len(others) > args.boiler_pages:
            boiler[i] = True
    n_boiler = int(boiler.sum())

    # Best chunk pair per page pair, keeping which headings matched.
    best: dict[tuple[str, str], tuple[float, str, str]] = {}
    for i in range(len(sources)):
        if boiler[i]:
            continue
        a = sources[i]
        for j in range(i + 1, len(sources)):
            if boiler[j]:
                continue
            b = sources[j]
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            score = float(sim[i, j])
            if key not in best or score > best[key][0]:
                best[key] = (score, headings[i], headings[j]) if a < b else (score, headings[j], headings[i])

    rows = []
    for (a, b), (score, ha, hb) in best.items():
        if not args.include_hubs and (a in HUB_STEMS or b in HUB_STEMS):
            continue
        if not args.include_refs and (a in in_refs or b in in_refs):
            continue
        if b in graph.get(a, ()) or a in graph.get(b, ()):
            continue  # already linked, either direction
        if score < args.min_score:
            continue
        rows.append((score, a, b, ha, hb))

    rows.sort(key=lambda r: (-r[0], r[1], r[2]))

    print(f"vault pages: {len(graph)}   indexed chunks: {len(sources)}   "
          f"template chunks dropped: {n_boiler}   unlinked pairs: {len(rows)}")
    if not args.include_hubs:
        print(f"hubs excluded: {', '.join(sorted(HUB_STEMS))} (--include-hubs to keep)")
    if not args.include_refs:
        print(f"references/ excluded: {len(in_refs)} vendored doc page(s) (--include-refs to keep)")
    print()
    if not rows:
        print("no unlinked pairs above the threshold")
        return 0

    print(f"top {min(args.top, len(rows))} by best matching passage:\n")
    for score, a, b, ha, hb in rows[: args.top]:
        print(f"  {score:.3f}  [[{a}]]  x  [[{b}]]")
        print(f"         {ha[:58]}  ~  {hb[:58]}")
    print("\nRead-only. Nothing was written. Add the links you agree with by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
