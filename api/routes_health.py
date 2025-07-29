"""
api.routes_health
~~~~~~~~~~~~~~~~~

GET  /healthz   → 200 {"status": "ok"}
POST /test_connection → Test database connection
GET  /api/models → Get available OpenRouter models
"""

from flask import Blueprint, jsonify, request
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
import logging
import requests
import os

logger = logging.getLogger(__name__)
bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Kapsayıcı veya servis ayakta mı?"""
    return jsonify(status="ok"), 200


@bp.route('/api/models', methods=['GET'])
def get_models():
    """OpenRouter'dan mevcut modelleri getir."""
    try:
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # API key varsa authorized request yap, yoksa public catalog getir
        if openrouter_api_key:
            headers["Authorization"] = f"Bearer {openrouter_api_key}"
        
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            models_data = response.json()
            
            # Modelleri filtrele ve formatla
            filtered_models = []
            for model in models_data.get("data", []):
                # Sadece aktif modelleri al
                if not model.get("top_provider", {}).get("is_moderated", True):
                    continue
                    
                filtered_models.append({
                    "id": model["id"],
                    "name": model.get("name", model["id"]),
                    "description": model.get("description", ""),
                    "context_length": model.get("context_length", 0),
                    "pricing": {
                        "prompt": model.get("pricing", {}).get("prompt", "0"),
                        "completion": model.get("pricing", {}).get("completion", "0")
                    },
                    "architecture": model.get("architecture", {}),
                    "is_free": model.get("pricing", {}).get("prompt", "0") == "0"
                })
            
            # Ücretsiz modelleri önce sırala
            filtered_models.sort(key=lambda x: (not x["is_free"], x["name"]))
            
            return jsonify({
                "status": "success",
                "models": filtered_models,
                "count": len(filtered_models)
            }), 200
        else:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return jsonify({
                "status": "error", 
                "error": f"OpenRouter API returned {response.status_code}"
            }), 500
            
    except requests.RequestException as e:
        logger.error(f"Request to OpenRouter failed: {e}")
        return jsonify({
            "status": "error",
            "error": "Failed to connect to OpenRouter API"
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error getting models: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


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
