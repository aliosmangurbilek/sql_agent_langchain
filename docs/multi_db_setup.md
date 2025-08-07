# Multi-Database Setup Guide

This project supports monitoring multiple PostgreSQL databases. Follow these steps for each database you want the worker to monitor.

## 1. Create or select the database
Ensure the database exists on your PostgreSQL server. Repeat the remaining steps for every database.

## 2. Install schema and triggers
Run the schema script in the target database to create the `schema_embeddings` table, indexes and event triggers:

```bash
psql -d <DATABASE_NAME> -f sql/pgvector_schema.sql
```

This script enables the `pgvector` extension and registers event triggers that publish `schema_changed` notifications on `CREATE TABLE`, `ALTER TABLE` and `DROP TABLE`.

## 3. Configure the worker
Set the `BASE_DATABASE_URL` environment variable to a connection string without a database name. Example:

```bash
export BASE_DATABASE_URL=postgresql+asyncpg://user:password@localhost/
```

Start the background worker:

```bash
python -m core.worker.listen_and_refresh
```

## 4. Switch active databases
Use the Flask API to tell the worker which database to process:

```bash
curl -X POST http://localhost:5000/api/worker/set_db \
  -H "Content-Type: application/json" \
  -d '{"database": "my_database"}'
```

Repeat the `psql` setup and API call for each additional database you wish to monitor.

With these steps the worker will listen for schema changes across multiple databases and forward real-time notifications to connected clients.
