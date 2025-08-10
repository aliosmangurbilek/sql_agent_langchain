"""
api.routes_worker
~~~~~~~~~~~~~~~~~
Proxy endpoints to the background worker service.
"""
from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request
import requests

from config import get_config

logger = logging.getLogger(__name__)
bp = Blueprint("worker", __name__, url_prefix="/api/worker")


def _base() -> str:
    return get_config().WORKER_BASE_URL.rstrip("/")


@bp.get("/status")
def worker_status():
    try:
        r = requests.get(f"{_base()}/status", timeout=5)
        r.raise_for_status()
        return jsonify(r.json()), 200
    except Exception as e:
        logger.warning("Worker status error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 502


@bp.post("/switch")
def worker_switch():
    data = request.get_json(silent=True) or {}
    database = (data.get("database") or "").strip()
    if not database:
        return jsonify({"status": "error", "message": "'database' is required"}), 400
    try:
        r = requests.post(f"{_base()}/switch", json={"database": database}, timeout=10)
        r.raise_for_status()
        return jsonify(r.json()), 200
    except Exception as e:
        logger.warning("Worker switch error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 502