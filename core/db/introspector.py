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


def get_metadata(engine: sa.Engine, sample_rows: int = 0) -> List[Dict[str, Any]]:
    """Return a list of dicts describing every column in the database.

    Parameters
    ----------
    engine        : SQLAlchemy Engine already connected.
    sample_rows   : If >0, fetch up to *sample_rows* example values per column
                    (expensive on large tables; disabled by default).
    """
    inspector = sa.inspect(engine)
    meta: List[Dict[str, Any]] = []

    # Collect schemas: default schema + non-system schemas if available
    schemas: List[str] = []
    try:
        default_schema = getattr(inspector, 'default_schema_name', None)
        if default_schema:
            schemas.append(default_schema)
        for sch in inspector.get_schema_names():
            if sch not in schemas and sch not in ("information_schema", "pg_catalog"):
                schemas.append(sch)
    except Exception:
        # Fallback: single implicit schema
        schemas = [None]  # type: ignore

    metadata = sa.MetaData()
    for schema in schemas:
        try:
            table_names = inspector.get_table_names(schema=schema)  # type: ignore[arg-type]
        except Exception:
            table_names = inspector.get_table_names()
        for table_name in table_names:
            # Reflect table once for Core-based sampling
            try:
                table_obj = sa.Table(table_name, metadata, autoload_with=engine, schema=schema)
            except Exception:
                table_obj = None

            for col in inspector.get_columns(table_name, schema=schema):
                # Skip vector or unknown vector-like columns
                col_type_str = str(col.get('type', '')).lower()
                if 'vector' in col_type_str:
                    continue

                record: Dict[str, Any] = {
                    "schema": schema or "",
                    "table": table_name,
                    "column": col["name"],
                    "type": str(col["type"]),
                    "category": _classify(col["type"]),
                }

                if sample_rows > 0 and table_obj is not None:
                    try:
                        col_name = col["name"]
                        if col_name in table_obj.c:  # type: ignore[operator]
                            stmt = sa.select(table_obj.c[col_name]).limit(sample_rows)
                            with engine.connect() as conn:
                                rows = conn.execute(stmt).scalars().all()
                            record["sample"] = rows
                        else:
                            record["sample"] = []
                    except Exception:
                        record["sample"] = []  # best-effort only

                meta.append(record)

    return meta


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
