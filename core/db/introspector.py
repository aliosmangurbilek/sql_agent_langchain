from __future__ import annotations
"""Introspector

Tek bir sorgu ile PostgreSQL veritabanındaki *tüm* kullanici şemalarini gezerek
tablo & sütun metadatasini döner.

Her satırda aşağıdaki alanlar sağlanır::

    {
        "schema": "public",
        "table": "customers",
        "column": "customer_id",
        "data_type": "integer",
        "is_nullable": false,
        "is_primary_key": true,
        "fk_refs": ["public.orders.customer_id"],
        "row_estimate": 599,
        "table_size_mb": 1.34,
        "table_comment": "Müşteri temel bilgileri",
        "column_comment": "Birincil anahtar"
    }

Bu çıktı, DBEmbedder tarafında şema‑RAG için kullanılır.
"""

from typing import List, Dict, Any
from decimal import Decimal

from sqlalchemy import Engine, text

# -----------------------------------------------------------------------------
# Ana fonksiyon
# -----------------------------------------------------------------------------

def get_metadata(engine: Engine) -> List[Dict[str, Any]]:
    """Veritabanı şema metadatasını geri döndür."""

    sql = text(
        """
        WITH fk AS (
            SELECT
                con.conrelid                     AS relid,
                ck.attnum                        AS attnum,
                string_agg(
                    quote_ident(ns2.nspname) || '.' ||
                    quote_ident(cl2.relname) || '.' ||
                    quote_ident(att2.attname),
                    ','
                )                                AS fk_refs
            FROM pg_constraint  con
            JOIN pg_class       cl1   ON cl1.oid = con.conrelid
            JOIN pg_namespace   ns1   ON ns1.oid = cl1.relnamespace
            JOIN pg_class       cl2   ON cl2.oid = con.confrelid
            JOIN pg_namespace   ns2   ON ns2.oid = cl2.relnamespace
            JOIN unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord) ON TRUE
            JOIN unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord)
                                            USING(ord)
            JOIN pg_attribute att2 ON att2.attrelid = con.confrelid
                                   AND att2.attnum  = fk.attnum
            WHERE con.contype = 'f'
              AND ns1.nspname NOT IN ('pg_catalog','information_schema')
            GROUP BY con.conrelid, ck.attnum
        ),
        pk AS (
            SELECT
                con.conrelid                     AS relid,
                unnest(con.conkey)               AS attnum
            FROM pg_constraint con
            WHERE con.contype = 'p'
        )
        SELECT
            ns.nspname                                    AS schema,
            c.relname                                     AS table,
            att.attname                                   AS column,
            format_type(att.atttypid, att.atttypmod)      AS data_type,
            NOT att.attnotnull                            AS is_nullable,
            COALESCE(pk.attnum IS NOT NULL, FALSE)        AS is_primary_key,
            COALESCE(fk.fk_refs, '')                      AS fk_refs,
            c.reltuples::bigint                           AS row_estimate,
            pg_total_relation_size(c.oid)::bigint/1048576 AS table_size_mb,
            obj_description(c.oid)                        AS table_comment,
            col_description(c.oid, att.attnum)            AS column_comment
        FROM pg_class           c
        JOIN pg_namespace       ns   ON ns.oid = c.relnamespace
        JOIN pg_attribute       att  ON att.attrelid = c.oid
        LEFT JOIN fk ON fk.relid = c.oid AND fk.attnum = att.attnum
        LEFT JOIN pk ON pk.relid = c.oid AND pk.attnum = att.attnum
        WHERE c.relkind IN ('r','p')
          AND ns.nspname NOT IN ('pg_catalog','information_schema')
          AND att.attisdropped = FALSE
        ORDER BY ns.nspname, c.relname, att.attnum;
        """
    )

    # Use modern SQLAlchemy 2.0+ syntax
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    def _to_float(val: Any) -> float:
        if isinstance(val, Decimal):
            return float(val)
        return float(val) if val is not None else 0.0

    result: List[Dict[str, Any]] = []
    for row in rows:
        result.append({
            "schema":          row["schema"],
            "table":           row["table"],
            "column":          row["column"],
            "data_type":       row["data_type"],
            "is_nullable":     bool(row["is_nullable"]),
            "is_primary_key":  bool(row["is_primary_key"]),
            "fk_refs":         row["fk_refs"].split(",") if row["fk_refs"] else [],
            "row_estimate":    int(row["row_estimate"]),
            "table_size_mb":   _to_float(row["table_size_mb"]),
            "table_comment":   row["table_comment"],
            "column_comment":  row["column_comment"],
        })

    return result
