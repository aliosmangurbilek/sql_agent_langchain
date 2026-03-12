"""Database selection endpoints exposed to the frontend."""

from __future__ import annotations

from flask import Blueprint, jsonify

from config import get_database_catalog, get_default_database_name, has_default_db_uri

bp = Blueprint("databases", __name__, url_prefix="/api")


@bp.get("/databases")
def get_databases():
    catalog = get_database_catalog()
    return jsonify(
        {
            "databases": catalog,
            "default_database": get_default_database_name(),
            "has_default_db": has_default_db_uri(),
        }
    ), 200
