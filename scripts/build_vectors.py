#!/usr/bin/env python
"""
scripts/build_vectors.py
~~~~~~~~~~~~~~~~~~~~~~~~

Veritabanı şemasını embedleyip FAISS dizini oluşturur / yeniler.

Kullanım
--------
$ python -m flask_app.scripts.build_vectors \
      --db postgresql://user:pw@localhost:5432/pagila \
      [--force] [--model text-embedding-3-small]

Parametreler
------------
--db / -d     : Bağlantı URI'si (postgresql://, sqlite:/// vs.)
--force / -f  : Eski FAISS klasörünü silip yeniden oluşturur
--model / -m  : Embedding modeli (varsayılan: text-embedding-3-small)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import sqlalchemy as sa

from flask_app.core.db.embedder import DBEmbedder

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)7s | %(message)s",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or rebuild FAISS vector store")
    parser.add_argument(
        "-d",
        "--db",
        required=True,
        help="Database URI (e.g. postgresql://user:pw@localhost:5432/pagila)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Delete existing index and rebuild from scratch",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="text-embedding-3-small",
        help="Embedding model name (default: text-embedding-3-small)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    engine = sa.create_engine(args.db)
    db_name = engine.url.database or "default"

    logging.info("Connecting to %s …", engine.url)
    embedder = DBEmbedder(
        engine,
        db_name=db_name,
        embedding_model=args.model,
    )

    if args.force:
        logging.info("Rebuilding FAISS index for %s (force)…", db_name)
        embedder.rebuild()
    else:
        embedder.ensure_store(force=False)

    index_path = Path(embedder.store_path).resolve()
    logging.info("Vector store ready at %s", index_path)


if __name__ == "__main__":
    main()
