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

from core.db.embedder import DBEmbedder
from core.db.verify_sql import verify_sql

logger = logging.getLogger(__name__)


class ProgressCallbackHandler(BaseCallbackHandler):
    """Custom callback handler to track LangChain agent progress."""
    
    def __init__(self, progress_callback: Callable[[str, str, int], None]):
        self.progress_callback = progress_callback
        self.current_step = 0
        self.total_steps = 6  # Estimated total steps
        
    def on_llm_start(self, serialized: Dict[str, Any], prompts: list[str], **kwargs) -> None:
        """Called when LLM starts generating."""
        # serialized, prompts, kwargs intentionally unused - required by LangChain interface
        self.current_step += 1
        progress = min(30 + (self.current_step * 10), 70)
        self.progress_callback("llm_thinking", "AI is analyzing your question...", progress)
        
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Called when LLM finishes generating."""
        # response, kwargs intentionally unused - required by LangChain interface
        self.current_step += 1
        progress = min(40 + (self.current_step * 8), 75)
        self.progress_callback("llm_response", "AI has generated a response...", progress)
        
    def on_agent_action(self, action: AgentAction, **kwargs) -> None:
        """Called when agent is about to execute an action."""
        # kwargs intentionally unused - required by LangChain interface
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
        # finish, kwargs intentionally unused - required by LangChain interface  
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
        raw_sql = str(command)
        safe_sql = verify_sql(raw_sql, engine=self._engine, auto_limit=True)
        self.last_query = safe_sql
        result = self._execute(
            sa.text(safe_sql),
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
        self.db_uri = db_uri
        self.llm_model = llm_model
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
            max_tokens=4000,
            timeout=30,
            default_headers={
                "HTTP-Referer": "https://github.com/openrouter-chat/openrouter-langchain",
                "X-Title": "LangChain SQL Agent"
            }
        )

        # Her veritabanı için izole bir DBEmbedder oluştur
        # URI'den veritabanı adını çıkararak doğru vektör deposunu hedeflemesini sağla
        db_name = sa.engine.url.make_url(db_uri).database
        self.embedder = DBEmbedder(engine=self.engine, db_name=db_name)
        self.embedder.ensure_store()

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

        # Anlamsal arama ile ilgili tabloları bul
        hits = self.embedder.similarity_search(nl_query, k=5) # Daha fazla sonuç alıp filtreleyelim
        qualified_table_names = [hit["table"] for hit in hits if hit.get("table")]

        # Sistem şemalarını (örn: information_schema) filtrele
        user_tables = [
            t for t in qualified_table_names
            if t and not t.startswith("information_schema.")
        ]

        logger.info(f"🔍 Embedder'dan gelen tablolar: {qualified_table_names}")
        logger.info(f"📋 Sorgu için ilgili tablolar bulundu: {user_tables}")
        logger.info(f"🔗 Database URI: {self.db_uri}")
        
        # Debug: Veritabanında gerçekte hangi tablolar var?
        try:
            with self.engine.connect() as conn:
                # Mevcut schema'yı kontrol et
                current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
                logger.info(f"📍 Current schema: {current_schema}")
                
                # Tüm tabloları listele
                all_tables = conn.execute(sa.text("""
                    SELECT table_schema, table_name 
                    FROM information_schema.tables 
                    WHERE table_type = 'BASE TABLE'
                    AND table_schema NOT IN ('information_schema', 'pg_catalog')
                    ORDER BY table_schema, table_name
                """)).fetchall()
                
                logger.info(f"🗄️ Veritabanındaki tüm tablolar: {[(t[0], t[1]) for t in all_tables]}")
                
        except Exception as e:
            logger.error(f"❌ Debug sorgusu başarısız: {e}")

        schema_name = None

        if user_tables:
            # Şema ve tablo adlarını ayır
            # Not: Bu basit mantık, tüm tabloların aynı şemada olduğunu varsayar.
            schemas = {t.split('.')[0] for t in user_tables if '.' in t}
            if schemas:
                schema_name = list(schemas)[0]
                # Schema belirtildiğinde include_tables kullanmıyoruz
                # Çünkü schema içindeki tablolar otomatik olarak dahil ediliyor
                logger.info(f"✅ Schema tespit edildi: {schema_name}, tüm tablolar dahil edilecek")
            else:
                # Schema yok, sadece tablo isimleri var - bunları include_tables olarak kullan
                logger.info(f"⚠️ Schema yok, sadece tablolar: {user_tables}")

        # Sadece ilgili tabloları içeren bir SQLDatabase nesnesi oluştur
        if schema_name:
            # Schema var - include_tables kullanmadan schema'daki tüm tabloları al
            db = LoggingSQLDatabase.from_uri(
                self.db_uri,
                schema=schema_name,
                sample_rows_in_table_info=3,
            )
        elif user_tables:
            # Schema yok ama tablo listesi var - include_tables kullan
            db = LoggingSQLDatabase.from_uri(
                self.db_uri,
                include_tables=user_tables,
                sample_rows_in_table_info=3,
            )
        else:
            # Ne schema ne de tablo listesi - tüm tabloları al
            db = LoggingSQLDatabase.from_uri(
                self.db_uri,
                sample_rows_in_table_info=3,
            )

        toolkit = SQLDatabaseToolkit(db=db, llm=self.llm)
        agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            verbose=False,
            agent_executor_kwargs={"handle_parsing_errors": True},
        )

        result = agent.invoke({"input": nl_query}, config={"callbacks": callbacks})
        answer = result.get("output", "") if isinstance(result, dict) else str(result)

        generated_sql = getattr(db, "last_query", "")
        safe_sql = verify_sql(generated_sql, engine=self.engine)

        rows = getattr(db, "last_result", [])

        return {
            "answer": answer,
            "sql": safe_sql,
            "data": rows,
            "rowcount": len(rows),
        }
