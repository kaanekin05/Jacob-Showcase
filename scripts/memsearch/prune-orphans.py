#!/usr/bin/env python3
"""prune-orphans.py — evict index chunks whose source file is gone.

Why this exists (measured 2026-09-27):

  The collection held 811 chunks across 61 files that no longer exist on disk.
  60 of them were left by the obsidian-vault -> vault rename. They were 23% of
  the whole index, and every vault search competed against them.

  They can never be evicted by indexing. core.py:130 prunes deleted files only
  "inside directory roots from this run", and reindex.sh passes one file at a
  time, which counts as a partial update with no root. So a renamed or deleted
  page leaks its chunks permanently.

Scope: only sources under JACOB_ROOT. Other projects share the Milvus file but
own their own collections, and a source outside Jacob is never this script's to
delete.

--check also reports the other direction, files on disk with no chunks, because
both are the same drift between the index and the files. It never indexes; that
is reindex.sh's job.

Usage:
  scripts/memsearch/prune-orphans.py            # delete orphans
  scripts/memsearch/prune-orphans.py --check    # report only, exit 1 on any drift
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

JACOB_ROOT = Path(os.environ.get("JACOB_ROOT", "/Users/kaan/Workspace/Jacob"))
STATE = JACOB_ROOT / ".memsearch/.index-state.json"

# The roots reindex.sh keeps in the collection. A file here with no chunks is drift.
MANAGED_ROOTS = (".memsearch/memory", "vault/wiki")


def resolve_collection() -> str:
    """Read the collection name the memsearch plugin itself wrote."""
    return json.loads(STATE.read_text())["collection"]


def indexed_sources(client, collection: str) -> dict[str, int]:
    """Return {source path: chunk count} for every chunk in the collection."""
    counts: dict[str, int] = {}
    offset = 0
    while True:
        rows = client.query(
            collection_name=collection,
            filter='source != ""',
            output_fields=["source"],
            limit=1000,
            offset=offset,
        )
        if not rows:
            break
        for row in rows:
            counts[row["source"]] = counts.get(row["source"], 0) + 1
        offset += len(rows)
    return counts


def find_orphans(counts: dict[str, int]) -> dict[str, int]:
    """Sources under JACOB_ROOT whose file no longer exists."""
    root = str(JACOB_ROOT) + "/"
    return {
        source: n
        for source, n in counts.items()
        if source.startswith(root) and not Path(source).exists()
    }


def find_unindexed(counts: dict[str, int]) -> list[str]:
    """Markdown files under the managed roots that have no chunks."""
    indexed = set(counts)
    missing: list[str] = []
    for rel in MANAGED_ROOTS:
        root = JACOB_ROOT / rel
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if str(path) not in indexed:
                missing.append(str(path))
    return missing


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    if not STATE.exists():
        print(f"prune-orphans: no index state at {STATE}", file=sys.stderr)
        return 0

    from pymilvus import MilvusClient

    collection = resolve_collection()
    uri = os.path.expanduser("~/.memsearch/milvus.db")
    client = MilvusClient(uri=uri)

    if not client.has_collection(collection):
        print(f"prune-orphans: collection {collection} does not exist")
        return 0
    # Newer milvus-lite opens collections in the 'released' state; query needs it loaded.
    client.load_collection(collection)

    counts = indexed_sources(client, collection)
    orphans = find_orphans(counts)
    unindexed = find_unindexed(counts) if check_only else []

    if not orphans and not unindexed:
        print(f"prune-orphans: clean ({len(counts)} files, 0 orphans)")
        return 0

    if check_only and unindexed:
        print(f"prune-orphans: {len(unindexed)} file(s) on disk with no chunks")
        for path in unindexed:
            print(f"  {path}")
        if not orphans:
            return 1

    if not orphans:
        return 0

    chunks = sum(orphans.values())
    verb = "would remove" if check_only else "removing"
    print(f"prune-orphans: {verb} {chunks} chunks from {len(orphans)} missing files")
    for source in sorted(orphans):
        print(f"  {source} ({orphans[source]} chunks)")

    if check_only:
        return 1

    for source in orphans:
        escaped = source.replace('"', '\\"')
        client.delete(collection_name=collection, filter=f'source == "{escaped}"')

    remaining = find_orphans(indexed_sources(client, collection))
    if remaining:
        print(f"prune-orphans: FAILED, {len(remaining)} orphans remain", file=sys.stderr)
        return 1
    print(f"prune-orphans: removed {chunks} chunks, 0 orphans remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
