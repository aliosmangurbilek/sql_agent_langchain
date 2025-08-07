#!/usr/bin/env python3
"""
Async background worker to refresh schema embeddings on schema changes.

Features:
- Multi-tenant database connection cache
- FastAPI endpoint for database switching
- HuggingFace embeddings with e5-large-v2 model
- Graceful shutdown handling
- Comprehensive logging
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Dict, List, Tuple, Any

import asyncpg
import uvicorn
from fastapi import FastAPI
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
import queue
import threading
import time

from config import get_config

from ..db.introspector import get_metadata

# Global event queues for SSE clients
sse_event_queues: List[queue.Queue] = []
sse_queue_lock = threading.Lock()

def add_sse_client() -> queue.Queue:
    """Add a new SSE client queue."""
    client_queue = queue.Queue()
    with sse_queue_lock:
        sse_event_queues.append(client_queue)
    return client_queue

def remove_sse_client(client_queue: queue.Queue):
    """Remove an SSE client queue."""
    with sse_queue_lock:
        if client_queue in sse_event_queues:
            sse_event_queues.remove(client_queue)

def broadcast_to_sse_clients(event_data: dict):
    """Broadcast an event to all connected SSE clients."""
    event_json = json.dumps(event_data)
    with sse_queue_lock:
        dead_queues = []
        for client_queue in sse_event_queues:
            try:
                client_queue.put_nowait(event_json)
            except queue.Full:
                # Client queue is full, remove it
                dead_queues.append(client_queue)
        
        # Remove dead queues
        for dead_queue in dead_queues:
            sse_event_queues.remove(dead_queue)


async def get_metadata_async(engine: AsyncEngine) -> List[Dict[str, Any]]:
    """Async version of get_metadata function using direct SQL."""
    
    sql = text("""
        WITH fk AS (
            SELECT
                con.conrelid                     AS relid,
                ck.attnum                        AS attnum,
                string_agg(
                    quote_ident(ns2.nspname) || '.' ||
                    quote_ident(cl2.relname) || '.' ||
                    quote_ident(att2.attname),
                    ','
                ) AS refs
            FROM pg_constraint con
            JOIN pg_class cl1 ON con.conrelid = cl1.oid
            JOIN pg_namespace ns1 ON cl1.relnamespace = ns1.oid
            JOIN pg_attribute ck ON con.conrelid = ck.attrelid AND ck.attnum = ANY(con.conkey)
            JOIN pg_class cl2 ON con.confrelid = cl2.oid
            JOIN pg_namespace ns2 ON cl2.relnamespace = ns2.oid
            JOIN pg_attribute att2 ON con.confrelid = att2.attrelid AND att2.attnum = ANY(con.confkey)
            WHERE con.contype = 'f'
            GROUP BY con.conrelid, ck.attnum
        )
        SELECT
            n.nspname                                                AS schema,
            c.relname                                                AS "table",
            a.attname                                                AS "column",
            CASE
                WHEN t.typname = 'bpchar' THEN 'character(' || a.atttypmod - 4 || ')'
                WHEN t.typname = 'varchar' THEN 'character varying(' || a.atttypmod - 4 || ')'
                WHEN a.atttypmod > 0 AND t.typname IN ('numeric', 'decimal')
                THEN t.typname || '(' || ((a.atttypmod - 4) >> 16) || ',' || ((a.atttypmod - 4) & 65535) || ')'
                ELSE t.typname
            END                                                      AS data_type,
            NOT a.attnotnull                                         AS is_nullable,
            COALESCE(ix.is_primary, false)                          AS is_primary_key,
            COALESCE(string_to_array(fk.refs, ','), ARRAY[]::text[]) AS fk_refs,
            COALESCE(s.n_tup_ins + s.n_tup_upd, 0)::bigint          AS row_estimate,
            ROUND((pg_total_relation_size(c.oid) / 1024.0 / 1024.0)::numeric, 2) AS table_size_mb,
            obj_description(c.oid, 'pg_class')                      AS table_comment,
            col_description(c.oid, a.attnum)                        AS column_comment
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        JOIN pg_attribute a ON c.oid = a.attrelid
        JOIN pg_type t ON a.atttypid = t.oid
        LEFT JOIN fk ON c.oid = fk.relid AND a.attnum = fk.attnum
        LEFT JOIN pg_stat_user_tables s ON c.oid = s.relid
        LEFT JOIN (
            SELECT DISTINCT
                i.indrelid AS relid,
                attr.attnum AS attnum,
                true AS is_primary
            FROM pg_index i
            JOIN pg_attribute attr ON i.indrelid = attr.attrelid AND attr.attnum = ANY(i.indkey)
            WHERE i.indisprimary
        ) ix ON c.oid = ix.relid AND a.attnum = ix.attnum
        WHERE c.relkind = 'r'
          AND n.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
          AND n.nspname NOT LIKE 'pg_temp_%'
          AND n.nspname NOT LIKE 'pg_toast_temp_%'
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY n.nspname, c.relname, a.attnum
    """)
    
    async with engine.connect() as conn:
        result = await conn.execute(sql)
        rows = result.fetchall()
        
        metadata = []
        for row in rows:
            row_dict = dict(row._mapping)  # Convert Row to dict
            metadata.append(row_dict)
        
        return metadata

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Global state
ACTIVE_DB = "default"
connection_cache: Dict[str, Tuple[AsyncEngine, asyncpg.Connection]] = {}
shutdown_event = asyncio.Event()
database_listeners: Dict[str, asyncpg.Connection] = {}  # Track active listeners

# Initialize embedding model
embedding_model = HuggingFaceEmbeddings(
    model_name="intfloat/e5-large-v2",
    encode_kwargs={"normalize_embeddings": True},
)

# FastAPI app for /set_db endpoint
app = FastAPI(title="Schema Worker API", version="1.0.0")


class DatabaseRequest(BaseModel):
    database: str


@app.post("/set_db")
async def set_active_database(request: DatabaseRequest):
    """Set the active database for on-demand operations."""
    global ACTIVE_DB
    old_db = ACTIVE_DB
    ACTIVE_DB = request.database
    logger.info(f"🔄 Active database switched from '{old_db}' to '{ACTIVE_DB}'")
    return {"status": "success", "active_db": ACTIVE_DB, "previous_db": old_db}


@app.get("/status")
async def get_status():
    """Get worker status and active database."""
    return {
        "status": "running",
        "active_db": ACTIVE_DB,
        "cached_connections": list(connection_cache.keys()),
    }


class AddDatabaseRequest(BaseModel):
    database: str
    base_url: str = None  # Optional: custom base URL


class RefreshRequest(BaseModel):
    database: str = None
    schema: str = None
    table: str = None


@app.post("/add_database_listener")
async def add_database_listener(request: AddDatabaseRequest):
    """Add a new database to the listener pool."""
    try:
        db_name = request.database
        
        if db_name in database_listeners:
            return {"status": "info", "message": f"Database '{db_name}' is already being monitored"}
        
        # Use custom base URL or default
        config = get_config()
        base_url = request.base_url or config.BASE_DATABASE_URL
        
        if not base_url:
            return {"status": "error", "message": "No base database URL provided"}
        
        # Build database URL
        if base_url.endswith("/"):
            db_url = f"{base_url}{db_name}"
        else:
            # Replace database name in existing URL
            if "/" in base_url:
                db_url = "/".join(base_url.split("/")[:-1] + [db_name])
            else:
                db_url = f"{base_url}/{db_name}"
        
        # Create connection for listening
        listen_dsn = db_url.replace("+asyncpg", "")
        listener_conn = await asyncpg.connect(listen_dsn)
        
        # Queue for notifications
        queue: asyncio.Queue[str] = asyncio.Queue()
        
        def notification_handler(connection, pid, channel, payload):
            """Handle incoming notifications."""
            try:
                queue.put_nowait(payload)
            except Exception as e:
                logger.error(f"Error queuing notification from {db_name}: {e}")
        
        # Add listener for schema changes
        await listener_conn.add_listener("schema_changed", notification_handler)
        
        # Store the connection
        database_listeners[db_name] = listener_conn
        
        # Start processing notifications for this database
        asyncio.create_task(process_database_notifications(db_name, queue))
        
        logger.info(f"👂 Started listening for schema changes on database: {db_name}")
        
        return {
            "status": "success", 
            "message": f"Started monitoring database: {db_name}",
            "database": db_name,
            "active_listeners": list(database_listeners.keys())
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to add database listener for {request.database}: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def process_database_notifications(db_name: str, queue: asyncio.Queue[str]):
    """Process notifications for a specific database."""
    logger.info(f"🔄 Started notification processor for database: {db_name}")
    
    while not shutdown_event.is_set():
        try:
            # Wait for notification with timeout
            payload = await asyncio.wait_for(queue.get(), timeout=1.0)
            await handle_notification(payload)
        except asyncio.TimeoutError:
            continue  # Check shutdown event
        except Exception as e:
            logger.error(f"Error processing notification from {db_name}: {e}", exc_info=True)
    
    logger.info(f"🔌 Notification processor stopped for database: {db_name}")


@app.post("/refresh_embeddings")
async def manual_refresh_embeddings(request: RefreshRequest):
    """Manually refresh embeddings for specified database/schema/table."""
    try:
        db_name = request.database or ACTIVE_DB
        
        if not db_name:
            return {"status": "error", "message": "No database specified"}
        
        # Get database handles
        engine, _ = await get_handles(db_name)
        
        # Get metadata for filtering using async wrapper
        all_metadata = await get_metadata_async(engine)
        
        # Filter based on request
        if request.schema and request.table:
            # Specific table
            rows = [r for r in all_metadata if r["schema"] == request.schema and r["table"] == request.table]
            target = f"{request.schema}.{request.table}"
        elif request.schema:
            # All tables in schema
            rows = [r for r in all_metadata if r["schema"] == request.schema]
            target = f"schema '{request.schema}'"
        else:
            # All tables in database
            rows = all_metadata
            target = f"database '{db_name}'"
        
        if not rows:
            return {"status": "error", "message": f"No tables found for {target}"}
        
        # Group by schema.table
        tables_processed = set()
        total_vectors = 0
        
        for row in rows:
            table_key = f"{row['schema']}.{row['table']}"
            if table_key in tables_processed:
                continue
                
            tables_processed.add(table_key)
            
            # Get all columns for this table
            table_rows = [r for r in rows if r["schema"] == row["schema"] and r["table"] == row["table"]]
            
            # Generate embeddings
            texts = [f"passage: {r['schema']}.{r['table']}({r['column']} {r['data_type']})" for r in table_rows]
            vectors = embedding_model.embed_documents(texts)
            
            # Refresh embeddings
            await refresh_embeddings(engine, row["schema"], row["table"], vectors)
            total_vectors += len(vectors)
        
        logger.info(f"✅ Manual refresh completed for {target}: {len(tables_processed)} tables, {total_vectors} vectors")
        
        return {
            "status": "success",
            "message": f"Refreshed embeddings for {target}",
            "tables_processed": len(tables_processed),
            "total_vectors": total_vectors,
            "target": target
        }
        
    except Exception as e:
        logger.error(f"❌ Manual refresh error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def get_handles(db_name: str) -> Tuple[AsyncEngine, asyncpg.Connection]:
    """
    Get or create database handles for the specified database.
    Returns (engine, conn) tuple, creating and caching if not exists.
    """
    if db_name in connection_cache:
        return connection_cache[db_name]

    # Build database URL
    config = get_config()
    base_url = config.BASE_DATABASE_URL
    if not base_url:
        raise ValueError("BASE_DATABASE_URL configuration not set")

    # Construct full database URL
    if base_url.endswith("/"):
        db_url = f"{base_url}{db_name}"
    else:
        # Replace database name in existing URL
        if "/" in base_url:
            db_url = "/".join(base_url.split("/")[:-1] + [db_name])
        else:
            db_url = f"{base_url}/{db_name}"

    # Create async engine
    engine = create_async_engine(db_url, echo=False, future=True)

    # Create asyncpg connection for notifications
    listen_dsn = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(listen_dsn)

    # Cache the handles
    connection_cache[db_name] = (engine, conn)
    logger.info(f"🔗 Created connection cache for database: {db_name}")

    return engine, conn


async def refresh_embeddings(
    engine: AsyncEngine, schema: str, table: str, vectors: List[List[float]]
) -> None:
    """Refresh embeddings for a specific table."""
    async with engine.begin() as conn:
        # Delete existing embeddings for this table
        await conn.execute(
            text('DELETE FROM schema_embeddings WHERE schema=:s AND "table"=:t'),
            {"s": schema, "t": table},
        )

        # Insert new embeddings
        if vectors:
            ins = text(
                'INSERT INTO schema_embeddings(schema, "table", embedding) VALUES (:s, :t, :e)'
            )
            for vec in vectors:
                # Convert vector list to PostgreSQL vector format
                vec_str = '[' + ','.join(map(str, vec)) + ']'
                await conn.execute(ins, {"s": schema, "t": table, "e": vec_str})

        # Analyze table for better query performance
        await conn.execute(text("ANALYZE schema_embeddings"))


async def remove_table_embeddings(engine: AsyncEngine, schema: str, table: str) -> None:
    """Delete embeddings for a dropped table."""
    async with engine.begin() as conn:
        await conn.execute(
            text('DELETE FROM schema_embeddings WHERE schema=:s AND "table"=:t'),
            {"s": schema, "t": table},
        )
        await conn.execute(text("ANALYZE schema_embeddings"))


async def handle_notification(payload: str) -> None:
    """Handle schema change notification."""
    try:
        data = json.loads(payload)
        db_name = data["db"]
        schema = data["schema"]
        table = data["table"]
        command = data["command"]

        logger.info(f"🔄 Schema changed: {db_name}.{schema}.{table} ({command})")
        
        # Broadcast to SSE clients
        event_data = {
            "type": "schema_change",
            "timestamp": time.time(),
            "database": db_name,
            "schema": schema,
            "table": table,
            "command": command,
            "message": f"Schema changed: {db_name}.{schema}.{table} ({command})"
        }
        broadcast_to_sse_clients(event_data)

        # Get database handles
        engine, _ = await get_handles(db_name)

        # Get metadata for the affected table using async wrapper
        all_metadata = await get_metadata_async(engine)
        rows = [
            r
            for r in all_metadata
            if r["schema"] == schema and r["table"] == table
        ]

        if command == "DROP TABLE" or not rows:
            await remove_table_embeddings(engine, schema, table)
            logger.info(f"🗑️ Removed embeddings for {schema}.{table}")
            
            # Broadcast drop event to SSE clients
            drop_event = {
                "type": "table_drop",
                "timestamp": time.time(),
                "database": db_name,
                "schema": schema,
                "table": table,
                "message": f"Table dropped: {db_name}.{schema}.{table} - embeddings removed"
            }
            broadcast_to_sse_clients(drop_event)
        else:
            # Generate embeddings for table metadata
            texts = [
                f"passage: {r['schema']}.{r['table']}({r['column']} {r['data_type']})"
                for r in rows
            ]
            vectors = embedding_model.embed_documents(texts)
            await refresh_embeddings(engine, schema, table, vectors)
            logger.info(
                f"✅ Refreshed embeddings for {schema}.{table} ({len(vectors)} vectors)"
            )
            
            # Broadcast refresh event to SSE clients
            refresh_event = {
                "type": "embedding_refresh",
                "timestamp": time.time(),
                "database": db_name,
                "schema": schema,
                "table": table,
                "vectors_count": len(vectors),
                "message": f"Embeddings refreshed: {schema}.{table} ({len(vectors)} vectors)"
            }
            broadcast_to_sse_clients(refresh_event)

    except Exception as e:
        logger.error(f"❌ Error handling notification: {e}", exc_info=True)


async def schema_listener() -> None:
    """Main schema change listener loop."""
    try:
        # Use a dedicated connection for listening
        config = get_config()
        base_url = config.BASE_DATABASE_URL
        if not base_url:
            raise ValueError("BASE_DATABASE_URL configuration not set")

        # Connect to the main database for listening
        listen_dsn = base_url.replace("+asyncpg", "")
        listener_conn = await asyncpg.connect(listen_dsn)

        # Queue for notifications
        queue: asyncio.Queue[str] = asyncio.Queue()

        def notification_handler(connection, pid, channel, payload):
            """Handle incoming notifications."""
            # connection, pid, channel intentionally unused - required by asyncpg interface
            try:
                queue.put_nowait(payload)
            except Exception as e:
                logger.error(f"Error queuing notification: {e}")

        # Add listener for schema changes
        await listener_conn.add_listener("schema_changed", notification_handler)
        logger.info("👂 Listening for schema changes on 'schema_changed' channel")

        # Process notifications until shutdown
        while not shutdown_event.is_set():
            try:
                # Wait for notification with timeout to check shutdown event
                payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                await handle_notification(payload)
            except asyncio.TimeoutError:
                continue  # Check shutdown event
            except Exception as e:
                logger.error(f"Error processing notification: {e}", exc_info=True)

        # Cleanup
        await listener_conn.close()
        logger.info("🔌 Schema listener connection closed")

    except Exception as e:
        logger.error(f"Schema listener error: {e}", exc_info=True)
        raise


async def cleanup_connections() -> None:
    """Cleanup all cached database connections."""
    logger.info("🧹 Cleaning up database connections...")

    for db_name, (engine, conn) in connection_cache.items():
        try:
            await conn.close()
            await engine.dispose()
            logger.info(f"✅ Closed connections for database: {db_name}")
        except Exception as e:
            logger.error(f"Error closing connections for {db_name}: {e}")

    connection_cache.clear()


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    # frame intentionally unused - required by signal handler interface
    logger.info(f"🛑 Received signal {signum}, initiating shutdown...")
    shutdown_event.set()


async def run_fastapi_server():
    """Run FastAPI server for /set_db endpoint."""
    config = uvicorn.Config(
        app=app, host="0.0.0.0", port=9500, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)

    # Run server until shutdown
    try:
        await server.serve()
    except Exception as e:
        logger.error(f"FastAPI server error: {e}")


async def main(enable_signals=True) -> None:
    """Main worker entry point."""
    # Setup signal handlers only if we're in the main thread
    if enable_signals:
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except ValueError:
            # signal only works in main thread, ignore if we're in a thread
            logger.info("🔧 Running in thread mode, skipping signal handlers")

    logger.info("🚀 Starting schema change worker...")

    try:
        # Run both the schema listener and FastAPI server concurrently
        await asyncio.gather(
            schema_listener(), run_fastapi_server(), return_exceptions=True
        )
    except Exception as e:
        logger.error(f"Main worker error: {e}", exc_info=True)
    finally:
        # Cleanup connections
        await cleanup_connections()
        logger.info("👋 Schema worker shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main(enable_signals=True))
    except KeyboardInterrupt:
        logger.info("🛑 Worker interrupted by user")
        sys.exit(0)
