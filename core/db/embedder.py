"""core.db.embedder
~~~~~~~~~~~~~~~~~~
Veritabanı şemasını vektör uzayına gömer ve PGVector (PostgreSQL) ile arar.
"""

from __future__ import annotations
import json, logging
from pathlib import Path
from typing import List, Dict, Any
import hashlib
import re

import sqlalchemy as sa
from langchain_community.vectorstores import PGVector
from langchain_community.vectorstores.pgvector import DistanceStrategy
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
            self.conn_str = str(engine.url)

        # Auto-select device for embeddings (GPU if available)
        _device = "cpu"
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                _device = "cuda"
        except Exception:
            _device = "cpu"

        self._embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model,
            model_kwargs={"device": _device},
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

        # Build or attach store (handle version differences in param names)
        store: PGVector
        try:
            store = PGVector(
                connection_string=self.conn_str,
                collection_name=self.collection_name,
                embeddings=self._embeddings,             # new param name
                use_jsonb=True,
                distance_strategy=DistanceStrategy.COSINE,
            )
        except TypeError:
            store = PGVector(
                connection_string=self.conn_str,
                collection_name=self.collection_name,
                embedding_function=self._embeddings,     # older param name
                use_jsonb=True,
                distance_strategy=DistanceStrategy.COSINE,
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
            # Ensure ANN index exists even if collection was pre-existing
            self._ensure_ann_index()
            self._log_index_status()
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
                            DELETE FROM public.langchain_pg_embedding
                            WHERE collection_id IN (
                                SELECT uuid FROM public.langchain_pg_collection WHERE name = :name
                            );
                            DELETE FROM public.langchain_pg_collection WHERE name = :name;
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
        doc_meta = [{"schema": s, "table": t} for (s, t) in tables]

        # Clear existing collection (if any) then (re)create
        self._clear_collection()

        # Handle API differences for from_texts
        try:
            store = PGVector.from_texts(
                texts=doc_texts,
                embedding=self._embeddings,  # new name
                metadatas=doc_meta,
                connection_string=self.conn_str,
                collection_name=self.collection_name,
                use_jsonb=True,
                distance_strategy=DistanceStrategy.COSINE,
            )
        except TypeError:
            store = PGVector.from_texts(
                texts=doc_texts,
                embeddings=self._embeddings,  # alt; bazı sürümlerde bu isim
                metadatas=doc_meta,
                connection_string=self.conn_str,
                collection_name=self.collection_name,
                use_jsonb=True,
                distance_strategy=DistanceStrategy.COSINE,
            )
        # Build ANN index (HNSW preferred; fallback to IVFFlat) best-effort
        self._ensure_ann_index()
        logger.info("PGVector collection built: %s", self.collection_name)
        self._log_index_status()
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

    # ------------------------------------------------------------------ #
    # Minimal deterministic schema signature (simplified phase 1)         #
    # ------------------------------------------------------------------ #
    _META_TABLE_NAME = "app_schema_embed_meta"
    # Backward compat: some code references _SIG_META_TABLE
    _SIG_META_TABLE = _META_TABLE_NAME

    def _schema_components(self) -> list[tuple[str, str, str, str]]:  # (schema, table, column, type)
        """Deterministic component list used for signature & optional diff UI.

        Filters out internal langchain_pg_* ve meta tablo.
        """
        if not self.engine.url.get_backend_name().startswith("postgres"):
            return []
        out: list[tuple[str, str, str, str]] = []
        try:
            for r in get_metadata(self.engine):
                tbl = r["table"]
                if tbl == self._META_TABLE_NAME or tbl.startswith("langchain_pg_"):
                    continue
                out.append(((r.get("schema") or ""), tbl, r["column"], str(r["type"]).lower()))
        except Exception as e:  # noqa: BLE001
            logger.debug("_schema_components failed: %s", e)
        out.sort()
        return out

    def _schema_signature(self) -> str:
        """Stable SHA256 hash of schema components list."""
        comps = self._schema_components()
        if not comps:
            return ""
        payload = json.dumps(comps, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ #
    # Index management
    # ------------------------------------------------------------------ #

    def _ensure_ann_index(self) -> None:
        """Ensure an ANN index exists for this collection.

        Preference order: HNSW (pgvector >= 0.5), otherwise IVFFlat.
        Uses a partial index filtered by collection_id to avoid cross-collection scans.
        """
        try:
            if not self.engine.url.get_backend_name().startswith("postgres"):
                return

            # CREATE INDEX CONCURRENTLY requires autocommit
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                # Ensure vector column has fixed dimensions; required for ANN indexes
                try:
                    self._ensure_vector_dimensions(conn)
                except Exception as e:
                    logger.warning(f"Could not ensure vector dimensions: {e}")

                # Detect pgvector version (extversion like '0.6.0')
                extver = conn.execute(
                    sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                ).scalar()
                logger.info("pgvector extension version: %s", extver or "unknown")

                def _ver_tuple(v: str) -> tuple[int, int, int]:
                    parts = [int(p) for p in re.split(r"[^0-9]+", v or "0.0.0") if p]
                    return tuple((parts + [0, 0, 0])[:3])

                row = conn.execute(
                    sa.text("SELECT uuid FROM public.langchain_pg_collection WHERE name = :n"),
                    {"n": self.collection_name},
                ).fetchone()
                if not row:
                    return
                cid = str(row[0])

                # Generate short, deterministic index suffix (keep under 63 char identifier limit)
                suffix = hashlib.sha1(f"{self.collection_name}:{cid}".encode("utf-8")).hexdigest()[:12]
                idx_hnsw = f"idx_lcpg_hnsw_{suffix}"
                idx_ivf = f"idx_lcpg_ivf_{suffix}"

                # Choose opclass for cosine (we normalize embeddings); fallback to l2 if not available
                opclass = "vector_cosine_ops"

                # Try HNSW if version supports it
                if _ver_tuple(str(extver)) >= (0, 5, 0):
                    try:
                        ddl_hnsw = (
                            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_hnsw} "
                            f"ON public.langchain_pg_embedding "
                            f"USING hnsw (embedding {opclass}) "
                            f"WITH (m = 16, ef_construction = 200) "
                            f"WHERE collection_id = '{cid}'::uuid"
                        )
                        conn.execute(sa.text(ddl_hnsw))
                        logger.info("HNSW index ensured: %s (collection=%s, opclass=%s)", idx_hnsw, self.collection_name, opclass)
                        return
                    except Exception as e:
                        msg = str(e)
                        logger.warning("HNSW index creation failed with opclass=%s. DDL=\n%s\nError=%s", opclass, ddl_hnsw, msg)
                        # Fallback opclass if cosine ops not available
                        if "operator class" in msg and "does not exist" in msg:
                            try:
                                opclass_fallback = "vector_l2_ops"
                                ddl_hnsw_l2 = ddl_hnsw.replace(opclass, opclass_fallback)
                                conn.execute(sa.text(ddl_hnsw_l2))
                                logger.info("HNSW index ensured with l2 ops: %s (collection=%s)", idx_hnsw, self.collection_name)
                                return
                            except Exception as e2:
                                logger.warning("HNSW l2 fallback failed. DDL=\n%s\nError=%s", ddl_hnsw_l2, e2)
                        # Continue to IVFFlat fallback

                # IVFFlat fallback (requires pgvector >= 0.4)
                try:
                    ddl_ivf = (
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_ivf} "
                        f"ON public.langchain_pg_embedding "
                        f"USING ivfflat (embedding {opclass}) "
                        f"WITH (lists = 100) "
                        f"WHERE collection_id = '{cid}'::uuid"
                    )
                    conn.execute(sa.text(ddl_ivf))
                    logger.info("IVFFlat index ensured: %s (collection=%s, opclass=%s)", idx_ivf, self.collection_name, opclass)
                except Exception as e2:
                    msg2 = str(e2)
                    logger.warning("IVFFlat index creation failed with opclass=%s. DDL=\n%s\nError=%s", opclass, ddl_ivf, msg2)
                    if "operator class" in msg2 and "does not exist" in msg2:
                        try:
                            opclass_fallback = "vector_l2_ops"
                            ddl_ivf_l2 = ddl_ivf.replace(opclass, opclass_fallback)
                            conn.execute(sa.text(ddl_ivf_l2))
                            logger.info("IVFFlat index ensured with l2 ops: %s (collection=%s)", idx_ivf, self.collection_name)
                        except Exception as e3:
                            logger.warning("IVFFlat l2 fallback failed. DDL=\n%s\nError=%s", ddl_ivf_l2, e3)

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not ensure ANN index: {e}")

    def _log_index_status(self) -> None:
        """Log the active ANN index type for this collection (HNSW/IVFFlat/none)."""
        try:
            if not self.engine.url.get_backend_name().startswith("postgres"):
                return
            with self.engine.connect() as conn:
                row = conn.execute(
                    sa.text("SELECT uuid FROM public.langchain_pg_collection WHERE name = :n"),
                    {"n": self.collection_name},
                ).fetchone()
                if not row:
                    return
                cid = str(row[0])
                rows = conn.execute(
                    sa.text(
                        """
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'langchain_pg_embedding'
                        """
                    )
                ).fetchall()
                found = False
                for idxname, idxdef in rows:
                    low = (idxdef or "").lower()
                    if cid in (idxdef or "") and " using hnsw " in low:
                        logger.info("HNSW index active: %s (collection=%s)", idxname, self.collection_name)
                        found = True
                    elif cid in (idxdef or "") and " using ivfflat " in low:
                        logger.info("IVFFlat index active: %s (collection=%s)", idxname, self.collection_name)
                        found = True
                if not found:
                    logger.info("No ANN index found for collection: %s", self.collection_name)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not determine index status: {e}")

    def _ensure_vector_dimensions(self, conn) -> None:
        """Ensure the embedding column has a fixed dimension (e.g., vector(1024)).

        LangChain'ın default tablosu zaman zaman `vector` (boyutsuz) oluşturabiliyor.
        ANN index'ler için sabit boyut gerekiyor.
        """
        # Check current column type (vector or vector(n))
        row = conn.execute(
            sa.text(
                """
                SELECT format_type(a.atttypid, a.atttypmod) AS typ
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'langchain_pg_embedding'
                  AND n.nspname = 'public'
                  AND a.attname = 'embedding'
                """
            )
        ).fetchone()
        current = (row[0] if row else "") or ""
        if current.startswith("vector("):
            return  # already fixed-size

        # Infer dimension from embedding model (fallback to 1024 for e5-large-v2)
        dim = None
        try:
            vec = self._embeddings.embed_query("dimension probe")
            dim = int(len(vec)) if vec is not None else None
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not probe embedding dimension: {e}")
        if not dim or dim <= 0:
            dim = 1024

        logger.info("Altering embedding column to fixed dimension: vector(%s)", dim)
        conn.execute(
            sa.text(
                f"ALTER TABLE public.langchain_pg_embedding "
                f"ALTER COLUMN embedding TYPE vector({dim})"
            )
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m core.db.embedder <DB_URI>")
    uri = sys.argv[1]
    eng = sa.create_engine(uri)
    emb = DBEmbedder(eng, force_rebuild=True)
    emb.rebuild()
    print(json.dumps(emb.similarity_search("customer rentals 2005", k=3), indent=2))
