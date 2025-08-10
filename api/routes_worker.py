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


def _wrap_status(ok: bool, payload: dict | None = None, error: str | None = None):
    """Shape the response for the frontend (worker-manager.js)."""
    if ok and payload is not None:
        return {
            "worker_online": True,
            "data": {
                "active_db": payload.get("active_db"),
                "cached_connections": payload.get("cached_connections", []),
                "status": payload.get("status", "unknown"),
            },
        }
    return {"worker_online": False, "message": error or "Worker offline"}


@bp.get("/status")
def worker_status():
    try:
        r = requests.get(f"{_base()}/status", timeout=5)
        r.raise_for_status()
        payload = r.json()
        return jsonify(_wrap_status(True, payload)), 200
    except Exception as e:
        logger.warning("Worker status error: %s", e)
        return jsonify(_wrap_status(False, error=str(e))), 200


@bp.post("/switch")
def worker_switch():
    data = request.get_json(silent=True) or {}
    database = (data.get("database") or "").strip()
    if not database:
        return jsonify({"status": "error", "message": "'database' is required"}), 400
    try:
        r = requests.post(f"{_base()}/switch", json={"database": database}, timeout=10)
        r.raise_for_status()
        payload = r.json()
        # Normalize for UI
        out = {
            "status": "success",
            "data": {"active_db": payload.get("active_db")},
        }
        return jsonify(out), 200
    except Exception as e:
        logger.warning("Worker switch error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 502


# Backward/Frontend compatibility: the UI calls /api/worker/set_db
@bp.post("/set_db")
def worker_set_db():
    data = request.get_json(silent=True) or {}
    database = (data.get("database") or "").strip()
    if not database:
        return jsonify({"status": "error", "message": "'database' is required"}), 400
    try:
        r = requests.post(f"{_base()}/switch", json={"database": database}, timeout=10)
        r.raise_for_status()
        payload = r.json()
        # Response shaped exactly like the frontend expects
        return jsonify({
            "status": "success",
            "data": {"active_db": payload.get("active_db")}
        }), 200
    except Exception as e:
        logger.warning("Worker set_db error: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 502