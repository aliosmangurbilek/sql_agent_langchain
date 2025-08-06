"""
api.routes_health
~~~~~~~~~~~~~~~~~

GET  /healthz   → 200 {"status": "ok"}
"""

from flask import Blueprint, jsonify
import logging

logger = logging.getLogger(__name__)
bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Kapsayıcı veya servis ayakta mı?"""
    return jsonify(status="ok"), 200
