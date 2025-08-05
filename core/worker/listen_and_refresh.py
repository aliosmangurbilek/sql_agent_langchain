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
import os
import signal
import sys
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config import get_config

from ..db.introspector import get_metadata

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Global state
ACTIVE_DB = "default"
connection_cache: Dict[str, Tuple[AsyncEngine, asyncpg.Connection]] = {}
shutdown_event = asyncio.Event()

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
        "cached_connections": list(connection_cache.keys())
    }


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


async def refresh_embeddings(engine: AsyncEngine, schema: str, table: str, vectors: List[List[float]]) -> None:
    """Refresh embeddings for a specific table."""
    async with engine.begin() as conn:
        # Delete existing embeddings for this table
        await conn.execute(
            text('DELETE FROM schema_embeddings WHERE schema=:s AND "table"=:t'),
            {"s": schema, "t": table},
        )
        
        # Insert new embeddings
        if vectors:
            ins = text('INSERT INTO schema_embeddings(schema, "table", embedding) VALUES (:s, :t, :e)')
            for vec in vectors:
                await conn.execute(ins, {"s": schema, "t": table, "e": vec})
        
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
        
        # Get database handles
        engine, _ = await get_handles(db_name)
        
        # Get metadata for the affected table
        rows = [
            r for r in get_metadata(engine.sync_engine)
            if r["schema"] == schema and r["table"] == table
        ]
        
        if command == "DROP TABLE" or not rows:
            await remove_table_embeddings(engine, schema, table)
            logger.info(f"🗑️ Removed embeddings for {schema}.{table}")
        else:
            # Generate embeddings for table metadata
            texts = [
                f"passage: {r['schema']}.{r['table']}({r['column']} {r['data_type']})"
                for r in rows
            ]
            vectors = embedding_model.embed_documents(texts)
            await refresh_embeddings(engine, schema, table, vectors)
            logger.info(f"✅ Refreshed embeddings for {schema}.{table} ({len(vectors)} vectors)")
            
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
    logger.info(f"🛑 Received signal {signum}, initiating shutdown...")
    shutdown_event.set()


async def run_fastapi_server():
    """Run FastAPI server for /set_db endpoint."""
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=9500,
        log_level="info",
        access_log=False
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
            schema_listener(),
            run_fastapi_server(),
            return_exceptions=True
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
