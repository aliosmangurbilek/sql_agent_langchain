# Technology Stack

## Backend Framework
- **Flask**: Lightweight WSGI web application framework
- **Gunicorn**: WSGI HTTP Server for production deployment
- **Pydantic**: Data validation and settings management using Python type annotations

## AI/ML Stack
- **LangChain**: Framework for developing applications with language models
- **OpenRouter**: LLM provider (primary model: deepseek/deepseek-chat)
- **Sentence Transformers**: For embedding generation (E5 embeddings)
- **PGVector**: PostgreSQL extension for vector similarity search

## Database & Storage
- **PostgreSQL**: Primary database with pgvector extension for embeddings
- **SQLite**: Fallback option (no embedding support)
- **SQLAlchemy**: Python SQL toolkit and ORM

## Frontend
- **Vanilla JavaScript**: No framework dependencies, modular ES6 modules
- **Vega-Lite**: Grammar of interactive graphics for chart generation
- **CSS**: Custom styling without external frameworks

## Configuration & Environment
- **python-dotenv**: Environment variable management
- **Pydantic Settings**: Type-safe configuration from environment variables

## Common Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your OPENROUTER_API_KEY and DEFAULT_DB_URI

# For PostgreSQL, enable pgvector extension
psql -d your_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Running the Application
```bash
# Development server
python app.py

# Production server
gunicorn -w 4 -b 0.0.0.0:5000 app:create_app()
```

### Testing
```bash
# Run tests
pytest

# Run with Flask test client
pytest-flask
```

### Database Operations
```bash
# Build/rebuild embeddings (via API)
curl -X POST http://localhost:5000/api/admin/embeddings/rebuild

# Check schema status
curl http://localhost:5000/api/admin/embeddings/status?db_uri=your_db_uri
```