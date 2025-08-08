# core/db/embedder.py
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List
import asyncio

import sqlalchemy as sa
import asyncpg
from pgvector.asyncpg import Vector, register_vector
from langchain_huggingface import HuggingFaceEmbeddings

from .introspector import get_metadata

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Yardımcılar
# ------------------------------------------------------------

def _safe_score(raw: float | int) -> float | None:
    """NaN / sonsuz skorları JSON-uyumlu hâle getir."""
    try:
        f = float(raw)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


# ------------------------------------------------------------
# Ana sınıf - pgvector kullanır
# ------------------------------------------------------------

class DBEmbedder:
    """
    Veritabanı şemasını HuggingFace embedding'ine gömer ve
    pgvector (PostgreSQL extension) ile benzerlik araması sunar.
    HNSW index ve cosine similarity kullanır.
    """

    def __init__(
        self,
        engine: sa.Engine,
        *,
        db_name: str | None = None,
        embedding_model: str = "intfloat/e5-large-v2",
        force_rebuild: bool = False,
    ) -> None:
        
        raw = db_name or (engine.url.database or "default")
        self.db_name = raw.replace("-", "_").replace(".", "_")  # Simple sanitization
        
        self._embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model, 
            encode_kwargs={"normalize_embeddings": True}
        )
        self.engine = engine

        if force_rebuild:
            self.rebuild()

    def _get_db_url_for_asyncpg(self) -> str:
        """Convert SQLAlchemy URL to asyncpg format."""
        url = self.engine.url
        # Convert postgresql+asyncpg:// to postgresql://
        return f"postgresql://{url.username}:{url.password}@{url.host}:{url.port}/{url.database}"

    async def _ensure_pgvector_table(self):
        """Ensure schema_embeddings table exists with pgvector extension."""
        db_url = self._get_db_url_for_asyncpg()
        conn = await asyncpg.connect(db_url)
        
        try:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Check if table exists at all
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'schema_embeddings'
                )
            """)
            
            if not table_exists:
                # Table doesn't exist, create with new schema
                logger.info("📋 Creating schema_embeddings table with multi-database support...")
                
                # Temporarily disable event triggers to avoid conflicts
                try:
                    await conn.execute("ALTER EVENT TRIGGER trg_schema_change DISABLE")
                except:
                    pass  # Trigger might not exist, that's fine
                
                await conn.execute("""
                    CREATE TABLE schema_embeddings (
                        id BIGSERIAL PRIMARY KEY,
                        db_name TEXT NOT NULL,
                        schema TEXT NOT NULL,
                        "table" TEXT NOT NULL,
                        embedding VECTOR(1024),
                        UNIQUE(db_name, schema, "table")
                    )
                """)
                
                # Re-enable event triggers
                try:
                    await conn.execute("ALTER EVENT TRIGGER trg_schema_change ENABLE")
                except:
                    pass  # Trigger might not exist, that's fine
                    
                logger.info("✅ Table created successfully")
            else:
                # Table exists, check if it has db_name column
                try:
                    db_name_exists = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'schema_embeddings' 
                            AND column_name = 'db_name'
                        )
                    """)
                    
                    if not db_name_exists:
                        logger.info("🔧 Migrating existing schema_embeddings table to support multiple databases...")
                        
                        # Temporarily disable event triggers to avoid conflicts
                        try:
                            await conn.execute("ALTER EVENT TRIGGER trg_schema_change DISABLE")
                        except:
                            pass  # Trigger might not exist, that's fine
                        
                        # Drop existing table and recreate to avoid conflicts
                        await conn.execute("DROP TABLE schema_embeddings")
                        
                        # Recreate with new schema
                        await conn.execute("""
                            CREATE TABLE schema_embeddings (
                                id BIGSERIAL PRIMARY KEY,
                                db_name TEXT NOT NULL,
                                schema TEXT NOT NULL,
                                "table" TEXT NOT NULL,
                                embedding VECTOR(1024),
                                UNIQUE(db_name, schema, "table")
                            )
                        """)
                        
                        # Re-enable event triggers
                        try:
                            await conn.execute("ALTER EVENT TRIGGER trg_schema_change ENABLE")
                        except:
                            pass  # Trigger might not exist, that's fine
                        
                        logger.info("✅ Migration completed - table recreated with new schema")
                    else:
                        logger.info("✅ Table already has multi-database support")
                        
                except Exception as migration_error:
                    logger.warning(f"Migration check failed, recreating table: {migration_error}")
                    # If anything goes wrong, just recreate the table
                    try:
                        await conn.execute("ALTER EVENT TRIGGER trg_schema_change DISABLE")
                    except:
                        pass  # Trigger might not exist, that's fine
                        
                    await conn.execute("DROP TABLE IF EXISTS schema_embeddings")
                    await conn.execute("""
                        CREATE TABLE schema_embeddings (
                            id BIGSERIAL PRIMARY KEY,
                            db_name TEXT NOT NULL,
                            schema TEXT NOT NULL,
                            "table" TEXT NOT NULL,
                            embedding VECTOR(1024),
                            UNIQUE(db_name, schema, "table")
                        )
                    """)
                    
                    try:
                        await conn.execute("ALTER EVENT TRIGGER trg_schema_change ENABLE")
                    except:
                        pass  # Trigger might not exist, that's fine
                        
                    logger.info("✅ Table recreated after migration error")
            
            # Create HNSW index
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_schema_embeddings_embedding
                    ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 32, ef_construction = 200)
            """)
            
            # Update/create the DDL trigger function to be more robust
            await conn.execute("""
                CREATE OR REPLACE FUNCTION ddl_notify_schema_change()
                RETURNS event_trigger
                LANGUAGE plpgsql
                AS $$
                DECLARE
                    cmd RECORD;
                    payload JSON;
                    obj_name TEXT;
                    sch_name TEXT;
                BEGIN
                    FOR cmd IN SELECT * FROM pg_event_trigger_ddl_commands()
                    LOOP
                        -- Skip schema_embeddings table to avoid circular triggers
                        IF cmd.command_tag IN ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE') THEN
                            BEGIN
                                -- Safely extract object name and schema name
                                obj_name := COALESCE(cmd.object_identity, cmd.objid::text, 'unknown');
                                sch_name := COALESCE(cmd.schema_name, 'public');
                                
                                -- Skip if this is the schema_embeddings table itself
                                IF obj_name LIKE '%schema_embeddings%' THEN
                                    CONTINUE;
                                END IF;
                                
                                payload := json_build_object(
                                    'db', current_database(),
                                    'schema', sch_name,
                                    'table', obj_name,
                                    'command', cmd.command_tag
                                );
                                PERFORM pg_notify('schema_changed', payload::text);
                                
                            EXCEPTION WHEN OTHERS THEN
                                -- If anything fails, just skip this notification
                                CONTINUE;
                            END;
                        END IF;
                    END LOOP;
                END;
                $$
            """)
            
        finally:
            await conn.close()

    def ensure_store(self, *, force: bool = False):
        """Ensure embeddings are stored in pgvector."""
        # Run async operations
        asyncio.run(self._ensure_store_async(force=force))

    async def _ensure_store_async(self, *, force: bool = False):
        """Async version of ensure_store."""
        await self._ensure_pgvector_table()
        
        db_url = self._get_db_url_for_asyncpg()
        conn = await asyncpg.connect(db_url)
        await register_vector(conn)

        try:
            # Check if we already have embeddings for this specific database
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM schema_embeddings WHERE db_name = $1",
                self.db_name
            )

            if count > 0 and not force:
                logger.info(f"✅ Found {count} existing embeddings for database: {self.db_name}")
                return

            # Rebuild embeddings
            await self._build_embeddings(conn, force=force)

        finally:
            await conn.close()

    async def _build_embeddings(self, conn: asyncpg.Connection, *, force: bool = False):
        """Build and store embeddings in pgvector."""
        logger.info(f"🔄 Building embeddings for database: {self.db_name}")
        
        if force:
            # Clear existing embeddings for this specific database
            await conn.execute(
                "DELETE FROM schema_embeddings WHERE db_name = $1",
                self.db_name
            )
        
        # Get metadata from introspector
        meta = get_metadata(self.engine)
        by_table: Dict[str, List[str]] = {}
        
        for row in meta:
            schema_name = row['schema']
            table_name = row['table']
            qualified_table = f"{schema_name}.{table_name}"
            by_table.setdefault(qualified_table, []).append(f"{row['column']} ({row['data_type']})")

        # Generate embeddings and store
        for qualified_table, columns in by_table.items():
            schema_name, table_name = qualified_table.split('.', 1)
            text = f"passage: Table {qualified_table}: {', '.join(columns)}"
            
            # Generate embedding
            embedding = self._embeddings.embed_query(text)

            # Store in pgvector using binary format
            await conn.execute(
                """
                INSERT INTO schema_embeddings (db_name, schema, "table", embedding)
                VALUES ($1, $2, $3, $4::vector)
                """,
                self.db_name,
                schema_name,
                table_name,
                Vector(embedding),
            )
        
        logger.info(f"✅ Stored {len(by_table)} table embeddings for database: {self.db_name}")

    def similarity_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        """Search for similar tables using pgvector cosine similarity."""
        return asyncio.run(self._similarity_search_async(query, k))

    async def _similarity_search_async(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        """Async version of similarity_search."""
        query_text = f"query: {query}"
        
        # Generate query embedding
        query_embedding = self._embeddings.embed_query(query_text)
        
        db_url = self._get_db_url_for_asyncpg()
        conn = await asyncpg.connect(db_url)
        await register_vector(conn)

        try:
            # Debug: Check what's in the database
            debug_count = await conn.fetchval(
                "SELECT COUNT(*) FROM schema_embeddings WHERE db_name = $1", 
                self.db_name
            )
            debug_tables = await conn.fetch(
                "SELECT DISTINCT schema, \"table\" FROM schema_embeddings WHERE db_name = $1", 
                self.db_name
            )
            logger.info(f"🔍 Debug - Total embeddings for {self.db_name}: {debug_count}")
            logger.info(f"🔍 Debug - Available tables for {self.db_name}: {[(r['schema'], r['table']) for r in debug_tables]}")
            
            # Search using cosine similarity (1 - cosine_distance)
            results = await conn.fetch(
                """
                SELECT
                    schema,
                    "table",
                    (1 - (embedding <=> $1::vector)) AS similarity_score
                FROM schema_embeddings
                WHERE db_name = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                Vector(query_embedding),
                self.db_name,
                k,
            )

            return [
                {
                    "table": f"{row['schema']}.{row['table']}",
                    "score": _safe_score(row['similarity_score']),
                    "text": f"Table {row['schema']}.{row['table']}"
                }
                for row in results
            ]

        finally:
            await conn.close()

    def rebuild(self) -> None:
        """Force rebuild all embeddings."""
        asyncio.run(self._ensure_store_async(force=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DBEmbedder {self.db_name} (pgvector)>"
