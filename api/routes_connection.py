"""
Database connection testing routes
"""

from flask import Blueprint, request, jsonify
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('connection', __name__, url_prefix='/api')


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
