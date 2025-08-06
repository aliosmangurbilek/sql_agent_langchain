"""
Database connection testing routes
"""

from flask import Blueprint, request, jsonify
import logging
from config import get_config

logger = logging.getLogger(__name__)

bp = Blueprint('connection', __name__, url_prefix='/api')


@bp.get('/config')
def get_app_config():
    """Get application configuration values for UI initialization"""
    try:
        config = get_config()
        return jsonify({
            "status": "success",
            "config": {
                "base_database_url": config.BASE_DATABASE_URL,
                "default_db_uri": config.DEFAULT_DB_URI,
                "openrouter_model": config.OPENROUTER_MODEL
            }
        }), 200
    except Exception as e:
        logger.error(f"Config retrieval error: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to get config: {str(e)}"
        }), 500


@bp.post('/test_connection')
def test_connection():
    """Test database connection without loading heavy ML libraries"""
    try:
        data = request.get_json()
        if not data or 'db_uri' not in data:
            return jsonify({
                "status": "error",
                "message": "Database URI is required",
                "connected": False
            }), 400
        
        db_uri = data['db_uri'].strip()
        if not db_uri:
            return jsonify({
                "status": "error", 
                "message": "Database URI cannot be empty",
                "connected": False
            }), 400
        
        # Import connection test function lazily
        from core.db.connection_test import test_database_connection
        
        result = test_database_connection(db_uri)
        
        if result["connected"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Connection test error: {e}")
        return jsonify({
            "status": "error",
            "message": f"Test failed: {str(e)}",
            "connected": False
        }), 500
