"""
api.routes_query
~~~~~~~~~~~~~~~~

POST /api/query
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

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from config import resolve_db_uri
from core.db.engine_registry import get_query_engine

logger = logging.getLogger(__name__)
bp = Blueprint("query", __name__, url_prefix="/api")


@bp.post("/query")
def run_query():
    """Doğal dil sorgusunu çalıştır ve sonucu JSON olarak döndür."""
    if not request.is_json:
        raise BadRequest("Request content-type must be application/json")

    body = request.get_json(silent=True) or {}
    question = body.get("question")
    model = body.get("model") or current_app.config.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    if not question:
        raise BadRequest("'question' field is required")

    try:
        db_uri = resolve_db_uri(body.get("db_uri"), body.get("database"))
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc

    try:
        # Model parametresini de kullan
        qe = get_query_engine(db_uri, llm_model=model)
        result = qe.ask(question)
        return jsonify(result), 200
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query failed")
        return jsonify({"error": str(exc)}), 500
