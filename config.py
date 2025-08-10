from __future__ import annotations

from functools import lru_cache
import os

# Try Pydantic v2 first, then v1; fall back to a no-deps shim
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
    _HAS_PYDANTIC = True
except Exception:  # pragma: no cover - fallback if pydantic_settings missing
    try:
        from pydantic import BaseSettings, Field  # type: ignore
        _HAS_PYDANTIC = True
    except Exception:  # pragma: no cover
        _HAS_PYDANTIC = False

if _HAS_PYDANTIC:
    class AppConfig(BaseSettings):
        """Application configuration (env-driven)."""
        # Flask
        FLASK_ENV: str = Field(default="development", env="FLASK_ENV")
        FLASK_DEBUG: bool = Field(default=True, env="FLASK_DEBUG")
        SECRET_KEY: str = Field(default="dev", env="SECRET_KEY")

        # Databases
        BASE_DATABASE_URL: str = Field(default="", env="BASE_DATABASE_URL")  # e.g., postgresql+asyncpg://user:pw@host/db
        DEFAULT_DB_URI: str = Field(default="", env="DEFAULT_DB_URI")        # e.g., postgresql://user:pw@host/db

        # LLM / OpenRouter
        OPENROUTER_API_KEY: str = Field(default="", env="OPENROUTER_API_KEY")
        OPENROUTER_MODEL: str = Field(default="deepseek/deepseek-chat", env="OPENROUTER_MODEL")

        # Worker
        WORKER_BASE_URL: str = Field(default="http://localhost:9500", env="WORKER_BASE_URL")

        # Charts
        CHART_WIDTH: int = Field(default=800, env="CHART_WIDTH")
        CHART_HEIGHT: int = Field(default=400, env="CHART_HEIGHT")

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = True
            extra = "allow"
else:
    class AppConfig:  # pragma: no cover - minimal fallback without pydantic
        def __init__(self) -> None:
            self.FLASK_ENV = os.getenv("FLASK_ENV", "development")
            self.FLASK_DEBUG = os.getenv("FLASK_DEBUG", "1") not in {"0", "false", "False"}
            self.SECRET_KEY = os.getenv("SECRET_KEY", "dev")
            self.BASE_DATABASE_URL = os.getenv("BASE_DATABASE_URL", "")
            self.DEFAULT_DB_URI = os.getenv("DEFAULT_DB_URI", "")
            self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
            self.OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")
            self.WORKER_BASE_URL = os.getenv("WORKER_BASE_URL", "http://localhost:9500")
            self.CHART_WIDTH = int(os.getenv("CHART_WIDTH", "800"))
            self.CHART_HEIGHT = int(os.getenv("CHART_HEIGHT", "400"))

@lru_cache()
def get_config() -> AppConfig:
    """Return a cached configuration instance."""
    return AppConfig()