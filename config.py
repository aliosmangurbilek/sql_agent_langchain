"""
Application configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pydantic-based settings loaded from environment variables (.env supported).
Only OpenRouter is used as LLM provider.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# .env dosyası varsa yükle
load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}
_RESERVED_DISCOVERED_DATABASES = {"postgres"}


class AppConfig(BaseSettings):
    """Application configuration using Pydantic v2"""
    # ---------------------------------------------------------- #
    # Flask / genel
    # ---------------------------------------------------------- #
    FLASK_ENV: str = Field("development", env="FLASK_ENV")
    FLASK_DEBUG: bool = Field(True, env="FLASK_DEBUG")

    # ---------------------------------------------------------- #
    # OpenRouter (Tek LLM Provider)
    # ---------------------------------------------------------- #
    OPENROUTER_API_KEY: str = Field("", env="OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = Field("deepseek/deepseek-chat", env="OPENROUTER_MODEL")

    # ---------------------------------------------------------- #
    # LangChain Configuration
    # ---------------------------------------------------------- #
    LANGCHAIN_TRACING_V2: bool = Field(False, env="LANGCHAIN_TRACING_V2")
    LANGCHAIN_API_KEY: str = Field("", env="LANGCHAIN_API_KEY")

    # ---------------------------------------------------------- #
    # Database
    # ---------------------------------------------------------- #
    DEFAULT_DB_URI: str = Field(
        "sqlite:///langchain_agent.db",
        env="DEFAULT_DB_URI"
    )
    DATABASE_OPTIONS: str = Field("", env="DATABASE_OPTIONS")
    SAMPLE_DATABASES: str = Field("", env="SAMPLE_DATABASES")
    TRUST_PROXY_HEADERS: bool = Field(False, env="TRUST_PROXY_HEADERS")

    # ---------------------------------------------------------- #
    # Vector storage
    # ---------------------------------------------------------- #
    VECTOR_STORE_PATH: str = Field(
        str(ROOT_DIR / "storage" / "vectors"),
        env="VECTOR_STORE_PATH"
    )

    # ---------------------------------------------------------- #
    # Chart configuration
    # ---------------------------------------------------------- #
    CHART_WIDTH: int = Field(800, env="CHART_WIDTH")
    CHART_HEIGHT: int = Field(400, env="CHART_HEIGHT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_config() -> AppConfig:
    """Get cached configuration instance"""
    return AppConfig()


def _parse_csv(raw: str | None) -> list[str]:
    items: list[str] = []
    for part in (raw or "").split(","):
        value = part.strip()
        if value and value not in items:
            items.append(value)
    return items


def _display_database_name(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists() or os.getenv("RUNNING_IN_DOCKER") == "1"


def _validate_manual_db_uri(db_uri: str) -> str:
    try:
        url = make_url(db_uri)
    except ArgumentError as exc:
        raise ValueError(f"Invalid database URI: {exc}") from exc

    host = (url.host or "").strip("[]").lower()
    if _running_in_docker() and host in _LOCAL_DB_HOSTS:
        raise ValueError("Database URI uses localhost inside Docker. Use the database dropdown or the Docker hostname 'db'.")

    return db_uri


def _discover_database_names_from_server() -> list[str]:
    default_db_uri = (get_config().DEFAULT_DB_URI or "").strip()
    if not default_db_uri:
        return []

    try:
        url = make_url(default_db_uri)
    except ArgumentError:
        return []

    if not url.drivername.startswith("postgresql"):
        return []

    try:
        engine = sa.create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT datname
                    FROM pg_database
                    WHERE datistemplate = false
                      AND datallowconn = true
                    ORDER BY CASE WHEN datname = current_database() THEN 0 ELSE 1 END, datname
                    """
                )
            ).scalars().all()
        return [str(row).strip() for row in rows if str(row).strip()]
    except Exception:
        return []


def get_default_database_name() -> str | None:
    default_db_uri = (get_config().DEFAULT_DB_URI or "").strip()
    if not default_db_uri:
        return None
    try:
        return make_url(default_db_uri).database or None
    except ArgumentError:
        return None


def get_database_catalog() -> list[dict[str, str]]:
    config = get_config()
    configured = _parse_csv(config.DATABASE_OPTIONS or config.SAMPLE_DATABASES or os.getenv("SAMPLE_DATABASES"))
    default_name = get_default_database_name()
    discovered = _discover_database_names_from_server()
    names: list[str] = []

    for name in configured:
        if name not in names:
            names.append(name)

    for name in discovered:
        if name in names:
            continue
        if name in _RESERVED_DISCOVERED_DATABASES and name not in configured and name != default_name:
            continue
        names.append(name)

    if default_name and default_name not in names:
        names.insert(0, default_name)
    return [{"name": name, "label": _display_database_name(name)} for name in names]


def build_db_uri_for_database(database: str) -> str:
    target = (database or "").strip()
    if not target:
        raise ValueError("Database name is required")

    allowed = {entry["name"] for entry in get_database_catalog()}
    if allowed and target not in allowed:
        raise ValueError(f"Unknown database selection: {target}")

    default_db_uri = (get_config().DEFAULT_DB_URI or "").strip()
    if not default_db_uri:
        raise ValueError("DEFAULT_DB_URI is not configured")

    try:
        base_url = make_url(default_db_uri)
    except ArgumentError as exc:
        raise ValueError(f"DEFAULT_DB_URI is invalid: {exc}") from exc

    if not base_url.database:
        raise ValueError("DEFAULT_DB_URI must include a database name")

    return base_url.set(database=target).render_as_string(hide_password=False)


def resolve_db_uri(db_uri: str | None, database: str | None = None) -> str:
    """Resolve request DB URI from manual input, selected database, or default config."""
    selected_database = (database or "").strip()
    if selected_database:
        return build_db_uri_for_database(selected_database)

    candidate = (db_uri or "").strip()
    if candidate:
        return _validate_manual_db_uri(candidate)

    default_db_uri = (get_config().DEFAULT_DB_URI or "").strip()
    if default_db_uri:
        return default_db_uri

    raise ValueError("Database URI not provided and DEFAULT_DB_URI is empty")


def has_default_db_uri() -> bool:
    """Return whether the server has a usable default DB URI configured."""
    return bool((get_config().DEFAULT_DB_URI or "").strip())
