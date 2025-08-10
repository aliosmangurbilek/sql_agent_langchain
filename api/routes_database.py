"""
Database management API endpoints
"""
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest

from core.db.database_manager import database_manager

logger = logging.getLogger(__name__)
bp = Blueprint('database', __name__, url_prefix='/api')


@bp.post('/database/test-and-prepare')
def test_and_prepare_database():
    """Test database connection and prepare embeddings if needed."""
    try:
        data = request.get_json(silent=True) or {}
        db_uri = (data.get("db_uri") or "").strip()
        force_rebuild = bool(data.get("force_rebuild", False))
        
        if not db_uri:
            return jsonify({"error": "'db_uri' is required"}), 400
        
        # Get comprehensive database information
        db_info = database_manager.get_database_info(db_uri)
        
        if not db_info.get('connected', False):
            return jsonify({
                "status": "error",
                "connected": False,
                "message": db_info.get('message', 'Connection failed')
            }), 400
        
        # Ensure embeddings if connection successful
        if force_rebuild:
            embedding_result = database_manager.ensure_embeddings(db_uri, force_rebuild=True)
        else:
            embedding_result = database_manager.ensure_embeddings(db_uri, force_rebuild=False)
        
        return jsonify({
            "status": "success",
            "connected": True,
            "database_info": db_info,
            "embedding_info": embedding_result,
            "message": f"Database ready: {db_info.get('table_count', 0)} tables available"
        }), 200
        
    except Exception as e:
        logger.exception("Database preparation failed")
        return jsonify({
            "status": "error",
            "connected": False,
            "message": str(e)
        }), 500


@bp.post('/database/search-tables')
def search_tables():
    """Search for relevant tables in a database."""
    try:
        data = request.get_json(silent=True) or {}
        db_uri = (data.get("db_uri") or "").strip()
        query = (data.get("query") or "").strip()
        k = int(data.get("k", 5))
        
        if not db_uri:
            return jsonify({"error": "'db_uri' is required"}), 400
        if not query:
            return jsonify({"error": "'query' is required"}), 400
        
        # Search for tables
        results = database_manager.search_tables(db_uri, query, k=k)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results)
        }), 200
        
    except Exception as e:
        logger.exception("Table search failed")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bp.get('/database/info/<path:db_uri>')
def get_database_info(db_uri: str):
    """Get information about a database."""
    try:
        db_info = database_manager.get_database_info(db_uri)
        return jsonify(db_info), 200
        
    except Exception as e:
        logger.exception("Failed to get database info")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bp.post('/database/rebuild-embeddings')
def rebuild_embeddings():
    """Force rebuild embeddings for a database."""
    try:
        data = request.get_json(silent=True) or {}
        db_uri = (data.get("db_uri") or "").strip()
        
        if not db_uri:
            return jsonify({"error": "'db_uri' is required"}), 400
        
        # Force rebuild embeddings
        result = database_manager.ensure_embeddings(db_uri, force_rebuild=True)
        
        return jsonify({
            "status": "success",
            "message": "Embeddings rebuilt successfully",
            "details": result
        }), 200
        
    except Exception as e:
        logger.exception("Failed to rebuild embeddings")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bp.post('/database/cleanup')
def cleanup_database_cache():
    """Clean up database connection cache."""
    try:
        database_manager.cleanup_cache()
        
        return jsonify({
            "status": "success",
            "message": "Database cache cleaned up"
        }), 200
        
    except Exception as e:
        logger.exception("Failed to clean up cache")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
