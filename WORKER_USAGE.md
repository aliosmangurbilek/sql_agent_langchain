# Schema Worker Usage Guide

## Overview

The schema worker provides live database schema monitoring and embedding updates through PostgreSQL's NOTIFY/LISTEN mechanism.

## Components

### 1. SQL Schema (`sql/pgvector_schema.sql`)
- Creates pgvector extension if not exists
- Creates `schema_embeddings` table with VECTOR(1024) column
- Creates HNSW index for efficient similarity search
- Sets up PL/pgSQL trigger for DDL notifications

### 2. Background Worker (`core/worker/listen_and_refresh.py`)
- Multi-tenant database connection cache
- Listens for schema changes on all databases
- Automatically updates embeddings using HuggingFace e5-large-v2 model
- FastAPI endpoint for database switching
- Graceful shutdown handling

### 3. Helper Function (`core/db/embedder.py`)
- `upsert_rows()` function for embedding operations

## Environment Variables

```bash
# Required
BASE_DATABASE_URL=postgresql+asyncpg://user:password@localhost/

# Optional
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
```

## Running the Worker

```bash
# Install dependencies
pip install -r requirements.txt

# Run the background worker
python -m core.worker.listen_and_refresh

# The worker will:
# - Start listening on 'schema_changed' channel
# - Start FastAPI server on port 9500
# - Log all schema changes and embedding updates
```

## API Endpoints

The worker exposes a FastAPI server on port 9500:

### Switch Active Database
```bash
curl -X POST http://localhost:9500/set_db \
  -H "Content-Type: application/json" \
  -d '{"database": "my_database"}'
```

### Check Status
```bash
curl http://localhost:9500/status
```

## Database Setup

1. Run the schema setup:
```sql
\i sql/pgvector_schema.sql
```

2. The trigger will automatically notify on:
   - CREATE TABLE
   - ALTER TABLE  
   - DROP TABLE

## Monitoring

The worker logs all activities:
- 🔄 Schema changes detected
- ✅ Embeddings refreshed
- 🗑️ Embeddings removed for dropped tables
- 🔗 New database connections cached

## Shutdown

The worker handles graceful shutdown via SIGINT/SIGTERM:
- Closes all database connections
- Stops the FastAPI server
- Cleans up resources
