"""
api.routes_health
~~~~~~~~~~~~~~~~~

GET  /healthz   → 200 {"status": "ok"}
GET  /api/models → Get available OpenRouter models
"""

from flask import Blueprint, jsonify
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
                if not model.get("top_provider", {}).get("is_moderated", True):
                    continue

                pricing = model.get("pricing", {}) or {}
                prompt_price = float(pricing.get("prompt", "0"))
                completion_price = float(pricing.get("completion", "0"))
                total_price = prompt_price + completion_price

                filtered_models.append({
                    "id": model["id"],
                    "name": model.get("name", model["id"]),
                    "description": model.get("description", ""),
                    "context_length": model.get("context_length", 0),
                    "pricing": {
                        "prompt": f"{prompt_price:.6f}",
                        "completion": f"{completion_price:.6f}",
                        "total": f"{total_price:.6f}",
                    },
                    "architecture": model.get("architecture", {}),
                    "is_free": total_price == 0,
                    "total_price": total_price,  # ◄– sıralamada kullanacağımız alan
                })

            # ➊  önce fiyat, ➋  sonra isim
            filtered_models.sort(key=lambda m: (m["total_price"], m["name"]))
            
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
