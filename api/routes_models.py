"""
api.routes_models
~~~~~~~~~~~~~~~~~

GET /api/models → Get available OpenRouter models with filtering and sorting
"""

import logging
import os
import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
bp = Blueprint("models", __name__, url_prefix="/api")


@bp.route('/models', methods=['GET'])
def get_models():
    """
    OpenRouter'dan mevcut modelleri getir ve filtrele.
    
    Query Parameters:
    - search: Model ismi veya açıklamasında arama yap
    - free_only: Sadece ücretsiz modelleri döndür (true/false)
    - provider: Belirli provider'a göre filtrele
    """
    try:
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # API key varsa authorized request yap
        if openrouter_api_key:
            headers["Authorization"] = f"Bearer {openrouter_api_key}"
        
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            models_data = response.json()
            
            # Query parametrelerini al
            search_query = request.args.get("search", "").lower()
            free_only = request.args.get("free_only", "false").lower() == "true"
            provider_filter = request.args.get("provider", "").lower()
            
            # Modelleri işle ve filtrele
            filtered_models = []
            for model in models_data.get("data", []):
                # Moderated olmayan modelleri atla
                if not model.get("top_provider", {}).get("is_moderated", True):
                    continue

                model_id = model.get("id", "")
                name = model.get("name", model_id)
                description = model.get("description", "")
                pricing = model.get("pricing", {}) or {}
                
                # Fiyat hesaplama
                prompt_price = float(pricing.get("prompt", "0"))
                completion_price = float(pricing.get("completion", "0"))
                total_price = prompt_price + completion_price
                is_free = total_price == 0
                
                # Provider bilgisi
                provider = model_id.split("/")[0] if "/" in model_id else "unknown"
                
                # Filtreleme
                if search_query:
                    if not (search_query in name.lower() or 
                           search_query in model_id.lower() or 
                           search_query in description.lower()):
                        continue
                
                if free_only and not is_free:
                    continue
                    
                if provider_filter and provider_filter != provider:
                    continue

                filtered_models.append({
                    "id": model_id,
                    "name": name,
                    "description": description,
                    "context_length": model.get("context_length", 0),
                    "pricing": {
                        "prompt": f"{prompt_price:.6f}",
                        "completion": f"{completion_price:.6f}",
                        "total": f"{total_price:.6f}",
                    },
                    "architecture": model.get("architecture", {}),
                    "provider": provider,
                    "is_free": is_free,
                    "total_price": total_price,
                })

            # Sıralama: Önce ücretsiz modeller, sonra fiyat, sonra isim
            filtered_models.sort(key=lambda m: (not m["is_free"], m["total_price"], m["name"]))
            
            return jsonify({
                "status": "success",
                "models": filtered_models,
                "count": len(filtered_models),
                "filters": {
                    "search": search_query,
                    "free_only": free_only,
                    "provider": provider_filter
                }
            }), 200
            
        else:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return _fallback_models()
            
    except requests.RequestException as e:
        logger.error(f"Request to OpenRouter failed: {e}")
        return _fallback_models()
    except Exception as e:
        logger.error(f"Unexpected error getting models: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


def _fallback_models():
    """OpenRouter API'ye ulaşılamazsa kullanılacak fallback modeller."""
    fallback_models = [
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek Chat (Free)",
            "description": "Fast and capable chat model, completely free",
            "context_length": 4096,
            "pricing": {"prompt": "0.000000", "completion": "0.000000", "total": "0.000000"},
            "architecture": {"modality": "text", "tokenizer": "DeepSeek"},
            "provider": "deepseek",
            "is_free": True,
            "total_price": 0
        },
        {
            "id": "meta-llama/llama-3.1-8b-instruct:free",
            "name": "Llama 3.1 8B Instruct (Free)",
            "description": "Meta's powerful open-source model, free tier",
            "context_length": 8192,
            "pricing": {"prompt": "0.000000", "completion": "0.000000", "total": "0.000000"},
            "architecture": {"modality": "text", "tokenizer": "Llama"},
            "provider": "meta-llama",
            "is_free": True,
            "total_price": 0
        },
        {
            "id": "qwen/qwen-2.5-7b-instruct:free",
            "name": "Qwen 2.5 7B Instruct (Free)",
            "description": "Alibaba's multilingual model, free tier",
            "context_length": 4096,
            "pricing": {"prompt": "0.000000", "completion": "0.000000", "total": "0.000000"},
            "architecture": {"modality": "text", "tokenizer": "Qwen"},
            "provider": "qwen",
            "is_free": True,
            "total_price": 0
        }
    ]
    
    return jsonify({
        "status": "fallback",
        "models": fallback_models,
        "count": len(fallback_models),
        "message": "Using fallback models due to OpenRouter API unavailability"
    }), 200
