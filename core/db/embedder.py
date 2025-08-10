""""core.db.embedder
~~~~~~~~~~~~~~~~~~
Veritabanı şemasını vektör uzayına gömer ve PGVector (PostgreSQL) ile arar.
"""

from __future__ import annotations
import json, logging
from pathlib import Path
from typing import List, Dict, Any

import sqlalchemy as sa
from langchain_community.vectorstores import PGVector
from langchain_huggingface import HuggingFaceEmbeddings

from .introspector import get_metadata

logger = logging.getLogger(__name__)


_E5_QUERY_PREFIX = "query: "
_E5_PASSAGE_PREFIX = "passage: "


class DBEmbedder:
    """Veritabanı şeması için embedding + PGVector arama katmanı."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        db_name: str | None = None,
        collection_prefix: str = "schema_embeddings",
        embedding_model: str = "intfloat/e5-large-v2",
        force_rebuild: bool = False
    ) -> None:
        self.engine = engine
        self.db_name = db_name or (engine.url.database or "default")
        self.collection_name = f"{collection_prefix}_{self.db_name}"
        # Keep a full (unmasked) connection string for PGVector APIs
        try:
            self.conn_str = engine.url.render_as_string(hide_password=False)  # SQLAlchemy URL → DSN
        except Exception:
            # Fallback to str() (may hide password, not preferred)
            self.conn_str = str(engine.url)
        self._embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model,
            encode_kwargs={"normalize_embeddings": True},
        )
        if force_rebuild:
            self.rebuild()

    # ------------------------------------------------------------------ #

    def ensure_store(self, force: bool = False) -> PGVector:
        logger.debug(f"ensure_store called for db: {self.db_name}, force={force}")
        # Best-effort: ensure pgvector extension exists (PostgreSQL only)
        try:
            if self.engine.url.get_backend_name().startswith("postgres"):
                with self.engine.connect() as conn:
                    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
                    conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not ensure pgvector extension: {e}")

        # Use connection_string for broad compatibility across langchain versions
        store = PGVector(
            connection_string=self.conn_str,
            collection_name=self.collection_name,
            embedding_function=self._embeddings,
            use_jsonb=True,
        )

        if force:
            logger.info("Force rebuild requested for PGVector store: %s", self.collection_name)
            return self._build_store()

        # Probe: if empty, build
        try:
            hits = store.similarity_search("__pgvector_healthcheck__", k=1)
            if not hits:
                logger.info("PGVector collection appears empty; building: %s", self.collection_name)
                return self._build_store()
            return store
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error probing PGVector store, rebuilding: {e}")
            return self._build_store()

    def _clear_collection(self) -> None:
        """Clear existing rows for this collection (best-effort)."""
        try:
            with self.engine.connect() as conn:
                conn.execute(sa.text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='langchain_pg_collection') THEN
                            DELETE FROM langchain_pg_embedding
                            WHERE collection_id IN (
                                SELECT uuid FROM langchain_pg_collection WHERE name = :name
                            );
                            DELETE FROM langchain_pg_collection WHERE name = :name;
                        END IF;
                    END $$;
                    """
                ), {"name": self.collection_name})
                conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not clear existing PGVector collection ({self.collection_name}): {e}")

    def _build_store(self) -> PGVector:
        """Veritabanı şeması için yeni bir PGVector koleksiyonu oluştur."""
        logger.info("Building PGVector collection for %s …", self.db_name)
        metadata = get_metadata(self.engine)
        # Group by (schema, table) to avoid collisions across schemas
        tables: Dict[tuple[str, str], List[str]] = {}
        for row in metadata:
            schema = (row.get("schema") or "")
            tname = row["table"]
            key = (schema, tname)
            tables.setdefault(key, []).append(f"{row['column']} ({row['type']})")

        def _qual_name(schema: str, table: str) -> str:
            return f"{schema}.{table}" if schema else table

        doc_texts = [f"Table {_qual_name(s, t)}: {', '.join(cols)}" for (s, t), cols in tables.items()]
        # Prefix with e5 passage directive for better alignment
        doc_texts = [f"{_E5_PASSAGE_PREFIX}{txt}" for txt in doc_texts]
        doc_meta  = [{"schema": s, "table": t} for (s, t) in tables]

        # Clear existing collection (if any) then (re)create
        self._clear_collection()
        store = PGVector.from_texts(
            texts=doc_texts,
            embedding=self._embeddings,
            metadatas=doc_meta,
            connection_string=self.conn_str,
            collection_name=self.collection_name,
            use_jsonb=True,
        )
        logger.info("PGVector collection built: %s", self.collection_name)
        return store

    def similarity_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        logger.debug(f"similarity_search called for db: {self.db_name}, query: {query}, k: {k}")
        try:
            store = self.ensure_store()
            q = f"{_E5_QUERY_PREFIX}{query}"
            # Try different API variants depending on langchain version
            if hasattr(store, "similarity_search_with_relevance_scores"):
                hits = store.similarity_search_with_relevance_scores(q, k=k)
                pairs = hits
            elif hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(q, k=k)
                pairs = hits
            else:
                docs = store.similarity_search(q, k=k)
                pairs = [(doc, 0.0) for doc in docs]
            return [
                {
                    "schema": (getattr(doc, "metadata", {}) or {}).get("schema", ""),
                    "table": (getattr(doc, "metadata", {}) or {}).get("table"),
                    "score": float(score) if not isinstance(score, tuple) else float(score[0]),
                    "text": getattr(doc, "page_content", ""),
                }
                for doc, score in pairs
            ]
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error during similarity search: {e}")
            # Rebuild and try once more
            store = self.ensure_store(force=True)
            docs = store.similarity_search(f"{_E5_QUERY_PREFIX}{query}", k=k)
            return [
                {
                    "schema": (getattr(doc, "metadata", {}) or {}).get("schema", ""),
                    "table": (getattr(doc, "metadata", {}) or {}).get("table"),
                    "score": 0.0,
                    "text": getattr(doc, "page_content", ""),
                }
                for doc in docs
            ]

    # ------------------------------------------------------------------ #

    def rebuild(self) -> None:
        """Koleksiyonu zorla yeniden oluştur."""
        logger.info(f"Rebuilding PGVector collection for {self.db_name}")
        self._build_store()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m core.db.embedder <DB_URI>")
    uri = sys.argv[1]
    eng = sa.create_engine(uri)
    emb = DBEmbedder(eng, force_rebuild=True)
    emb.rebuild()
    print(json.dumps(emb.similarity_search("customer rentals 2005", k=3), indent=2))
