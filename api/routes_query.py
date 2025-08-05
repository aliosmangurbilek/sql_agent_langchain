"""
api.routes_query
~~~~~~~~~~~~~~~@lru_cache(maxsize=16)  # aynı db_uri ve model için QueryEngine nesnesini sakla
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat"):
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    
    # Lazy import to avoid segfault on startup
    try:
        from core.db.query_engine import QueryEngine
        logger.info(f"Using OpenRouter model: {llm_model}")
        return QueryEngine(db_uri, llm_model=llm_model)
    except Exception as e:
        logger.error(f"Failed to create QueryEngine: {e}")
        raisequery
Body (JSON):
{
  "db_uri": "postgresql://user:pw@localhost:5432/pagila",
  "question": "total rentals per month in 2005 for customer Mary Smith"
}

Response:
{
  "answer": "<natural language answer>"
}
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
import requests

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

# Don't import heavy ML libraries at startup
# from core.db.query_engine import QueryEngine
# from core.db.embedder import DBEmbedder
import sqlalchemy as sa

logger = logging.getLogger(__name__)
bp = Blueprint("query", __name__, url_prefix="/api")


@lru_cache(maxsize=16)  # aynı db_uri ve model için QueryEngine nesnesini sakla
def _get_engine(db_uri: str, llm_model: str = "deepseek/deepseek-chat") -> QueryEngine:
    # Her db_uri ve llm_model kombinasyonu için bir kere QueryEngine oluştur
    # Bu sayede aynı veritabanı için birden fazla kez embedding yapmayız
    
    # Lazy import to avoid segfault on startup
    try:
        from core.db.query_engine import QueryEngine
        logger.info(f"Using OpenRouter model: {llm_model}")
        return QueryEngine(db_uri, llm_model=llm_model)
    except Exception as e:
        logger.error(f"Failed to create QueryEngine: {e}")
        raise


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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query failed")
        return jsonify({"error": str(exc)}), 500

    # Embedding ile en alakalı tablo/kolon önerilerini ekle
    try:
        from core.db.embedder import DBEmbedder
        sa_engine = sa.create_engine(db_uri)
        embedder = DBEmbedder(sa_engine)
        suggestions = embedder.similarity_search(question, k=3)
    except Exception as e:
        logger.warning(f"Embedding suggestions error: {e}")
        suggestions = []

    return jsonify({
        "answer": result.get("answer"),
        "sql": result.get("sql"),
        "data": result.get("data"),
        "rowcount": result.get("rowcount"),
        "embedding_suggestions": suggestions,
    }), 200


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
        
        # Model arama terimi (opsiyonel)
        search_query = request.args.get("search", "").lower()

        # Tüm modelleri listele ve arama uygula
        listed_models = []
        for model in models:
            model_id = model.get("id", "")
            name = model.get("name", model_id)
            description = model.get("description", "")
            pricing = model.get("pricing", {})
            prompt_price = float(pricing.get("prompt", "1"))
            completion_price = float(pricing.get("completion", "1"))
            is_free = prompt_price == 0 and completion_price == 0
            context_length = model.get("context_length", 4096)
            provider = model_id.split("/")[0] if "/" in model_id else "unknown"
            # Arama terimi varsa filtrele
            if search_query:
                if search_query in name.lower() or search_query in model_id.lower() or search_query in description.lower():
                    listed_models.append({
                        "id": model_id,
                        "name": name,
                        "description": description,
                        "is_free": is_free,
                        "context_length": context_length,
                        "provider": provider
                    })
            else:
                listed_models.append({
                    "id": model_id,
                    "name": name,
                    "description": description,
                    "is_free": is_free,
                    "context_length": context_length,
                    "provider": provider
                })

        return jsonify({
            "models": listed_models,  # Tüm modelleri döndür
            "total": len(listed_models)
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
