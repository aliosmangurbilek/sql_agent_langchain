"""
api.routes_chart
~~~~~~~~~~~~~~~~

POST /api/chart
Body (JSON):
{
  "db_uri": "postgresql://user:pw@localhost:5432/pagila",
  "question": "monthly rentals per store in 2005",
  // Optional fast-path to avoid re-running agent:
  "sql": "SELECT ...",
  "data": [ { ... }, ... ]
}

Response:
{
  "sql": "...",
  "data": [ { ... }, ... ],
  "rowcount": 42,
  "vega_spec": { ... }          # Vega-Lite 5 JSON
}
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Dict, Any

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from core.db.query_engine import QueryEngine
from core.charts.spec_generator import generate_chart_spec

logger = logging.getLogger(__name__)
bp = Blueprint("chart", __name__, url_prefix="/api")


@lru_cache(maxsize=16)
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat") -> QueryEngine:
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    return QueryEngine(db_uri, llm_model=llm_model)


@bp.post("/chart")
def run_chart():
    """
    Doğal dil isteğini alır → SQL + veri → Vega-Lite spec döner.

    Eğer body içerisinde `sql` ve/veya `data` verilmişse agent tekrar
    çalıştırılmaz; doğrudan bu verilerden grafik spec'i üretilir.
    """
    if not request.is_json:
        raise BadRequest("Content-Type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get("model", "deepseek/deepseek-chat")

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    try:
        sql = body.get("sql")
        rows: List[Dict[str, Any]] | None = body.get("data")

        if sql and isinstance(rows, list):
            # Fast-path: Frontend'den gelen sonuçları kullan
            result_sql = sql
            result_rows = rows
        else:
            # Gerekirse agent'i bir kez çalıştır
            qe = _get_engine(db_uri, llm_model=model)
            result = qe.ask(question)              # {"answer", "sql", "data"}
            result_sql = result.get("sql", "")
            result_rows = result.get("data") or []

        rowcount = len(result_rows) if isinstance(result_rows, list) else 0

        # Grafik spec'ini üret (tek geçiş, agent yok)
        vega_spec = generate_chart_spec(
            question=question,
            sql=result_sql,
            data=result_rows,
        )

        return (
            jsonify(
                {
                    "sql": result_sql,
                    "data": result_rows,
                    "rowcount": rowcount,
                    "vega_spec": vega_spec,
                }
            ),
            200,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Chart generation failed")
        return jsonify({"error": str(exc)}), 500
