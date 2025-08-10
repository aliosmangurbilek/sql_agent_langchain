"""
api.routes_query
~~~~~~~~~~~~~~~~~
Endpoints for asking NL→SQL questions.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Tuple

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

logger = logging.getLogger(__name__)
bp = Blueprint("query", __name__, url_prefix="/api")


@lru_cache(maxsize=16)
def _get_engine(db_uri: str, llm_model: str) -> "QueryEngine":
    """Create (or reuse) a QueryEngine per (db_uri, model) pair."""
    from core.db.query_engine import QueryEngine  # lazy import
    logger.info("🔌 Creating QueryEngine for %s | model=%s", db_uri, llm_model)
    return QueryEngine(db_uri, llm_model=llm_model)


def _parse_body() -> Tuple[str, str, str, bool]:
    data = request.get_json(silent=True) or {}
    db_uri = (data.get("db_uri") or "").strip()
    question = (data.get("question") or "").strip()
    model = (data.get("model") or "").strip() or "deepseek/deepseek-chat"
    debug_flag = bool(data.get("debug", True))

    if not db_uri:
        raise BadRequest("'db_uri' is required")
    if not question:
        raise BadRequest("'question' is required")

    return db_uri, question, model, debug_flag


@bp.post("/query")
def post_query():
    """Run NL→SQL and return answer, sql, rows, rowcount, suggestions."""
    try:
        db_uri, question, model, debug_flag = _parse_body()
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400

    try:
        engine = _get_engine(db_uri, model)
        # Streamed progress is handled in SSE; here we do a blocking ask.
        result = engine.ask(question, debug=debug_flag)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query failed")
        return jsonify({"error": str(exc)}), 500

    # Optional embedding suggestions
    suggestions = []
    try:
        from core.db.embedder import DBEmbedder
        sa_engine = sa.create_engine(db_uri)
        embedder = DBEmbedder(sa_engine)
        suggestions = embedder.similarity_search(question, k=3)
    except Exception as e:
        logger.warning("Embedding suggestions error: %s", e)

    return jsonify({
        "answer": result.get("answer"),
        "sql": result.get("sql"),
        "data": result.get("data"),
        "rowcount": result.get("rowcount"),
        "embedding_suggestions": suggestions,
            "debug": result.get("debug"),
    }), 200