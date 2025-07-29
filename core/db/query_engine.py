"""
core.db.query_engine
~~~~~~~~~~~~~~~~~~~~

• Kullanıcı cümlesini alır, şemadan k-adet ilgili tablo/kolonu DBEmbedder ile bulur.
• Küçük şema kesitini LLM'e prompt eder → SQL sorgusu üretir.
• verify_sql güvenliğinden geçirir, veritabanında yürütür, sonucu JSON olarak döndürür.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Dict, List

import os
import sqlalchemy as sa
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

from .embedder import DBEmbedder
from .verify_sql import verify_sql

# Ensure environment variables are loaded
load_dotenv()

logger = logging.getLogger(__name__)


class QueryEngine:
    """
    Tek veritabanı + tek LLM modeli için sorgu motoru.

    Parameters
    ----------
    db_uri : str
        SQLAlchemy tarafından desteklenen bir bağlantı URI'si
        (postgresql://, mysql://, sqlite:/// vs.).
    llm_model : str, optional
        OpenAI modeli (varsayılan: "gpt-4o-mini").
    top_k : int, optional
        Embedding aramasında kaç tablo/kolon kesiti alınacağı.
    """

    def __init__(
        self,
        db_uri: str,
        llm_model: str = "deepseek/deepseek-chat",
        top_k: int = 6,
    ) -> None:
        self.engine = sa.create_engine(db_uri)
        self.embedder = DBEmbedder(self.engine)  # otomatik embedding + metadata
        
        # Sadece OpenRouter kullan
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        # OpenRouter için ChatOpenAI yapılandırması
        self.llm = ChatOpenAI(
            api_key=openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model=llm_model,
            temperature=0.0,
            default_headers={
                "HTTP-Referer": "https://github.com/openrouter-chat/openrouter-langchain",
                "X-Title": "LangChain SQL Agent"
            }
        )
        logger.info(f"Using OpenRouter with model: {llm_model}")
        self.top_k = top_k

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str) -> Dict[str, Any]:
        """
        Doğal dil sorgusunu al, SQL'e çevir, çalıştır, sonucu döndür.

        Returns
        -------
        dict
            {"sql": <str>, "data": <list[dict]>, "rowcount": <int>}
        """
        relevant = self.embedder.similarity_search(nl_query, k=self.top_k)
        schema_snippet = "\n".join(hit["text"] for hit in relevant)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an expert PostgreSQL assistant. "
                    "Write only valid SELECT statements and always add LIMIT 1000 if not present.",
                ),
                (
                    "user",
                    (
                        f"Database snippet:\n{schema_snippet}\n\n"
                        f"Write a SQL query (PostgreSQL syntax) "
                        f"for the following request:\n\"{nl_query}\""
                    ),
                ),
            ]
        )

        sql = self._generate_sql(prompt)
        logger.debug("Generated SQL: %s", sql)

        verify_sql(sql)  # güvenlik kontrolleri

        with self.engine.connect() as conn:
            rows = conn.execute(sa.text(sql)).fetchall()

        return {
            "sql": sql,
            "data": [dict(r) for r in rows],
            "rowcount": len(rows),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _generate_sql(self, prompt: ChatPromptTemplate) -> str:
        """LLM'den tek satır SQL döndürür, arakod veya yorum siler."""
        # Deprecated __call__ yerine invoke kullan
        response = self.llm.invoke(prompt.format_messages())
        # ChatModel geri dönüşü AIMessage; content alanındaki metin
        sql_text = response.content.strip()
        # ```sql ... ``` bloklarını temizle
        if sql_text.startswith("```"):
            sql_text = sql_text.split("```")[1] if "```" in sql_text else sql_text
        return sql_text.strip(" ;\n")
