"""
flask_app.config
~~~~~~~    # ---------------------------------------------------------- #
    # Flask / genel
    # ---------------------------------------------------------- #
    FLASK_ENV: str = Field("development", env="FLASK_ENV")
    FLASK_DEBUG: bool = Field(True, env="FLASK_DEBUG")

    # ---------------------------------------------------------- #
    # OpenRouter (Tek LLM Provider)
    # ---------------------------------------------------------- #
    OPENROUTER_API_KEY: str = Field("", env="OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = Field("deepseek/deepseek-chat", env="OPENROUTER_MODEL")î yapılandırma katmanı.
• .env (veya gerçek ortam değişkenleri) okunur
• Pydantic BaseSettings → type-safe erişim
• create_app() içinde   app.config.from_object(Settings())
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# .env dosyası varsa yükle
load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent


class AppConfig(BaseSettings):
    """Application configuration using Pydantic v2"""
    # ---------------------------------------------------------- #
    # Flask / genel
    # ---------------------------------------------------------- #
    FLASK_ENV: str = Field("development", env="FLASK_ENV")
    FLASK_DEBUG: bool = Field(True, env="FLASK_DEBUG")

    # ---------------------------------------------------------- #
    # OpenAI
    # ---------------------------------------------------------- #
    OPENAI_API_KEY: str = Field("", env="OPENAI_API_KEY")

    # ---------------------------------------------------------- #
    # OpenRouter
    # ---------------------------------------------------------- #
    OPENROUTER_API_KEY: str = Field("", env="OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = Field("openrouter/deepseek-chat-v3-0324:free", env="OPENROUTER_MODEL")

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

