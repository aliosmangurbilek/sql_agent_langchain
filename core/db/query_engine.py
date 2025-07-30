"""core.db.query_engine
~~~~~~~~~~~~~~~~~~~~~~~

LangChain tabanlı tam yetenekli bir SQL ajanı.

Bu sürüm, LangChain'in ``SQLDatabaseToolkit`` ve ``create_sql_agent``
yardımıyla veritabanıyla etkileşen bir ajan yaratır. Ajan gerekli
olduğunda tablolari listeler, şemayı sorar ve sorguyu çalıştırır.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import os
import sqlalchemy as sa
from langchain_openai import ChatOpenAI
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.utilities.sql_database import truncate_word
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent

logger = logging.getLogger(__name__)


class LoggingSQLDatabase(SQLDatabase):
    """SQLDatabase genişletmesi; son çalıştırılan sorguyu saklar."""

    def run(
        self,
        command: sa.sql.Executable | str,
        fetch: str = "all",
        include_columns: bool = False,
        *,
        parameters: Dict[str, Any] | None = None,
        execution_options: Dict[str, Any] | None = None,
    ) -> sa.engine.Result | str | list[Dict[str, Any]]:
        self.last_query = str(command)
        result = self._execute(
            command,
            fetch,
            parameters=parameters,
            execution_options=execution_options,
        )

        if fetch == "cursor":
            # nothing meaningful to store for charting
            self.last_result = []
            return result

        res = [
            {
                column: truncate_word(value, length=self._max_string_length)
                for column, value in r.items()
            }
            for r in result
        ]

        # store the processed rows for later retrieval
        self.last_result = res

        if not include_columns:
            res = [tuple(row.values()) for row in res]

        if not res:
            return ""
        else:
            return str(res)


class QueryEngine:
    """
    Tek veritabanı + tek LLM modeli için sorgu motoru.

    Parameters
    ----------
    db_uri : str
        SQLAlchemy tarafından desteklenen bir bağlantı URI'si
        (postgresql://, mysql://, sqlite:/// vs.).
    llm_model : str, optional
        OpenRouter üzerinden çağrılacak modelin adı.
    """

    def __init__(
        self,
        db_uri: str,
        llm_model: str = "deepseek/deepseek-chat",
    ) -> None:
        self.engine = sa.create_engine(db_uri)

        # OpenRouter için ChatOpenAI yapılandırması
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")

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

        self.db = LoggingSQLDatabase(self.engine)
        toolkit = SQLDatabaseToolkit(db=self.db, llm=self.llm)
        self.agent = create_sql_agent(llm=self.llm, toolkit=toolkit, verbose=False)

        logger.info(f"Using OpenRouter with model: {llm_model}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str) -> Dict[str, Any]:
        """Doğal dil sorusunu LangChain SQL ajanına ilet."""

        result = self.agent.invoke({"input": nl_query})
        answer = result.get("output", "") if isinstance(result, dict) else str(result)

        rows = getattr(self.db, "last_result", [])

        return {
            "answer": answer,
            "sql": getattr(self.db, "last_query", ""),
            "data": rows,
            "rowcount": len(rows),
        }

