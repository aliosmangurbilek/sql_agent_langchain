"""
api.routes_chart
~~~~~~~~~~~~~~~~~
Build a Vega-Lite spec from already-returned data.
"""
from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from core.charts.spec_generator import generate_chart_spec

logger = logging.getLogger(__name__)
bp = Blueprint("chart", __name__, url_prefix="/api")


@bp.post("/chart")
def post_chart():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    sql = data.get("sql")
    rows = data.get("data", [])
    use_llm = bool(data.get("use_llm", False))

    if not question:
        raise BadRequest("'question' field is required")

    try:
        logger.info("🎨 Generating chart spec for: %s", question[:80])
        vega_spec = generate_chart_spec(question=question, sql=sql, data=rows, use_llm=use_llm)
        return jsonify({"status": "success", "vega_spec": vega_spec}), 200
    except Exception as e:  # noqa: BLE001
        logger.exception("Chart generation failed")
        return jsonify({"status": "error", "message": str(e)}), 500