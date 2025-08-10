"""
api.routes_models
~~~~~~~~~~~~~~~~~

GET /api/models → OpenRouter model listesini döndürür
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import requests
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("models", __name__, url_prefix="/api")


@bp.get("/models")
@lru_cache(maxsize=1)
def get_models():
    """OpenRouter'dan mevcut modelleri çek ve ücretsiz/ücretli olarak döndür.
    Önceden sadece ücretsiz veya belirli popülerleri alıyorduk; şimdi tüm aktif
    modelleri dahil ediyoruz ve frontend'e dengeli bir liste sağlıyoruz.
    """
    try:
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

        headers = {}
        if openrouter_api_key:
            headers["Authorization"] = f"Bearer {openrouter_api_key}"

        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()

        models_data = response.json()
        models = models_data.get("data", [])

        free_models = []
        paid_models = []

        for model in models:
            model_id = model.get("id", "")
            name = model.get("name", model_id)
            pricing = model.get("pricing", {})

            # Ücretsiz mi hesapla (string veya sayı gelebilir)
            def _to_float(v, default=1.0):
                try:
                    return float(v)
                except Exception:
                    return default
            prompt_price = _to_float(pricing.get("prompt", 1))
            completion_price = _to_float(pricing.get("completion", 1))
            is_free = (prompt_price == 0.0) and (completion_price == 0.0)

            provider = model_id.split("/")[0] if "/" in model_id else "unknown"

            entry = {
                "id": model_id,
                "name": name,
                "is_free": is_free,
                "context_length": model.get("context_length", 4096),
                "provider": provider,
            }
            if is_free:
                free_models.append(entry)
            else:
                paid_models.append(entry)

        # İsimlere göre sırala
        free_models.sort(key=lambda x: x["name"]) 
        paid_models.sort(key=lambda x: x["name"]) 

        # Dengeli birleştir (örn. en fazla 100 ücretsiz + 100 ücretli)
        max_each = 300
        combined = free_models[:max_each] + paid_models[:max_each]

        return jsonify({
            "models": combined,
            "counts": {"free": len(free_models), "paid": len(paid_models)},
            "total": len(free_models) + len(paid_models),
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
                "provider": "deepseek",
            },
            {
                "id": "meta-llama/llama-3.1-8b-instruct:free",
                "name": "Llama 3.1 8B Instruct (Free)",
                "is_free": True,
                "context_length": 4096,
                "provider": "meta-llama",
            },
            {
                "id": "qwen/qwen-2.5-7b-instruct:free",
                "name": "Qwen 2.5 7B Instruct (Free)",
                "is_free": True,
                "context_length": 4096,
                "provider": "qwen",
            },
        ]
        return jsonify({
            "models": fallback_models,
            "counts": {"free": len(fallback_models), "paid": 0},
            "total": len(fallback_models),
        }), 200
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Unexpected error fetching models: {exc}")
        return jsonify({"error": str(exc)}), 500
