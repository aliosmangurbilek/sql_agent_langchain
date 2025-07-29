"""
api.routes_health
~~~~~~~~~~~~~~~~~

GET  /healthz   → 200 {"status": "ok"}
POST /test_connection → Test database connection
"""

from flask import Blueprint, jsonify, request
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
import logging

logger = logging.getLogger(__name__)
bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Kapsayıcı veya servis ayakta mı?"""
    return jsonify(status="ok"), 200


@bp.route('/test_connection', methods=['POST'])
def test_connection():
    """Veritabanı bağlantısını test eder."""
    try:
        data = request.get_json(silent=True) or {}
        db_uri = data.get('db_uri')

        if not db_uri:
            return jsonify({'error': "'db_uri' field is required"}), 400

        # Veritabanı bağlantısını test et
        engine = sa.create_engine(db_uri)
        with engine.connect() as conn:
            # Basit bir test sorgusu çalıştır
            result = conn.execute(sa.text("SELECT 1"))
            result.fetchone()
        
        logger.info(f"Database connection test successful for URI: {db_uri[:20]}...")
        return jsonify({'status': 'success', 'message': 'Connection successful'}), 200
        
    except OperationalError as exc:
        error_msg = str(exc.orig) if hasattr(exc, 'orig') else str(exc)
        logger.error(f"Database connection failed: {error_msg}")
        return jsonify({'status': 'failure', 'error': error_msg}), 500
    except Exception as exc:
        logger.error(f"Unexpected error during connection test: {exc}")
        return jsonify({'status': 'failure', 'error': str(exc)}), 500
