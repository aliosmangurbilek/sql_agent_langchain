"""
core.charts.spec_generator
~~~~~~~~~~~~~~~~~~~~~~~~~~

* `generate_chart_spec()`  –  Doğal dil sorudan & veri örneğinden
  otomatik Vega-Lite 5 JSON spec'i üretir.

Heuristikler
------------
1. Zaman alanı ("date", "time", "year", "month") + sayısal alan → Line chart
2. Kategorik alan + sayısal alan → Bar chart
3. Yalnızca iki sayısal alan → Scatter plot
4. Diğer durumlar → Tablo (arkaplanda bar gömme)

Sadece heuristik yaklaşım kullanılır; OpenAI bağımlılığı kaldırıldı.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import numpy as np

# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #


def generate_chart_spec(
    question: str,
    sql: str,
    data: List[Dict[str, Any]],
    *,
    use_llm: bool = False,  # kept for API compatibility, ignored
) -> Dict[str, Any]:
    """
    Heuristik tabanlı Vega-Lite spec üret.

    Parameters
    ----------
    question : str
        Kullanıcının doğal dil sorgusu (grafik başlığı için).
    sql : str
        Çalıştırılan SQL (tool-tip için).
    data : list[dict]
        QueryEngine'den gelen satırlar (ilk ~100 satır yeter).
    use_llm : bool, default False (ignored)
        Eskiden LLM post-processing içindi; artık kullanılmıyor.

    Returns
    -------
    dict
        Vega-Lite 5 JSON spec (frontend `vega.embed()` ile çizilebilir).
    """
    if not data:
        return _empty_spec("No data returned", question)

    field_types = _infer_field_types(data)
    chart_type, enc = _choose_chart(field_types, data)
    spec = _build_spec(chart_type, enc, question, sql)
    return spec


# ------------------------------------------------------------------ #
# Heuristik engine
# ------------------------------------------------------------------ #


def _infer_field_types(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Kolon adlarından & ilk satırlardan tip tahmini.

    Returns
    -------
    {field_name: "quantitative"|"temporal"|"nominal"}
    """
    sample = rows[0]
    types: Dict[str, str] = {}
    for col, val in sample.items():
        if _looks_temporal(col, val):
            types[col] = "temporal"
        elif _is_numeric(val):
            types[col] = "quantitative"
        else:
            types[col] = "nominal"
    return types


def _choose_chart(field_types: Dict[str, str], rows: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """
    Basit kurallara göre chart tipi & encoding seç.
    Returns
    -------
    ("line"|"bar"|"point"|"table", encoding_dict)
    """
    temporal = [f for f, t in field_types.items() if t == "temporal"]
    quantitative = [f for f, t in field_types.items() if t == "quantitative"]
    nominal = [f for f, t in field_types.items() if t == "nominal"]

    if temporal:
        temporal = _rank_temporal_fields(rows, temporal)
    if quantitative:
        quantitative = _rank_numeric_fields(rows, quantitative)
    if nominal:
        nominal = _rank_nominal_fields(rows, nominal)

    if temporal and quantitative:
        x = temporal[0]
        y = quantitative[0]
        return "line", {"x": x, "y": y}
    if nominal and quantitative:
        x = nominal[0]
        y = quantitative[0]
        return "bar", {"x": x, "y": y}
    if len(quantitative) >= 2:
        return "point", {"x": quantitative[0], "y": quantitative[1]}
    # fallback – tablo
    return "table", {"columns": list(field_types.keys())}


def _rank_numeric_fields(rows: List[Dict[str, Any]], fields: List[str]) -> List[str]:
    variances = {}
    for f in fields:
        vals = [row[f] for row in rows if isinstance(row.get(f), (int, float))]
        variances[f] = float(np.var(vals)) if vals else 0.0
    return sorted(fields, key=lambda x: variances[x], reverse=True)


def _rank_nominal_fields(rows: List[Dict[str, Any]], fields: List[str]) -> List[str]:
    counts = {}
    for f in fields:
        counts[f] = len({row[f] for row in rows if f in row})
    return sorted(fields, key=lambda x: counts[x], reverse=True)


def _rank_temporal_fields(rows: List[Dict[str, Any]], fields: List[str]) -> List[str]:
    import numpy as _np
    ranges = {}
    for f in fields:
        vals = []
        for row in rows:
            v = row.get(f)
            if v is None:
                continue
            try:
                vals.append(_np.datetime64(v))
            except Exception:
                pass
        if vals:
            ranges[f] = float((max(vals) - min(vals)).astype('timedelta64[s]') / _np.timedelta64(1, 's'))
        else:
            ranges[f] = 0.0
    return sorted(fields, key=lambda x: ranges[x], reverse=True)


def _build_spec(chart: str, enc: Dict[str, Any], title: str, sql: str) -> Dict[str, Any]:
    """Vega-Lite spec üret."""
    if chart == "table":
        # Simple bar-wrapped table
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": title,
            "data": {"name": "table"},  # front-end inline_data embed edecek
            "mark": "text",
            "encoding": {
                "row": {"field": enc["columns"][0], "type": "nominal"},
                "column": {"field": enc["columns"][1], "type": "nominal"}
                if len(enc["columns"]) > 1
                else {"value": ""},
                "text": {"field": enc["columns"][0], "type": "nominal"},
            },
            "config": {"view": {"stroke": "transparent"}},
            "title": title,
            "usermeta": {"sql": sql},
        }

    # XY charts
    mark = {"line": "line", "bar": "bar", "point": "point"}[chart]
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": title,
        "data": {"name": "table"},
        "mark": mark,
        "encoding": {
            "x": {"field": enc["x"], "type": _vl_type(enc["x"], chart)},
            "y": {"field": enc["y"], "type": "quantitative"},
            "tooltip": [
                {"field": enc["x"], "type": _vl_type(enc["x"], chart)},
                {"field": enc["y"], "type": "quantitative"},
            ],
        },
        "title": title,
        "usermeta": {"sql": sql},
    }


# ------------------------------------------------------------------ #
# Util
# ------------------------------------------------------------------ #


def _looks_temporal(col: str, val: Any) -> bool:
    pat = re.compile(r"(date|time|year|month)", re.I)
    try:
        import numpy as _np
        return bool(pat.search(col)) or isinstance(val, (_np.datetime64,))  # noqa: E721
    except Exception:
        return bool(pat.search(col))


def _is_numeric(val: Any) -> bool:
    try:
        import numpy as _np
        return isinstance(val, (int, float, _np.number))
    except Exception:
        return isinstance(val, (int, float))


def _vl_type(field: str, chart: str) -> str:
    """Vega-Lite tip kestirimi (temporal veya nominal)."""
    return "temporal" if re.search(r"(date|time|year|month)", field, re.I) else "nominal"


def _empty_spec(msg: str, title: str) -> Dict[str, Any]:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": title,
        "data": {"values": [{"Message": msg}]},
        "mark": "text",
        "encoding": {"text": {"field": "Message", "type": "nominal"}},
        "title": title,
    }
