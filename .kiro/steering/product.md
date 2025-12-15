# Product Overview

SQL Agent LangChain is a lightweight Flask + LangChain application that converts natural language questions into verified SQL queries, executes them safely, and optionally generates Vega-Lite charts.

## Core Features
- Natural language to SQL conversion using OpenRouter models (default: deepseek/deepseek-chat)
- Embedding-based table selection using PGVector + E5 embeddings
- Schema drift detection with deterministic signatures
- SQL safety guardrails (read-only, LIMIT injection, mutation blocking)
- Automatic chart generation with Vega-Lite specs
- Real-time schema monitoring with frontend polling
- Modular vanilla JS frontend (no framework dependencies)

## Key Value Props
- Schema-aware query generation reduces hallucination
- Embedding-guided table restriction improves accuracy
- Safety-first approach with SQL verification
- Interactive data visualization capabilities
- Real-time schema change detection and management