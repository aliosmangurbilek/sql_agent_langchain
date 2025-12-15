from __future__ import annotations

"""core.db.introspector
-------------------------------------------------
Lightweight helper to extract **structural metadata** from any SQLAlchemy‑
compatible database engine.  The resulting data structure is JSON‑serialisable
and intended to feed both the embedding layer and human‑readable diagnostics.

Usage
~~~~~
>>> from sqlalchemy import create_engine
>>> from core.db.introspector import get_metadata
>>> engine = create_engine("postgresql://...")
>>> meta = get_metadata(engine)
"""

# Core imports
from typing import Any, Dict, List
import warnings
import sqlalchemy as sa

# Suppress SAWarning for unrecognized 'vector' column types
try:
    from sqlalchemy.exc import SAWarning  # type: ignore
    warnings.filterwarnings(
        'ignore',
        r"Did not recognize type 'vector' of column",
        category=SAWarning
    )
except Exception:
    # Fallback for environments without SAWarning symbol
    warnings.filterwarnings(
        'ignore',
        r"Did not recognize type 'vector' of column",
        category=Warning,
        module='sqlalchemy'
    )

__all__ = ["get_metadata"]


def _classify(coltype: sa.types.TypeEngine) -> str:
    """Rough heuristic to bucket SQLAlchemy types into 'numeric', 'datetime',
    'vector', 'boolean', or 'categorical'. Extend as needed."""
    # Integer-like (incl. small/big)
    if isinstance(coltype, (sa.SmallInteger, sa.Integer, sa.BigInteger, sa.Numeric, sa.Float, sa.DECIMAL)):
        return "numeric"
    if isinstance(coltype, (sa.Date, sa.DateTime, sa.TIMESTAMP)):
        return "datetime"
    # Time/interval types
    if hasattr(sa, 'Time') and isinstance(coltype, getattr(sa, 'Time')):
        return "datetime"
    if hasattr(sa, 'Interval') and isinstance(coltype, getattr(sa, 'Interval')):
        return "datetime"
    # Booleans
    if isinstance(coltype, sa.Boolean):
        return "boolean"
    # PostgreSQL vector tipi için string kontrolü
    if 'vector' in str(coltype).lower():
        return "vector"
    return "categorical"


def _classify_from_str(type_str: str) -> str:
    """String-based type classifier for fast-path (Postgres catalog)."""
    s = (type_str or "").lower()
    if "vector" in s:
        return "vector"
    if any(tok in s for tok in ["int", "numeric", "decimal", "double", "real", "float", "serial"]):
        return "numeric"
    if any(tok in s for tok in ["date", "time", "timestamp", "timestamptz", "interval", "year", "month"]):
        return "datetime"
    if "bool" in s:
        return "boolean"
    return "categorical"


def _quote_ident(name: str) -> str:
    name = name or ""
    return '"' + name.replace('"', '""') + '"'


def _get_metadata_pg_fast(engine: sa.Engine, sample_rows: int = 0) -> List[Dict[str, Any]]:
    """Fast metadata collection using PostgreSQL catalogs in a single query.

    Returns rows: {schema, table, column, type, category[, sample]}
    Skips system schemas and vector columns.
    """
    sql = sa.text(
        r"""
        SELECT
            n.nspname AS schema,
            c.relname AS table,
            a.attname AS column,
            format_type(a.atttypid, a.atttypmod) AS type,
            obj_description(c.oid) AS table_comment,
            col_description(c.oid, a.attnum) AS column_comment
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE a.attnum > 0 AND NOT a.attisdropped
          AND n.nspname NOT IN ('pg_catalog','information_schema')
          AND c.relkind IN ('r','v','m','p')  -- table, view, materialized, partitioned
          AND format_type(a.atttypid, a.atttypmod) !~* 'vector'
        ORDER BY n.nspname, c.relname, a.attnum
        """
    )
    meta: List[Dict[str, Any]] = []
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    for r in rows:
        schema = r["schema"] or ""
        table = r["table"]
        col   = r["column"]
        typ   = r["type"]
        if "vector" in (typ or "").lower():
            continue
        rec: Dict[str, Any] = {
            "schema": schema,
            "table": table,
            "column": col,
            "type": typ,
            "category": _classify_from_str(typ),
        }
        # Include comments if present
        try:
            tcomm = r.get("table_comment")
            ccomm = r.get("column_comment")
            if tcomm:
                rec["table_comment"] = str(tcomm)
            if ccomm:
                rec["column_comment"] = str(ccomm)
        except Exception:
            pass
        meta.append(rec)

    if sample_rows > 0:
        # Best-effort sampling per (schema, table, column)
        try:
            with engine.connect() as conn:
                for rec in meta:
                    s = rec["schema"]
                    t = rec["table"]
                    c = rec["column"]
                    full_name = f"{_quote_ident(s)}.{_quote_ident(t)}" if s else _quote_ident(t)
                    col_name  = _quote_ident(c)
                    try:
                        stmt = sa.text(f"SELECT {col_name} FROM {full_name} LIMIT :lim")
                        vals = conn.execute(stmt, {"lim": sample_rows}).scalars().all()
                        rec["sample"] = vals
                    except Exception:
                        rec["sample"] = []
        except Exception:
            # Sampling is optional; ignore errors globally
            pass

    return meta


def get_metadata(engine: sa.Engine, sample_rows: int = 0) -> List[Dict[str, Any]]:
    """Return a list of dicts describing every column (PostgreSQL only).

    Uses pg_catalog for a single-query fast-path. This module targets PostgreSQL
    exclusively; other dialects are not supported.
    """
    if not engine.dialect.name.startswith("postgres"):
        raise RuntimeError("PostgreSQL required: dialect is '%s'" % engine.dialect.name)
    return _get_metadata_pg_fast(engine, sample_rows=sample_rows)


if __name__ == "__main__":
    # Minimal CLI to inspect a database and print a compact metadata summary
    import argparse
    import json
    import sqlalchemy as sa

    parser = argparse.ArgumentParser(description="Print database structural metadata")
    parser.add_argument("db_uri", help="SQLAlchemy connection URI, e.g. postgresql://user:pass@host:5432/db")
    parser.add_argument("--sample", type=int, default=0, help="Sample up to N values per column (may be slow)")
    parser.add_argument("--limit", type=int, default=10, help="Limit output rows for readability")
    args = parser.parse_args()

    eng = sa.create_engine(args.db_uri)
    meta = get_metadata(eng, sample_rows=args.sample)

    # Print a compact view first
    unique_tables = sorted({m["table"] for m in meta})
    print(f"Tables ({len(unique_tables)}):", ", ".join(unique_tables))
    print(f"Columns total: {len(meta)}")
    print("Sample (limited):")
    print(json.dumps(meta[: args.limit], indent=2))

