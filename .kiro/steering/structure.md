# Project Structure

## Root Level Organization
```
├── app.py                 # Flask application factory and main entry point
├── config.py              # Pydantic-based configuration management
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variable template
└── README.md             # Project documentation
```

## API Layer (`/api/`)
Flask blueprints organized by functionality:
- `routes_query.py` - Core NL→SQL agent endpoint (`/api/query`)
- `routes_chart.py` - Chart spec generation (`/api/chart`) 
- `routes_admin.py` - Schema & embeddings lifecycle management
- `routes_models.py` - OpenRouter model list proxy (`/api/models`)
- `routes_health.py` - Health check endpoint (`/api/healthz`)

## Core Business Logic (`/core/`)
### Database Module (`/core/db/`)
- `query_engine.py` - LangChain SQL agent with table selection
- `embedder.py` - Schema embedding (PGVector) + signature management
- `verify_sql.py` - SQL safety guardrails (LIMIT, read-only enforcement)
- `introspector.py` - Database schema introspection utilities

### Charts Module (`/core/charts/`)
- `spec_generator.py` - Heuristic-based Vega-Lite spec generation
- `utils.py` - Chart utility functions

## Frontend (`/static/` & `/templates/`)
### Templates
- `index.html` - Single-page application shell

### Static Assets
- `css/app.css` - Custom styling (no external CSS frameworks)
- `js/app.js` - Main application logic and initialization
- `js/modules/` - Modular ES6 components:
  - `models.js` - Model selection and management
  - `schema_status.js` - Real-time schema monitoring

## Scripts & Utilities (`/scripts/`)
- `build_vectors.py` - Standalone embedding generation script

## Architecture Patterns

### API Design
- RESTful endpoints with JSON request/response
- Blueprint-based route organization
- Consistent error handling with HTTP status codes
- LRU caching for QueryEngine instances

### Configuration Management
- Environment-based configuration via Pydantic
- `.env` file support with sensible defaults
- Type-safe settings validation

### Frontend Architecture
- Vanilla JavaScript with ES6 modules (no build step required)
- Event-driven architecture with DOM manipulation
- Local storage for user preferences
- Real-time polling for schema status updates

### Database Patterns
- SQLAlchemy for database abstraction
- Connection pooling and caching
- Schema signature-based change detection
- Embedding-based table selection for query optimization

### Safety & Security
- SQL injection prevention via parameterized queries
- Read-only query enforcement
- Automatic LIMIT injection for unbounded queries
- Input validation and sanitization