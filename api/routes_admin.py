"""Admin endpoints for embedding / schema lifecycle management.

GET  /api/admin/embeddings/status?db_uri=...   → koleksiyon durumu
POST /api/admin/embeddings/rebuild {db_uri: ...} → manuel rebuild & flag reset

Tasarlanan davranış:
 - Otomatik rebuild yerine embedder SCHEMA_CHANGE_MODE=mark iken sadece needs_rebuild flag set eder.
 - Kullanıcı arayüzü status endpoint'ini poll eder, needs_rebuild True ise banner gösterip rebuild çağırır.
"""
from __future__ import annotations

from flask import Blueprint, request, jsonify
import sqlalchemy as sa
import logging
import os

from core.db.embedder import DBEmbedder

logger = logging.getLogger(__name__)
bp = Blueprint("admin", __name__, url_prefix="/api/admin")

_SIG_META_TABLE = "app_schema_embed_meta"


def _ensure_sig_table(conn) -> None:
    conn.execute(sa.text(
        f"""
        CREATE TABLE IF NOT EXISTS {_SIG_META_TABLE} (
          collection_name text PRIMARY KEY,
          signature text,
          needs_rebuild boolean DEFAULT false,
          components_json jsonb,
          updated_at timestamptz DEFAULT now()
        )
        """
    ))
    # Forward migration: add column if table existed without it
    try:
        conn.execute(sa.text(f"ALTER TABLE {_SIG_META_TABLE} ADD COLUMN IF NOT EXISTS components_json jsonb"))
    except Exception:
        pass


def _upsert_signature(conn, collection: str, signature: str | None, needs_rebuild: bool) -> None:
    conn.execute(
        sa.text(
            f"""
            INSERT INTO {_SIG_META_TABLE}(collection_name, signature, needs_rebuild, updated_at)
            VALUES (:n, :s, :r, now())
            ON CONFLICT (collection_name)
            DO UPDATE SET signature = COALESCE(EXCLUDED.signature, {_SIG_META_TABLE}.signature),
                          needs_rebuild = EXCLUDED.needs_rebuild,
                          updated_at = now()
            """
        ),
        {"n": collection, "s": signature, "r": needs_rebuild},
    )


def _fetch_sig_row(conn, collection_name: str):
    try:
        return conn.execute(
            sa.text(
                f"SELECT signature, needs_rebuild, updated_at, components_json FROM {_SIG_META_TABLE} WHERE collection_name=:n"
            ),
            {"n": collection_name},
        ).mappings().first()
    except Exception:
        # Legacy table (no components_json)
        row = conn.execute(
            sa.text(
                f"SELECT signature, needs_rebuild, updated_at FROM {_SIG_META_TABLE} WHERE collection_name=:n"
            ),
            {"n": collection_name},
        ).mappings().first()
        if row:
            row = dict(row)
            row["components_json"] = None
        return row


def _detect_index_type(conn, collection_name: str) -> str:
    """Best-effort index type detection for given collection (HNSW / IVFFlat / none)."""
    try:
        row = conn.execute(
            sa.text("SELECT uuid FROM public.langchain_pg_collection WHERE name = :n"),
            {"n": collection_name},
        ).fetchone()
        if not row:
            return "none"
        cid = str(row[0])
        rows = conn.execute(
            sa.text(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname='public' AND tablename='langchain_pg_embedding'
                """
            )
        ).fetchall()
        for (idxdef,) in rows:
            low = (idxdef or "").lower()
            if cid in (idxdef or "") and " using hnsw " in low:
                return "hnsw"
            if cid in (idxdef or "") and " using ivfflat " in low:
                return "ivfflat"
        return "none"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Index detection failed: {e}")
        return "unknown"


@bp.get("/embeddings/status")
def embeddings_status():
    db_uri = request.args.get("db_uri")
    include_components = request.args.get("components") == "1"
    no_pool = request.args.get("nopool") == "1"
    debug = request.args.get("debug") == "1"
    force_check = request.args.get("force_check") == "1"
    if not db_uri:
        return jsonify({"error": "db_uri param required"}), 400
    try:
        if no_pool:
            from sqlalchemy.pool import NullPool  # type: ignore
            eng = sa.create_engine(db_uri, poolclass=NullPool)
        else:
            eng = sa.create_engine(db_uri)
        emb = DBEmbedder(eng)
        # İsteğe bağlı: embedder.ensure_store çağırıp _check_schema_change tetikle (force_check=1)
        if force_check:
            try:
                emb.ensure_store()  # Lazy check; mark modunda needs_rebuild set edebilir
            except Exception as fc_exc:  # noqa: BLE001
                logger.warning("force_check ensure_store failed: %s", fc_exc)
        if not eng.url.get_backend_name().startswith("postgres"):
            return jsonify({
                "collection": emb.collection_name,
                "backend": eng.url.get_backend_name(),
                "supported": False,
                "reason": "Only PostgreSQL (pgvector) supported",
            }), 200
        with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            _ensure_sig_table(conn)
            sig_row = _fetch_sig_row(conn, emb.collection_name)
            index_type = _detect_index_type(conn, emb.collection_name)
            mode = os.getenv("SCHEMA_CHANGE_MODE", "mark").lower()
            # Canlı şema imzasını yeniden hesapla (kullanıcı buton tetikli kontrol istedi)
            live_sig = None
            try:
                live_sig = emb._schema_signature()  # type: ignore[attr-defined]
            except Exception as sig_exc:  # noqa: BLE001
                logger.warning("Live schema signature compute failed: %s", sig_exc)
            # Migration: eğer components_json yoksa (null) şu anki filtreli komponentleri kaydet ve signature'ı normalize et
            if sig_row and sig_row.get("components_json") is None and live_sig:
                try:
                    comps_now = emb._schema_components()  # type: ignore[attr-defined]
                    import hashlib, json as _json
                    normalized_sig = hashlib.sha256(_json.dumps(comps_now, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                    if sig_row["signature"] != normalized_sig:
                        # Migration: signature değişti ama bu sadece internal tablo filtre normalizasyonu – needs_rebuild dokunma
                        conn.execute(sa.text(f"UPDATE {_SIG_META_TABLE} SET signature=:s, components_json=:c, updated_at=now() WHERE collection_name=:n"),{"s": normalized_sig, "c": _json.dumps(comps_now), "n": emb.collection_name})
                        sig_row = _fetch_sig_row(conn, emb.collection_name) or sig_row
                        logger.info("[EMBED STATUS] migration normalized signature old=%s new=%s collection=%s", (sig_row["signature"] or "")[:8], normalized_sig[:8], emb.collection_name)
                    else:
                        conn.execute(sa.text(f"UPDATE {_SIG_META_TABLE} SET components_json=:c, updated_at=now() WHERE collection_name=:n"),{"c": _json.dumps(comps_now), "n": emb.collection_name})
                        sig_row = _fetch_sig_row(conn, emb.collection_name) or sig_row
                        logger.info("[EMBED STATUS] components backfilled (no signature change) collection=%s", emb.collection_name)
                except Exception as mig_exc:  # noqa: BLE001
                    logger.warning("Could not run components_json migration: %s", mig_exc)
            if not sig_row:
                # Collection may not be initialized yet
                if live_sig:
                    logger.info(
                        "[EMBED STATUS] collection=%s not initialized (live_sig=%s mode=%s)",
                        emb.collection_name,
                        live_sig[:8],
                        mode,
                    )
                else:
                    logger.info(
                        "[EMBED STATUS] collection=%s not initialized (no signature) mode=%s",
                        emb.collection_name,
                        mode,
                    )
                return jsonify({
                    "collection": emb.collection_name,
                    "initialized": False,
                    "needs_rebuild": True,
                    "index_type": index_type,
                    "mode": mode,
                    "live_signature_head": (live_sig or "")[:8],
                }), 200
            signature = sig_row["signature"] or ""
            stored_sig_head = signature[:8]
            live_sig_head = (live_sig or "")[:8]
            diff_detected = bool(live_sig and signature and live_sig != signature)
            if diff_detected:
                # mark modunda embedder signature'ı ilerletmediği için burada sadece flag'in set olduğundan emin ol
                if mode != "off" and not bool(sig_row["needs_rebuild"]):
                    try:
                        conn.execute(
                            sa.text(
                                f"UPDATE {_SIG_META_TABLE} SET needs_rebuild=true, updated_at=now() WHERE collection_name=:n"
                            ),
                            {"n": emb.collection_name},
                        )
                        sig_row = _fetch_sig_row(conn, emb.collection_name) or sig_row
                    except Exception as upd_exc:  # noqa: BLE001
                        logger.warning("Could not set needs_rebuild flag during status diff: %s", upd_exc)
                logger.info(
                    "[EMBED STATUS] collection=%s DIFF detected stored=%s live=%s needs_rebuild=%s mode=%s",
                    emb.collection_name,
                    stored_sig_head,
                    live_sig_head,
                    bool(sig_row["needs_rebuild"]),
                    mode,
                )
            else:
                # Log component count for diagnostics
                comp_count = None
                try:
                    comp_count = conn.execute(sa.text(f"SELECT jsonb_array_length(components_json) FROM {_SIG_META_TABLE} WHERE collection_name=:n"),{"n": emb.collection_name}).scalar()
                except Exception:
                    pass
                logger.info(
                    "[EMBED STATUS] collection=%s OK signature=%s needs_rebuild=%s mode=%s components=%s",
                    emb.collection_name,
                    stored_sig_head,
                    bool(sig_row["needs_rebuild"]),
                    mode,
                    comp_count,
                )
            # Reason determination (simplified states)
            nr = bool(sig_row["needs_rebuild"])
            if not nr:
                reason = "ok"
            else:
                if not diff_detected and stored_sig_head == live_sig_head:
                    reason = "persisted_after_previous_change"  # flag kaldı; rebuild bekliyor
                elif diff_detected:
                    reason = "pending_rebuild_schema_changed"
                else:
                    reason = "needs_rebuild"
            payload = {
                "collection": emb.collection_name,
                "initialized": True,
                "needs_rebuild": nr,
                "signature_head": stored_sig_head,
                "updated_at": sig_row["updated_at"],
                "index_type": index_type,
                "mode": mode,
                "live_signature_head": live_sig_head,
                "diff_detected": diff_detected,
                "reason": reason,
            }
            if debug:
                payload["stored_signature_full"] = signature
                payload["live_signature_full"] = live_sig
            if include_components:
                try:
                    # Provide live schema components (could be large)
                    payload["schema_components"] = emb._schema_components()  # type: ignore[attr-defined]
                    payload["stored_components"] = sig_row.get("components_json")
                    # Basic diff if stored components exist
                    stored = sig_row.get("components_json") or []
                    live = payload["schema_components"]
                    # Normalize stored removing now-excluded internal tables for backward compatibility
                    norm_stored = []
                    for t in stored:
                        try:
                            _schema, _table, _col, _typ = t
                            if _table == emb._SIG_META_TABLE or _table.startswith("langchain_pg_"):  # type: ignore[attr-defined]
                                continue
                            norm_stored.append(t)
                        except Exception:
                            continue
                    if norm_stored and norm_stored != stored:
                        stored = norm_stored
                    try:
                        stored_set = set(tuple(t) for t in stored)
                        live_set = set(tuple(t) for t in live)
                        payload["component_added"] = sorted(list(live_set - stored_set))
                        payload["component_removed"] = sorted(list(stored_set - live_set))
                    except Exception:
                        pass
                except Exception as comp_exc:  # noqa: BLE001
                    payload["schema_components_error"] = str(comp_exc)
            return jsonify(payload), 200
    except Exception as e:  # noqa: BLE001
        logger.exception("Status endpoint failure")
        return jsonify({"error": str(e)}), 500


@bp.post("/embeddings/rebuild")
def embeddings_rebuild():
    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    if not db_uri:
        return jsonify({"error": "'db_uri' required"}), 400
    try:
        eng = sa.create_engine(db_uri)
        emb = DBEmbedder(eng, force_rebuild=True)  # Rebuild done inside
        # Update signature table after rebuild
        sig_head = None
        if eng.url.get_backend_name().startswith("postgres"):
            try:
                new_sig = emb._schema_signature()  # type: ignore (internal use)
                with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    _ensure_sig_table(conn)
                    conn.execute(
                        sa.text(
                            f"""
                            INSERT INTO {_SIG_META_TABLE}(collection_name, signature, needs_rebuild, updated_at)
                            VALUES (:n,:s,false, now())
                            ON CONFLICT (collection_name)
                            DO UPDATE SET signature=EXCLUDED.signature,
                                          needs_rebuild=false,
                                          updated_at=now()
                            """
                        ),
                        {"n": emb.collection_name, "s": new_sig},
                    )
                sig_head = new_sig[:8]
            except Exception as ie:  # noqa: BLE001
                logger.warning(f"Could not persist new signature after rebuild: {ie}")
        return jsonify({"status": "ok", "collection": emb.collection_name, "signature_head": sig_head}), 200
    except Exception as e:  # noqa: BLE001
        logger.exception("Rebuild endpoint failure")
        return jsonify({"status": "failure", "error": str(e)}), 500


@bp.post("/embeddings/check")
def embeddings_check():
    """Manual schema change check (simplified phase 1).

    Logic:
      - Compute live signature
      - If no row: create row (signature=NULL, needs_rebuild=True)
      - If stored signature is None: keep needs_rebuild True (initial state)
      - If stored signature == live: needs_rebuild stays as is (usually False)
      - If different: set needs_rebuild True (do NOT advance signature)
    """
    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    if not db_uri:
        return jsonify({"error": "'db_uri' required"}), 400
    try:
        eng = sa.create_engine(db_uri)
        emb = DBEmbedder(eng)
        if not eng.url.get_backend_name().startswith("postgres"):
            return jsonify({"error": "postgres required"}), 400
        live_sig = emb._schema_signature()  # type: ignore[attr-defined]
        with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            _ensure_sig_table(conn)
            row = _fetch_sig_row(conn, emb.collection_name)
            if not row:
                # Initialize row with no stored signature yet → force rebuild first
                _upsert_signature(conn, emb.collection_name, None, True)
                logger.info("[EMBED CHECK] init collection=%s live=%s needs_rebuild=True", emb.collection_name, live_sig[:8])
                changed = True
                stored_sig_head = None
            else:
                stored_sig = row.get("signature")
                stored_sig_head = (stored_sig or "")[:8] if stored_sig else None
                if stored_sig and stored_sig == live_sig:
                    changed = False
                    logger.info("[EMBED CHECK] same collection=%s sig=%s", emb.collection_name, stored_sig_head)
                else:
                    changed = stored_sig is not None and stored_sig != live_sig
                    # Mark needs_rebuild True (signature not advanced)
                    _upsert_signature(conn, emb.collection_name, stored_sig, True)
                    logger.info(
                        "[EMBED CHECK] changed=%s collection=%s stored=%s live=%s set needs_rebuild=True",
                        changed,
                        emb.collection_name,
                        (stored_sig or "")[:8] if stored_sig else None,
                        live_sig[:8],
                    )
            out = {
                "collection": emb.collection_name,
                "changed": changed,
                "needs_rebuild": True if changed else (row.get("needs_rebuild") if row else True),
                "stored_signature_head": stored_sig_head,
                "live_signature_head": live_sig[:8],
            }
            return jsonify(out), 200
    except Exception as e:  # noqa: BLE001
        logger.exception("Check endpoint failure")
        return jsonify({"error": str(e)}), 500


