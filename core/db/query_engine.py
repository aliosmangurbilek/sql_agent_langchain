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
from core.db.verify_sql import verify_sql  # SQL guardrail
from core.db.embedder import DBEmbedder  # Table selection via embeddings

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
        # Keep a copy of incoming SQL (string form)
        raw_sql = str(command)

        # Verify and possibly rewrite SQL (add LIMIT, block mutations, etc.)
        try:
            safe_sql = verify_sql(raw_sql, engine=self._engine, auto_limit=True, cost_guard=False)
            command = safe_sql
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SQL verification failed: {e}")
            # Re-raise to block execution of unsafe SQL
            raise

        self.last_query = str(command)
        result = self._execute(
            command,
            fetch,
            parameters=parameters,
            execution_options=execution_options,
        )

        # Convert to JSON-serialisable rows list
        if fetch == "cursor":
            self.last_result = []  # not serialisable; keep empty
            return result

        rows_as_dicts = [
            {
                column: truncate_word(value, length=self._max_string_length)
                for column, value in r.items()
            }
            for r in result
        ]

        # Store JSON-safe result for API usage
        self.last_result = rows_as_dicts

        # Preserve original return contract of SQLDatabase.run
        if not include_columns:
            res = [tuple(row.values()) for row in rows_as_dicts]
        else:
            res = rows_as_dicts

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

        # Embedding-based table selector
        self.embedder = DBEmbedder(self.engine)

        self.db = LoggingSQLDatabase(self.engine)
        toolkit = SQLDatabaseToolkit(db=self.db, llm=self.llm)
        self.agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            verbose=True,
            agent_executor_kwargs={
                "handle_parsing_errors": True
            },
        )

        logger.info(f"Using OpenRouter with model: {llm_model}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str) -> Dict[str, Any]:
        """Doğal dil sorusunu LangChain SQL ajanına ilet.
        Embedding ile en alakalı tabloları seçip ajanı sınırlı şema ile koşturur.
        """
        # 1) Relevant tables via embeddings (best-effort)
        db_for_run: LoggingSQLDatabase
        try:
            hits = self.embedder.similarity_search(nl_query, k=6)
            # Log embedding hits for observability
            try:
                hit_summ = [
                    f"{(h.get('schema') + '.' if h.get('schema') else '')}{h.get('table')} (score={h.get('score'):.3f})"
                    for h in hits if h.get('table')
                ]
                logger.info("Embedding hits: %s", ", ".join(hit_summ))
            except Exception:
                logger.debug("Could not log embedding hits; continuing.")
            tables = []
            for h in hits:
                t = h.get("table")
                if not t:
                    continue
                s = (h.get("schema") or "").strip()
                qualified = f"{s}.{t}" if s else t
                if qualified not in tables:
                    tables.append(qualified)
            if tables:
                logger.info("Restricting agent to tables: %s", ", ".join(tables))
                db_for_run = LoggingSQLDatabase(self.engine, include_tables=tables)
            else:
                db_for_run = self.db
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Embedding-based table selection failed, falling back. Reason: {e}")
            db_for_run = self.db

        # 2) Build a transient agent bound to the selected DB
        toolkit = SQLDatabaseToolkit(db=db_for_run, llm=self.llm)
        agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            verbose=True,
            agent_executor_kwargs={
                "handle_parsing_errors": True
            },
        )

        # 3) Invoke and return
        result = agent.invoke({"input": nl_query})
        answer = result.get("output", "") if isinstance(result, dict) else str(result)

        return {
            "answer": answer,
            "sql": getattr(db_for_run, "last_query", ""),
            "data": getattr(db_for_run, "last_result", []),
        }

