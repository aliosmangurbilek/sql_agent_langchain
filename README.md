# SQL Agent LangChain (Schema-Aware, Embedding-Guided)

A lightweight Flask + LangChain application that turns natural language questions into verified SQL, executes them safely, and (optionally) generates Vega-Lite charts. It maintains an embedding index of the live database schema (tables & columns) to select relevant tables for each question and detects schema drift via a deterministic signature.

## Features
- Natural language → SQL via OpenRouter models (default: `deepseek/deepseek-chat`)
- Embedding-based relevant table restriction (PGVector + E5 embeddings)
- Deterministic schema signature & change flag (no silent auto-rebuild in `mark` mode)
- Manual schema check & rebuild endpoints, frontend banner + 10s polling
- SQL guardrail (`verify_sql`) adds LIMIT, blocks mutations (extensible)
- Chart auto-spec generation (Vega-Lite) with heuristics (aggregation, top-N, mark selection)
- Copy answer / copy SQL / download CSV / row+column meta UI helpers
- Modular vanilla JS frontend (no framework bundler required)

## Architecture Overview
```
Flask (app.py)
├── api/
│   ├── routes_query.py       # /api/query NL → SQL agent
│   ├── routes_chart.py       # /api/chart chart spec generation
│   ├── routes_admin.py       # schema + embeddings lifecycle (status/check/rebuild)
│   ├── routes_models.py      # model list proxy (OpenRouter)
│   └── routes_health.py      # /api/healthz
├── core/db/embedder.py       # schema embedding (PGVector) + signature
├── core/db/query_engine.py   # LangChain SQL agent + table selection
├── core/db/verify_sql.py     # guardrails (LIMIT, safety)
├── core/charts/spec_generator.py # Vega-Lite heuristic spec builder
└── static + templates        # frontend (index.html, modular JS)
```

## Prerequisites
- Python 3.11+ recommended
- PostgreSQL with `pgvector` extension if you want embeddings/table selection (SQLite fallback works but no embeddings)
- OpenRouter API key (https://openrouter.ai/)

## Docker Compose
1. Create `.env` from the template:
```bash
cp .env.example .env
```
2. Edit `.env` and set at least:
```bash
OPENROUTER_API_KEY=your_openrouter_key_here
POSTGRES_PASSWORD=change-this
DEFAULT_SAMPLE_DB=pagila
```
3. Start the stack:
```bash
docker compose up --build -d
```
4. Open http://localhost:5000
5. Pick a database from the dropdown. Manual DB URI is now an advanced override only.

Notes:
- The Postgres container loads sample databases on first boot from `postgres-sample-dbs/`.
- Default sample set: `pagila,chinook,titanic,netflix,periodic_table,happiness_index`
- The dropdown keeps configured names first, then auto-discovers other accessible databases on the same PostgreSQL server.
- First embedding build downloads the Hugging Face model and may take a while.
- The compose file binds the web app to `127.0.0.1:${APP_PORT:-5000}` so it is ready for a reverse proxy on the host.

## Local Quick Start
1. Clone repository
2. Create & populate `.env` from template:
```bash
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
# Set DEFAULT_DB_URI if you want a server-side default DB
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. (PostgreSQL only) Ensure pgvector extension:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
5. Run the server:
```bash
python app.py
```
6. Open http://localhost:5000 in browser. Enter DB URI, or leave it blank if `DEFAULT_DB_URI` is configured on the server.

## Environment Variables
See `.env.example` for full list. Key variables:
- `OPENROUTER_API_KEY` (required) OpenRouter key
- `DEFAULT_DB_URI` base server-side database URI used by the dropdown and as fallback
- `DATABASE_OPTIONS` optional comma-separated database names exposed first in the UI dropdown; leave blank to rely on auto-discovery
- `SCHEMA_CHANGE_MODE` (off|mark|auto*) current: `mark` marks flag only
- `OPENROUTER_MODEL` default LLM model
- `EMBEDDING_MODEL`, `EMBEDDING_DEVICE` control local schema embedding runtime
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` Docker Postgres settings
- `SAMPLE_DATABASES` comma-separated sample DB list loaded on first Postgres boot
- `DEFAULT_SAMPLE_DB` database used by Docker as the default backend target
- `TRUST_PROXY_HEADERS=1` enables reverse-proxy header handling
- `FLASK_ENV`, `FLASK_DEBUG` dev convenience
- `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY` optional tracing

## Schema Signature & Polling
- A deterministic signature (SHA256 over `(schema, table, column, type)` tuples excluding internal tables) is stored in `app_schema_embed_meta`.
- Frontend polls `/api/admin/embeddings/status` every 10 seconds.
- On each query attempt, client POSTs `/api/admin/embeddings/check` first; if schema drift is detected `needs_rebuild` is set true.
- Rebuild: POST `/api/admin/embeddings/rebuild` recreates embedding collection & updates stored signature.

State meanings in status:
- `needs_rebuild=false` and signatures equal → everything current
- `needs_rebuild=true` and signatures differ → pending rebuild after change
- After rebuild signature updates & flag cleared

## Endpoints (Summary)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/query` | Run NL → SQL agent (returns answer, SQL, data) |
| POST | `/api/chart` | Generate chart spec from existing SQL + data |
| GET  | `/api/admin/embeddings/status?db_uri=...` | Current collection state & diff heads |
| POST | `/api/admin/embeddings/check` | Compare live signature vs stored, set flag |
| POST | `/api/admin/embeddings/rebuild` | Rebuild embeddings & persist new signature |
| GET  | `/api/models` | Available OpenRouter models (proxy) |
| GET  | `/api/healthz` | Health probe |

## Query Flow
1. Frontend pre-check: `/api/admin/embeddings/check`
2. POST `/api/query` { database?, db_uri?, question, model } (`database` is the normal UI path; `db_uri` is advanced override)
3. Server: embeddings similarity selects tables → restricted SQLDatabase (single schema) → LangChain agent → `verify_sql` guard → execution
4. Response includes: `answer`, `sql`, `data`
5. Chart (optional): POST `/api/chart` with same `sql` + `data` to refine/aggregate visualization

## Reverse Proxy
For a home server setup, keep Docker bound to loopback and publish it through your host web server.

An Nginx example is included at `deploy/nginx/sql-agent.conf.example`.

Typical flow:
1. `docker compose up --build -d`
2. Copy the Nginx example into your server config
3. Set `TRUST_PROXY_HEADERS=1` in `.env`
4. Reload Nginx and point DNS to your home server

## Chart Generation Heuristics
- Infers quantitative vs nominal fields
- Detects aggregation need (COUNT / SUM / AVG)
- Auto top-N limiting for long tails
- Chooses mark: bar/line/area/point based on data semantics & field counts

## Safety & Guardrails
- `verify_sql` enforces read-only and injects a LIMIT when absent
- Embedding-driven table restriction reduces cross-schema hallucination
- (Extend) Add blocklist, row count budget, or cost estimator as needed

## Development Tips
- Turn on more verbose logs: `export LOG_LEVEL=DEBUG` (add handling in logging setup if desired)
- To reset embeddings: delete rows in `langchain_pg_collection` & `langchain_pg_embedding` for the collection; or call rebuild endpoint
- To support multi-user: scope collection name by user / tenant prefix

## Future Enhancements (Ideas)
- Server-Sent Events or WebSocket for real-time query stage updates
- Cancel in-flight query / agent run
- Redis pub/sub for multi-process event fan-out
- Caching SQL result sets (TTL) to reduce repeat token cost

## Minimal Example (Interactive)
After starting server, try questions like:
- "Top 5 customers by total revenue"
- "Monthly order counts for the last year"
- "Distribution of products by category"

If schema changes (DDL) are applied, banner will indicate rebuild requirement after next poll or immediate pre-query check.

## Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| Banner always says needs rebuild | Rebuild not executed yet | Click Rebuild Embeddings |
| No SQL returned | Agent fallback triggers | Check logs; ensure model key valid |
| Slow first request | Model + embedding model warm-up | Subsequent calls faster |
| Docker starts but web is slow on first query | Embedding model is downloading/building | Wait for first warm-up; cache persists in `huggingface_cache` volume |
| Table restriction skipped | Hits in multiple schemas | Accept fallback; refine embeddings or constrain search |
| Newly added sample DB does not appear | Postgres init scripts only run on first volume creation | Recreate the `postgres_data` volume or restore the new DB manually |

## License
MIT (add a LICENSE file if distributing).

---
Happy querying!
