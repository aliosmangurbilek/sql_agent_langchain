"""
api.routes_query
~~~~~~~~~~~~~~~~

POST /api/query
Body (JSON):
{
  "db_uri": "postgresql://user:pw@localhost:5432/pagila",
  "question": "total rentals per month in 2005 for customer Mary Smith"
}

Response:
{
  "sql": "...",
  "data": [ { ... }, ... ],
  "rowcount": 42
}
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
import requests

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from core.db.query_engine import QueryEngine

logger = logging.getLogger(__name__)
bp = Blueprint("query", __name__, url_prefix="/api")


@lru_cache(maxsize=16)  # aynı db_uri ve model için QueryEngine nesnesini sakla
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat") -> QueryEngine:
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    
    # Direkt olarak model ID'sini kullan
    logger.info(f"Using OpenRouter model: {llm_model}")
    return QueryEngine(db_uri, llm_model=llm_model)


@bp.post("/query")
def run_query():
    """Doğal dil sorgusunu çalıştır ve sonucu JSON olarak döndür."""
    if not request.is_json:
        raise BadRequest("Request content-type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get("model", "deepseek/deepseek-chat")  # Default to free DeepSeek model if not specified

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    try:
        # Model parametresini de kullan
        qe = _get_engine(db_uri, llm_model=model)
        result = qe.ask(question)
        return jsonify(result), 200
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query failed")
        return jsonify({"error": str(exc)}), 500


@bp.get("/models")
def get_models():
    """OpenRouter'dan mevcut modelleri çek ve ücretsiz olanları filtrele."""
    try:
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        
        headers = {}
        if openrouter_api_key:
            headers["Authorization"] = f"Bearer {openrouter_api_key}"
        
        # OpenRouter API'den modelleri çek
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        
        models_data = response.json()
        models = models_data.get("data", [])
        
        # Modelleri filtrele ve düzenle
        filtered_models = []
        
        for model in models:
            model_id = model.get("id", "")
            name = model.get("name", model_id)
            pricing = model.get("pricing", {})
            
            # Ücretsiz modelleri kontrol et
            prompt_price = float(pricing.get("prompt", "1"))
            completion_price = float(pricing.get("completion", "1"))
            is_free = prompt_price == 0 and completion_price == 0
            
            # Popüler ücretsiz modelleri ekle
            if is_free or any(free_model in model_id.lower() for free_model in [
                "deepseek", "llama-3.1", "qwen", "gemini-flash", "claude-3-haiku"
            ]):
                filtered_models.append({
                    "id": model_id,
                    "name": name,
                    "is_free": is_free,
                    "context_length": model.get("context_length", 4096),
                    "provider": model_id.split("/")[0] if "/" in model_id else "unknown"
                })
        
        # Ücretsiz modelleri başa al, sonra diğerlerini ekle
        filtered_models.sort(key=lambda x: (not x["is_free"], x["name"]))
        
        return jsonify({
            "models": filtered_models[:50],  # İlk 50 modeli döndür
            "total": len(filtered_models)
        }), 200
        
    except requests.RequestException as exc:
        logger.error(f"Failed to fetch models from OpenRouter: {exc}")
        # Fallback: Bilinen ücretsiz modeller
        fallback_models = [
            {
                "id": "deepseek/deepseek-chat",
                "name": "DeepSeek Chat (Free)",
                "is_free": True,
                "context_length": 4096,
                "provider": "deepseek"
            },
            {
                "id": "meta-llama/llama-3.1-8b-instruct:free",
                "name": "Llama 3.1 8B Instruct (Free)",
                "is_free": True,
                "context_length": 4096,
                "provider": "meta-llama"
            },
            {
                "id": "qwen/qwen-2.5-7b-instruct:free",
                "name": "Qwen 2.5 7B Instruct (Free)",
                "is_free": True,
                "context_length": 4096,
                "provider": "qwen"
            }
        ]
        return jsonify({
            "models": fallback_models,
            "total": len(fallback_models)
        }), 200
    except Exception as exc:
        logger.error(f"Unexpected error fetching models: {exc}")
        return jsonify({"error": str(exc)}), 500
