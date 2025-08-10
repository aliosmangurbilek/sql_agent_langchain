#!/usr/bin/env python3
"""
Build embeddings for one or more database URIs using DBEmbedder.

Usage:
  python scripts/build_vectors.py postgresql://user:pass@host:5432/db1 postgresql://user:pass@host:5432/db2

Or from a file (one URI per line):
  python scripts/build_vectors.py --file uris.txt

Optional:
  --model intfloat/e5-large-v2
  --prefix schema_embeddings
  --force  (force rebuild)
"""
from __future__ import annotations

import argparse
import sys
import sqlalchemy as sa
from typing import List

from core.db.embedder import DBEmbedder


def _iter_uris(args: argparse.Namespace) -> List[str]:
    uris: List[str] = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            uris.extend([line.strip() for line in f if line.strip() and not line.strip().startswith("#")])
    uris.extend(args.uris or [])
    # de-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for u in uris:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Build PGVector embeddings for given DB URIs")
    p.add_argument("uris", nargs="*", help="SQLAlchemy connection URIs")
    p.add_argument("--file", help="File containing URIs (one per line)")
    p.add_argument("--model", default="intfloat/e5-large-v2", help="Embedding model")
    p.add_argument("--prefix", default="schema_embeddings", help="Collection name prefix")
    p.add_argument("--force", action="store_true", help="Force rebuild (drop+recreate)")
    args = p.parse_args()

    uris = _iter_uris(args)
    if not uris:
        print("No URIs provided.")
        return 1

    for uri in uris:
        print(f"\n==> Building embeddings for: {uri}")
        try:
            eng = sa.create_engine(uri)
            emb = DBEmbedder(
                eng,
                collection_prefix=args.prefix,
                embedding_model=args.model,
                force_rebuild=args.force,
            )
            if not args.force:
                # ensure_store will build lazily if empty
                emb.ensure_store()
            else:
                emb.rebuild()
            # quick sanity query
            hits = emb.similarity_search("sales by customer 2005", k=3)
            print("Top hits:", ", ".join(
                f"{(h.get('schema') + '.' if h.get('schema') else '')}{h.get('table')} ({h.get('score'):.3f})" for h in hits
            ))
        except Exception as e:  # noqa: BLE001
            print(f"Failed for {uri}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
