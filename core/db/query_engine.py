"""core.db.query_engine
~~~~~~~~~~~~~~~~~~~~~~~

LangChain tabanlı tam yetenekli bir SQL ajanı.

Bu sürüm, LangChain'in ``SQLDatabaseToolkit`` ve ``create_sql_agent``
yardımıyla veritabanıyla etkileşen bir ajan yaratır. Ajan gerekli
olduğunda tablolari listeler, şemayı sorar ve sorguyu çalıştırır.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Callable, Optional

import os
import sqlalchemy as sa
from langchain_openai import ChatOpenAI
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.utilities.sql_database import truncate_word
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import LLMResult
from langchain.schema.agent import AgentAction, AgentFinish

logger = logging.getLogger(__name__)


class ProgressCallbackHandler(BaseCallbackHandler):
    """Custom callback handler to track LangChain agent progress."""
    
    def __init__(self, progress_callback: Callable[[str, str, int], None]):
        self.progress_callback = progress_callback
        self.current_step = 0
        self.total_steps = 6  # Estimated total steps
        
    def on_llm_start(self, serialized: Dict[str, Any], prompts: list[str], **kwargs) -> None:
        """Called when LLM starts generating."""
        self.current_step += 1
        progress = min(30 + (self.current_step * 10), 70)
        self.progress_callback("llm_thinking", "AI is analyzing your question...", progress)
        
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Called when LLM finishes generating."""
        self.current_step += 1
        progress = min(40 + (self.current_step * 8), 75)
        self.progress_callback("llm_response", "AI has generated a response...", progress)
        
    def on_agent_action(self, action: AgentAction, **kwargs) -> None:
        """Called when agent is about to execute an action."""
        tool_name = action.tool
        self.current_step += 1
        
        if "sql_db_list_tables" in tool_name.lower():
            progress = 45
            self.progress_callback("db_schema", "Exploring database schema...", progress)
        elif "sql_db_schema" in tool_name.lower():
            progress = 55
            self.progress_callback("table_schema", "Analyzing table structure...", progress)
        elif "sql_db_query" in tool_name.lower():
            progress = 70
            self.progress_callback("sql_execution", "Executing SQL query...", progress)
        else:
            progress = min(50 + (self.current_step * 5), 80)
            self.progress_callback("agent_action", f"Executing: {tool_name}", progress)
            
    def on_agent_finish(self, finish: AgentFinish, **kwargs) -> None:
        """Called when agent finishes."""
        self.progress_callback("agent_complete", "Agent execution completed!", 90)


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
        # Pass handle_parsing_errors=True so that the agent can retry when
        # the LLM returns malformed output instead of raising an exception.
        self.agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            verbose=False,
            agent_executor_kwargs={"handle_parsing_errors": True},
        )

        logger.info(f"Using OpenRouter with model: {llm_model}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str, progress_callback: Optional[Callable[[str, str, int], None]] = None) -> Dict[str, Any]:
        """Doğal dil sorusunu LangChain SQL ajanına ilet."""
        
        # Setup progress callback if provided
        callbacks = []
        if progress_callback:
            callbacks.append(ProgressCallbackHandler(progress_callback))

        result = self.agent.invoke({"input": nl_query}, config={"callbacks": callbacks})
        answer = result.get("output", "") if isinstance(result, dict) else str(result)

        rows = getattr(self.db, "last_result", [])

        return {
            "answer": answer,
            "sql": getattr(self.db, "last_query", ""),
            "data": rows,
            "rowcount": len(rows),
        }

