"""
Database connection & config endpoints.
"""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from urllib.parse import urlparse

from config import get_config

logger = logging.getLogger(__name__)
bp = Blueprint('connection', __name__, url_prefix='/api')


@bp.get('/config')
def get_app_config():
    """Return app configuration needed by the frontend."""
    cfg = get_config()
    return jsonify({
        "status": "success",
        "config": {
            "base_database_url": cfg.BASE_DATABASE_URL,
            "default_db_uri": cfg.DEFAULT_DB_URI,
            "worker_base_url": cfg.WORKER_BASE_URL,
            "openrouter_model": cfg.OPENROUTER_MODEL,
            "chart_width": cfg.CHART_WIDTH,
            "chart_height": cfg.CHART_HEIGHT,
        }
    }), 200


def _db_display_name(db_uri: str) -> str:
    try:
        parsed = urlparse(db_uri)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}/{parsed.path.lstrip('/') or ''}"
    except Exception:
        return db_uri


def test_database_connection(db_uri: str) -> dict:
    """Try to connect and run a trivial query."""
    try:
        engine = sa.create_engine(db_uri, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return {
            "status": "success",
            "connected": True,
            "db_uri": _db_display_name(db_uri),
        }
    except SQLAlchemyError as e:
        logger.warning("DB connection failed: %s", e)
        return {
            "status": "error",
            "connected": False,
            "message": str(e),
            "db_uri": _db_display_name(db_uri),
        }


@bp.post('/test-connection')
def post_test_connection():
    """POST body: {"db_uri": "..."} → return connectivity info."""
    data = request.get_json(silent=True) or {}
    db_uri = data.get("db_uri", "").strip()
    if not db_uri:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "'db_uri' is required"
        }), 400

    result = test_database_connection(db_uri)
    code = 200 if result.get("connected") else 400
    return jsonify(result), code