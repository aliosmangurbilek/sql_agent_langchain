"""
api.routes_models
~~~~~~~~~~~~~~~~~
GET /api/models → List OpenRouter models (filtered) with UI-expected fields.
"""
from __future__ import annotations

import logging
import os
from typing import List, Dict, Any

import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
bp = Blueprint("models", __name__, url_prefix="/api")


def _coerce_pricing(model: Dict[str, Any]) -> Dict[str, Any]:
    pricing = model.get("pricing") or {}
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    try:
        total = None
        if prompt is not None and completion is not None:
            total = float(prompt) + float(completion)
    except Exception:
        total = None
    out: Dict[str, Any] = {}
    if prompt is not None:
        out["prompt"] = str(prompt)
    if completion is not None:
        out["completion"] = str(completion)
    if total is not None:
        out["total"] = f"{total:.6f}"
    return out


@bp.get("/models")
def get_models():
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return jsonify({"status": "error", "message": "OPENROUTER_API_KEY not set"}), 400

    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.exception("Failed to fetch models")
        return jsonify({"status": "error", "message": str(e)}), 502

    search_query = request.args.get("search", "").lower()
    free_only = request.args.get("free_only", "false").lower() == "true"
    provider_filter = request.args.get("provider", "").lower()

    filtered: List[Dict[str, Any]] = []
    for model in payload.get("data", []):
        mid = (model.get("id") or "")
        mid_lower = mid.lower()
        name = model.get("name") or model.get("id") or ""
        description = model.get("description") or ""
        top = model.get("top_provider", {}) or {}
        provider = (top.get("name") or "").lower()
        # Better "free" detection: either API says so, or id contains free-suffix
        is_free = bool(top.get("is_free", False)) or (":free" in mid_lower) or ("-free" in mid_lower)
        is_moderated = top.get("is_moderated", None)

        if search_query and (search_query not in mid_lower) and (search_query not in name.lower()):
            continue
        if provider_filter and provider_filter != provider:
            continue
        if free_only and not is_free:
            continue

        filtered.append({
            "id": mid,
            "name": name,
            "provider": top.get("name"),
            "description": description,
            "is_free": is_free,
            "is_moderated": is_moderated,
            "pricing": _coerce_pricing(model),
        })

    # Sort alphabetically by display name (fallback to id)
    filtered.sort(key=lambda m: (m.get("name") or m.get("id") or "").lower())
    return jsonify({"status": "success", "models": filtered, "total": len(filtered)}), 200