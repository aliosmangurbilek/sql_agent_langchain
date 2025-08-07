"""
api.routes_chart
~~~~~~~~~~~~~~~~

POST /api/chart
Body (JSON):
{
  "db_uri": "postgresql://user:pw@localhost:5432/pagila",
  "question": "monthly rentals per store in 2005"
}

Response:
{
  "sql": "...",
  "data": [ { ... }, ... ],
  "rowcount": 42,
  "vega_spec": { ... }          # Vega-Lite 5 JSON
}

Not: Eğer ortamda OPENAI_API_KEY varsa ve LLM destekli grafik isteniyorsa,
otomatik olarak OpenAI API ile daha iyi grafik spec'i üretilir.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from core.db.query_engine import QueryEngine
from core.charts.spec_generator import generate_chart_spec

logger = logging.getLogger(__name__)
bp = Blueprint("chart", __name__, url_prefix="/api")


@lru_cache(maxsize=16)
def _get_engine(db_uri: str, llm_model: str = "gpt-4o-mini") -> QueryEngine:
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    return QueryEngine(db_uri, llm_model=llm_model)


@bp.post("/chart")
def run_chart():
    """
    Doğal dil isteğini alır → SQL + veri → Vega-Lite spec döner.

    Front-end tarafı:
      • Dönen `data` dizisini doğrudan inline-data olarak kullanabilir
        *veya* ayrı `/api/query` çağrısından aldığı veri ile aynı yapıdır.
      • `vega_spec` içindeki `"data": {"name": "table"}`
        ise front-end uygun şekilde embed edecektir.

    Not: Ortamda OPENAI_API_KEY varsa, chart üretiminde OpenAI LLM kullanılır.
    """
    if not request.is_json:
        raise BadRequest("Content-Type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get("model", "gpt-4o-mini")  # Default to gpt-4o-mini if not specified
    use_llm = bool(body.get("use_llm", False))

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    try:
        qe = _get_engine(db_uri, llm_model=model)
        result = qe.ask(question)  # {"sql", "data", "rowcount"}

        # Grafik spec'ini üret
        vega_spec = generate_chart_spec(
            question=question,
            sql=result["sql"],
            data=result["data"],
            use_llm=use_llm,
        )

        return (
            jsonify(
                {
                    **result,  # sql, data, rowcount
                    "vega_spec": vega_spec,
                }
            ),
            200,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Chart generation failed")
        return jsonify({"error": str(exc)}), 500


@bp.post("/chart_spec")
def generate_chart_spec_only():
    """
    Generate chart specification from existing data (cache optimization).

    Body (JSON):
    {
      "question": "What are the top directors?",
      "data": [...],     # Existing query data
      "sql": "SELECT ..." # Original SQL query
    }

    Response:
    {
      "vega_spec": { ... }  # Vega-Lite 5 JSON only
    }
    """
    if not request.is_json:
        raise BadRequest("Content-Type must be application/json")

    body = request.get_json(silent=True) or {}
    question = body.get("question", "")
    data = body.get("data", [])
    sql = body.get("sql", "")
    use_llm = bool(body.get("use_llm", False))

    if not data:
        raise BadRequest("'data' field is required and cannot be empty")

    if not question:
        raise BadRequest("'question' field is required")

    try:
        logger.info(
            f"🎨 Generating chart spec from cached data for: {question[:50]}..."
        )

        # Generate chart spec using existing data
        vega_spec = generate_chart_spec(
            question=question,
            sql=sql,
            data=data,
            use_llm=use_llm,
        )

        logger.info(f"✅ Chart spec generated successfully ({len(data)} data points)")

        return (
            jsonify(
                {"status": "success", "vega_spec": vega_spec, "data_points": len(data)}
            ),
            200,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Chart spec generation failed")
        return (
            jsonify({"error": f"Chart specification generation failed: {str(exc)}"}),
            500,
        )
