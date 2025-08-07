"""
api.routes_query
~~~~~~~~~~~~~~~@lru_cache(maxsize=16)  # aynı db_uri ve model için QueryEngine nesnesini sakla
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat"):
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    
    # Lazy import to avoid segfault on startup
    try:
        from core.db.query_engine import QueryEngine
        logger.info(f"Using OpenRouter model: {llm_model}")
        return QueryEngine(db_uri, llm_model=llm_model)
    except Exception as e:
        logger.error(f"Failed to create QueryEngine: {e}")
        raisequery
Body (JSON):
{
  "db_uri": "postgresql://user:pw@localhost:5432/pagila",
  "question": "total rentals per month in 2005 for customer Mary Smith"
}

Response:
{
  "answer": "<natural language answer>"
}
"""

from __future__ import annotations

import logging
from functools import lru_cache

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

# Don't import heavy ML libraries at startup
# from core.db.query_engine import QueryEngine
# from core.db.embedder import DBEmbedder
import sqlalchemy as sa

logger = logging.getLogger(__name__)
bp = Blueprint("query", __name__, url_prefix="/api")


@lru_cache(maxsize=16)  # aynı db_uri ve model için QueryEngine nesnesini sakla
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat") -> QueryEngine:
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız

    # Lazy import to avoid segfault on startup
    try:
        from core.db.query_engine import QueryEngine

        logger.info(f"Using OpenRouter model: {llm_model}")
        return QueryEngine(db_uri, llm_model=llm_model)
    except Exception as e:
        logger.error(f"Failed to create QueryEngine: {e}")
        raise


@bp.post("/query")
def run_query():
    """Doğal dil sorgusunu çalıştır ve sonucu JSON olarak döndür."""
    if not request.is_json:
        raise BadRequest("Request content-type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get(
        "model", "deepseek/deepseek-chat"
    )  # Default to free DeepSeek model if not specified

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    try:
        # Model parametresini de kullan
        qe = _get_engine(db_uri, llm_model=model)
        result = qe.ask(question)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query failed")
        return jsonify({"error": str(exc)}), 500

    # Embedding ile en alakalı tablo/kolon önerilerini ekle
    try:
        from core.db.embedder import DBEmbedder

        sa_engine = sa.create_engine(db_uri)
        embedder = DBEmbedder(sa_engine)
        suggestions = embedder.similarity_search(question, k=3)
    except Exception as e:
        logger.warning(f"Embedding suggestions error: {e}")
        suggestions = []

    return (
        jsonify(
            {
                "answer": result.get("answer"),
                "sql": result.get("sql"),
                "data": result.get("data"),
                "rowcount": result.get("rowcount"),
                "embedding_suggestions": suggestions,
            }
        ),
        200,
    )


# Model endpoint'i artık routes_models.py'de
