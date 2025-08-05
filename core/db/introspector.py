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
from collections import defaultdict
from typing import Any, Dict, List
import warnings
import sqlalchemy as sa
from typing import List, Dict, Any

# Suppress SAWarning for unrecognized 'vector' column types
try:
    from sqlalchemy.exc import SAWarning
    warnings.filterwarnings(
        'ignore',
        r"Did not recognize type 'vector' of column",
        category=SAWarning
    )
except ImportError:
    pass

__all__ = ["get_metadata"]


def _classify(coltype: sa.types.TypeEngine) -> str:
    """Rough heuristic to bucket SQLAlchemy types into 'numeric', 'datetime',
    'vector', or 'categorical'. Extend as needed."""
    if isinstance(coltype, (sa.Integer, sa.Numeric, sa.Float, sa.DECIMAL)):
        return "numeric"
    if isinstance(coltype, (sa.Date, sa.DateTime, sa.TIMESTAMP)):
        return "datetime"
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

    for schema in inspector.get_schema_names():
        for table_name in inspector.get_table_names(schema=schema):
            for column in inspector.get_columns(table_name, schema=schema):
                # Tam nitelikli tablo adını ekle (schema.table)
                qualified_table_name = f"{schema}.{table_name}"
                record: Dict[str, Any] = {
                    "table": qualified_table_name,
                    "column": column["name"],
                    "type": str(column["type"]),
                    "category": _classify(column["type"]),
                }
                if sample_rows > 0:
                    try:
                        sql = sa.text(
                            f"SELECT {sa.sql.quote_identifier(column['name'])} FROM "
                            f"{sa.sql.quote_identifier(table_name)} LIMIT :limit"
                        )
                        with engine.connect() as conn:
                            rows = conn.execute(sql, {"limit": sample_rows}).scalars().all()
                        record["sample"] = rows
                    except Exception:  # noqa: BLE001
                        record["sample"] = []  # ignore missing perms, etc.
                meta.append(record)

    return meta

