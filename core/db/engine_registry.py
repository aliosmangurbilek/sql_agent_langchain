"""Process-local QueryEngine registry with bounded cache and explicit disposal."""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from threading import RLock

from core.db.query_engine import QueryEngine

logger = logging.getLogger(__name__)

_CACHE_LOCK = RLock()
_CACHE: "OrderedDict[tuple[str, str], QueryEngine]" = OrderedDict()


def _cache_limit() -> int:
    raw = (os.getenv("QUERY_ENGINE_CACHE_SIZE") or "2").strip()
    try:
        return max(1, int(raw))
    except Exception:
        return 2


def _dispose_query_engine(qe: QueryEngine) -> None:
    try:
        close_fn = getattr(qe, "close", None)
        if callable(close_fn):
            close_fn()
            return
        qe.engine.dispose()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to dispose QueryEngine resources: %s", exc)


def get_query_engine(db_uri: str, llm_model: str) -> QueryEngine:
    key = (db_uri, llm_model)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

    created = QueryEngine(db_uri, llm_model=llm_model)
    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing is not None:
            _CACHE.move_to_end(key)
            _dispose_query_engine(created)
            return existing

        _CACHE[key] = created
        limit = _cache_limit()
        while len(_CACHE) > limit:
            evicted_key, evicted_qe = _CACHE.popitem(last=False)
            logger.info("Evicting QueryEngine cache key=%s", evicted_key)
            _dispose_query_engine(evicted_qe)
        return created


def clear_query_engine_cache() -> int:
    with _CACHE_LOCK:
        items = list(_CACHE.values())
        _CACHE.clear()

    for qe in items:
        _dispose_query_engine(qe)
    return len(items)
