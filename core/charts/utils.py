"""
core.charts.utils
~~~~~~~~~~~~~~~~~

Genel yardımcı işlevler:

• infer_field_types(rows)  →  {field: "quantitative"|"temporal"|"nominal"}
• sample_rows(data, limit) →  veri dizisinin ilk N öğesini döndür
• looks_temporal / is_numeric / vl_type  →  tip kestirimi
• shorten_title(title, max_len) →  uzun başlıkları kırpar
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import numpy as np


# ------------------------------------------------------------------ #
# Tip kestirimi / alan analizi
# ------------------------------------------------------------------ #


def looks_temporal(col: str, val: Any) -> bool:
    """Kolon adı veya değeri zaman bilgisini mi işaret ediyor?"""
    pat = re.compile(r"(date|time|year|month|day)", re.I)
    return bool(pat.search(col)) or isinstance(val, (np.datetime64,))  # noqa: E721


def is_numeric(val: Any) -> bool:
    """Değer sayısal mı? (int, float, numpy number)."""
    return isinstance(val, (int, float, np.number))


def infer_field_types(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    İlk satıra bakarak Vega-Lite field tipi tahmini.

    Returns
    -------
    dict
        {"field_name": "temporal"|"quantitative"|"nominal"}
    """
    if not rows:
        return {}
    sample = rows[0]
    types: Dict[str, str] = {}
    for col, val in sample.items():
        if looks_temporal(col, val):
            types[col] = "temporal"
        elif is_numeric(val):
            types[col] = "quantitative"
        else:
            types[col] = "nominal"
    return types


def vl_type(field: str) -> str:
    """Kolon adından Vega-Lite tipi (temporal/nominal) türet."""
    return "temporal" if re.search(r"(date|time|year|month|day)", field, re.I) else "nominal"


# ------------------------------------------------------------------ #
# Veri / Başlık yardımcıları
# ------------------------------------------------------------------ #


def sample_rows(data: List[Dict[str, Any]], limit: int = 100) -> List[Dict[str, Any]]:
    """Veri dizisinin ilk *limit* satırını döndür (grafik önizlemesi için kafi)."""
    return data[:limit]


def shorten_title(title: str, max_len: int = 60) -> str:
    """Başlık metni çok uzunsa kes (… ile)."""
    return title if len(title) <= max_len else title[: max_len - 3] + "…"
