"""Async background worker to refresh schema embeddings on schema change."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List

import asyncpg
from langchain.embeddings import HuggingFaceEmbeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.db import get_metadata  # assumed to be provided elsewhere


embedding_model = HuggingFaceEmbeddings(
    model_name="intfloat/e5-large-v2",
    encode_kwargs={"normalize_embeddings": True},
)


async def refresh_embeddings(
    engine, schema: str, table: str, rows: List[Dict[str, Any]]
) -> None:
    """Delete old vectors and insert new ones for a table."""
    texts = [row["text"] for row in rows]
    loop = asyncio.get_running_loop()
    vectors = await loop.run_in_executor(None, embedding_model.embed_documents, texts)

    async with engine.begin() as conn:
        await conn.execute(
            text('DELETE FROM schema_embeddings WHERE schema=:s AND "table"=:t'),
            {"s": schema, "t": table},
        )
        insert_stmt = text(
            'INSERT INTO schema_embeddings(schema, "table", embedding) '
            'VALUES (:s, :t, :e)'
        )
        for vec in vectors:
            await conn.execute(insert_stmt, {"s": schema, "t": table, "e": vec})
        await conn.execute(text("ANALYZE schema_embeddings"))


async def remove_table(engine, schema: str, table: str) -> None:
    """Delete embeddings for a dropped table."""
    async with engine.begin() as conn:
        await conn.execute(
            text('DELETE FROM schema_embeddings WHERE schema=:s AND "table"=:t'),
            {"s": schema, "t": table},
        )
        await conn.execute(text("ANALYZE schema_embeddings"))


async def handle_notification(engine, payload: str) -> None:
    data = json.loads(payload)
    schema = data.get("schema")
    table = data.get("table")
    command = data.get("command")

    if command == "DROP TABLE":
        await remove_table(engine, schema, table)
        return

    rows = await get_metadata(schema, table)  # type: ignore[func-returns-value]
    if not rows:
        await remove_table(engine, schema, table)
        return
    await refresh_embeddings(engine, schema, table, rows)


async def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False, future=True)

    listen_dsn = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(listen_dsn)
    queue: asyncio.Queue[str] = asyncio.Queue()

    def listener(connection, pid, channel, payload):  # type: ignore[override]
        queue.put_nowait(payload)

    await conn.add_listener("schema_changed", listener)

    try:
        while True:
            payload = await queue.get()
            await handle_notification(engine, payload)
    finally:
        await conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
