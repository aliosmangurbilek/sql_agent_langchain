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
    """Heuristik + hafif NLP ile Vega-Lite spec üret (A+B+C geliştirmeleri).

    İyileştirmeler:
    - (A) İlk N satır (varsayılan 50) üzerinden tip & kardinalite analizi.
    - (A) Aşırı yüksek kardinalite nominal alanlarda top-N (default 15) kırpma / bar yerine tablo.
    - (B) Nominal + numerik seçildiğinde yinelenen kategorileri aggregate (sum) ile topla.
    - (C) Soru ipuçları (trend, top, dağılım) ile chart tipi override.
    - Çok küçük veri seti (<=10 satır) için hata fırlat (kullanıcıya daha anlamlı veri üretmesi istenir).
    """
    if not data:
        return _empty_spec("No data returned", question)

    row_count = len(data)
    if row_count <= 9:  # Kullanıcı isteği: 10 satır civarı sonuçta hata ver
        raise ValueError(f"Result set too small for chart (rows={row_count}). Provide a broader query.")

    sample = data[:50]
    analysis = _analyze_fields(sample)
    chart_type, enc, opts = _choose_chart(question, analysis, sample)
    spec = _build_spec(chart_type, enc, question, sql, analysis, opts)
    return spec


# ------------------------------------------------------------------ #
# Heuristik engine
# ------------------------------------------------------------------ #


def _analyze_fields(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Çok satırlı örnek üzerinden alan analizi.

    Dönen yapı:
      {
        'types': {field: type},
        'cardinality': {field: distinct_count},
        'null_ratio': {field: 0..1},
        'numeric_variance': {field: var},
      }
    """
    if not rows:
        return {"types": {}, "cardinality": {}, "null_ratio": {}, "numeric_variance": {}}

    types: Dict[str, str] = {}
    cardinality: Dict[str, int] = {}
    null_ratio: Dict[str, float] = {}
    numeric_variance: Dict[str, float] = {}

    fields = list(rows[0].keys())
    import collections, math
    values_by_field: Dict[str, list] = {f: [] for f in fields}
    for r in rows:
        for f in fields:
            values_by_field[f].append(r.get(f))

    for f, vals in values_by_field.items():
        non_null = [v for v in vals if v is not None]
        null_ratio[f] = 1 - (len(non_null) / max(1, len(vals)))
        sample_val = next((v for v in non_null if v is not None), None)
        if sample_val is not None and _looks_temporal(f, sample_val):
            types[f] = "temporal"
        elif all(_is_numeric(v) for v in non_null[: min(5, len(non_null))]) and sum(
            1 for v in non_null if _is_numeric(v)
        ) >= max(1, int(0.7 * len(non_null))):
            types[f] = "quantitative"
        else:
            types[f] = "nominal"
        cardinality[f] = len({v for v in non_null})
        if types[f] == "quantitative":
            nums = [float(v) for v in non_null if _is_numeric(v)]
            if len(nums) >= 2:
                m = sum(nums) / len(nums)
                numeric_variance[f] = sum((x - m) ** 2 for x in nums) / (len(nums) - 1)
            else:
                numeric_variance[f] = 0.0
    return {
        "types": types,
        "cardinality": cardinality,
        "null_ratio": null_ratio,
        "numeric_variance": numeric_variance,
    }


def _choose_chart(question: str, analysis: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Chart seçimi + encoding + ops.

    Ek dönen ops:
      {
        'aggregate': bool,
        'top_n': int|None,
      }
    """
    field_types = analysis["types"]
    temporal = [f for f, t in field_types.items() if t == "temporal"]
    quantitative = [f for f, t in field_types.items() if t == "quantitative"]
    nominal = [f for f, t in field_types.items() if t == "nominal"]

    # Rank fields
    if temporal:
        temporal = _rank_temporal_fields(rows, temporal)
    if quantitative:
        quantitative = sorted(quantitative, key=lambda f: analysis["numeric_variance"].get(f, 0), reverse=True)
    if nominal:
        nominal = _rank_nominal_fields(rows, nominal)

    q_low = question.lower()
    cue_trend = any(k in q_low for k in ["trend", "zaman", "timeline", "ay", "month", "hafta", "week", "gün", "daily"])
    cue_scatter = any(k in q_low for k in ["scatter", "dağılım", "distribution"])
    cue_top = any(k in q_low for k in ["top", "en fazla", "en çok", "highest", "largest", "max"])

    opts = {"aggregate": False, "top_n": None}

    if cue_scatter and len(quantitative) >= 2:
        return "point", {"x": quantitative[0], "y": quantitative[1]}, opts

    if (cue_trend or cue_top) and temporal and quantitative:
        return "line", {"x": temporal[0], "y": quantitative[0]}, opts

    if temporal and quantitative:
        return "line", {"x": temporal[0], "y": quantitative[0]}, opts

    if nominal and quantitative:
        # High cardinality handling
        card = analysis["cardinality"].get(nominal[0], 0)
        if card > 60:
            # Too many categories – revert to table
            return "table", {"columns": list(field_types.keys())[:6]}, opts
        if card > 20:
            opts["top_n"] = 15
        opts["aggregate"] = True  # aggregate repeating categories
        return "bar", {"x": nominal[0], "y": quantitative[0]}, opts

    if len(quantitative) >= 2:
        return "point", {"x": quantitative[0], "y": quantitative[1]}, opts

    return "table", {"columns": list(field_types.keys())[:6]}, opts


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


def _build_spec(chart: str, enc: Dict[str, Any], title: str, sql: str, analysis: Dict[str, Any], opts: Dict[str, Any]) -> Dict[str, Any]:
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
    spec: Dict[str, Any] = {
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
    enc_y = spec["encoding"]["y"]
    if opts.get("aggregate"):
        enc_y["aggregate"] = "sum"
    # Top-N filtering transform (descending by y after aggregate if aggregate applied)
    if opts.get("top_n"):
        topn = opts["top_n"]
        spec.setdefault("transform", [])
        if opts.get("aggregate"):
            # aggregate then window + filter
            # Vega-Lite auto aggregate via encoding.aggregate; we emulate ranking after aggregation
            spec["transform"].extend([
                {"window": [{"op": "row_number", "as": "__rn"}], "sort": [{"field": enc["y"], "order": "descending"}]},
                {"filter": f"datum.__rn <= {topn}"},
            ])
        else:
            spec["transform"].extend([
                {"aggregate": [{"op": "sum", "field": enc["y"], "as": "__agg_y"}], "groupby": [enc["x"]]},
                {"window": [{"op": "row_number", "as": "__rn"}], "sort": [{"field": "__agg_y", "order": "descending"}]},
                {"filter": f"datum.__rn <= {topn}"},
            ])
            spec["encoding"]["y"]["field"] = "__agg_y"
            spec["encoding"]["y"].pop("aggregate", None)
            spec["encoding"]["tooltip"].append({"field": "__agg_y", "type": "quantitative", "title": "Sum"})
    return spec


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
