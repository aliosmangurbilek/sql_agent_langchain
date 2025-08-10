"""core.db.query_engine
~~~~~~~~~~~~~~~~~~~~~~~

LangChain tabanlı tam yetenekli bir SQL ajanı.

Bu sürüm, LangChain'in ``SQLDatabaseToolkit`` ve ``create_sql_agent``
yardımıyla veritabanıyla etkileşen bir ajan yaratır. Ajan gerekli
olduğunda tablolari listeler, şemayı sorar ve sorguyu çalıştırır.
"""

from __future__ import annotations

import logging
import warnings
from sqlalchemy.exc import SAWarning
from typing import Any, Dict, Callable, Optional

# Silence pgvector reflection warning in SQLAlchemy
warnings.filterwarnings(
    "ignore",
    category=SAWarning,
    message=r"Did not recognize type 'vector' of column 'embedding'"
)

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
from core.db.database_manager import database_manager

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
        db_name = sa.engine.url.make_url(db_uri).database or "default"
        self.embedder = DBEmbedder(engine=self.engine, db_name=db_name)
        self.embedder.ensure_store()

        logger.info(f"Using OpenRouter with model: {llm_model}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str, progress_callback: Optional[Callable[[str, str, int], None]] = None, debug: bool = True) -> Dict[str, Any]:
        """Doğal dil sorusunu LangChain SQL ajanına ilet."""

        debug_info: Dict[str, Any] = {"nl_query": nl_query}
        # Setup progress callback if provided
        callbacks = []
        if progress_callback:
            callbacks.append(ProgressCallbackHandler(progress_callback))

        # Anlamsal arama ile ilgili tabloları bul - önce embeddings var mı kontrol et
        try:
            # Database manager ile tablo araması yap
            hits = database_manager.search_tables(self.db_uri, nl_query, k=5)
            qualified_table_names = [hit["table"] for hit in hits if hit.get("table")]
            
            # Sistem şemalarını (örn: information_schema) filtrele
            user_tables = [
                t for t in qualified_table_names
                if t and not t.startswith("information_schema.")
            ]

            logger.info(f"🔍 Database manager'dan gelen tablolar: {qualified_table_names}")
            debug_info["embedder_hits"] = qualified_table_names
            logger.info(f"📋 Sorgu için ilgili tablolar bulundu: {user_tables}")
            debug_info["user_tables"] = user_tables
            
            # If no tables found, try to ensure embeddings exist
            if not user_tables:
                logger.warning("🔄 No tables found, attempting to ensure embeddings...")
                embedding_result = database_manager.ensure_embeddings(self.db_uri, force_rebuild=False)
                logger.info(f"Embedding result: {embedding_result}")
                
                if embedding_result.get('status') == 'success':
                    # Try searching again
                    hits = database_manager.search_tables(self.db_uri, nl_query, k=5)
                    qualified_table_names = [hit["table"] for hit in hits if hit.get("table")]
                    user_tables = [
                        t for t in qualified_table_names
                        if t and not t.startswith("information_schema.")
                    ]
                    logger.info(f"🔄 After ensuring embeddings - tablolar: {user_tables}")
                
                # Final fallback - get all tables
                if not user_tables:
                    logger.warning("🔄 Still no tables found, using fallback table list...")
                    fallback_tables = database_manager.get_tables_fallback(self.db_uri)
                    user_tables = fallback_tables[:10]  # Limit to first 10 tables
                    logger.info(f"� Fallback tablolar: {user_tables}")
                    debug_info["fallback_used"] = True
                    
        except Exception as search_error:
            logger.error(f"❌ Table search failed: {search_error}")
            # Emergency fallback - try direct database query
            try:
                user_tables = database_manager.get_tables_fallback(self.db_uri)[:10]
                logger.info(f"🆘 Emergency fallback tablolar: {user_tables}")
                debug_info["emergency_fallback_used"] = True
            except Exception as fallback_error:
                logger.error(f"❌ Even fallback failed: {fallback_error}")
                user_tables = []
        
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
                debug_info["all_tables"] = [(t[0], t[1]) for t in all_tables]

        except Exception as e:
            logger.error(f"❌ Debug sorgusu başarısız: {e}")

        # Embedding ile bulunan tabloları temizle ve hazırla
        final_tables = []
        if user_tables:
            # Schema prefix'lerini kaldır - sadece tablo isimlerini kullan
            for table in user_tables:
                if '.' in table:
                    # "schema.table" formatında ise sadece table kısmını al
                    table_name = table.split('.')[-1]
                else:
                    # Zaten sadece tablo ismi
                    table_name = table
                final_tables.append(table_name)
            
            # Duplicate'ları kaldır
            final_tables = list(set(final_tables))
            logger.info(f"🎯 Final tables for agent (embedding based): {final_tables}")
            debug_info["final_tables"] = final_tables

        # Sadece embedding ile bulunan tabloları kullan - HER ZAMAN include_tables ile
        if final_tables:
            debug_info["db_from_uri"] = {"schema": None, "include_tables": final_tables}
            logger.info(f"🔧 Creating SQLDatabase with ONLY embedding-found tables: {final_tables}")
            db = LoggingSQLDatabase.from_uri(
                self.db_uri,
                include_tables=final_tables,
                sample_rows_in_table_info=3,
            )
        else:
            # Hiç tablo bulunamadı - bu durumda hata döndür
            logger.error("❌ No tables found by embedding search!")
            debug_info["db_from_uri"] = {"error": "no_tables_found"}
            return {
                "answer": "No relevant tables were found for your question. The database might not contain the information you're looking for, or you may need to rephrase your question.",
                "sql": "",
                "data": [],
                "rowcount": 0,
                "debug": debug_info,
            }

        # Debug: Check what tables are actually available to the agent
        try:
            available_tables = db.get_usable_table_names()
            logger.info(f"📋 SQLDatabase usable tables: {available_tables}")
            debug_info["usable_tables"] = available_tables
            
            # KRITIK: Embedding ile bulunan tablolar agent'a geçti mi?
            if final_tables:
                matched_tables = [t for t in available_tables if t in final_tables]
                logger.info(f"🎯 Embedding tables that made it to agent: {matched_tables}")
                logger.info(f"🔍 Expected: {final_tables}")
                debug_info["embedding_tables_in_agent"] = matched_tables
                debug_info["expected_embedding_tables"] = final_tables
                
                if len(matched_tables) != len(final_tables):
                    logger.warning(f"⚠️ Mismatch! Expected {len(final_tables)} tables, agent has {len(matched_tables)}")
            
            if not available_tables:
                logger.error("❌ No usable tables found in SQLDatabase!")
                return {
                    "answer": "No usable tables found in the database. Please check your database connection and permissions.",
                    "sql": "",
                    "data": [],
                    "rowcount": 0,
                    "debug": debug_info,
                }
            
            # Get table info for debugging
            table_info = db.get_table_info()
            logger.info(f"📝 Table info (first 500 chars): {table_info[:500]}...")
            debug_info["table_info_sample"] = table_info[:500]
            
        except Exception as table_error:
            logger.error(f"❌ Failed to get table information: {table_error}")
            debug_info["table_error"] = str(table_error)

        logger.info(f"🤖 Creating SQL agent with {len(available_tables) if 'available_tables' in locals() else 'unknown'} tables")
        toolkit = SQLDatabaseToolkit(db=db, llm=self.llm)
        agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            verbose=True,  # Enable verbose to see what the agent is doing
            agent_executor_kwargs={"handle_parsing_errors": True},
        )

        logger.info(f"🚀 Invoking agent with query: '{nl_query}'")
        result = agent.invoke({"input": nl_query}, config={"callbacks": callbacks})
        answer = result.get("output", "") if isinstance(result, dict) else str(result)

        generated_sql = getattr(db, "last_query", "")
        logger.info(f"🔍 Agent generated SQL: '{generated_sql}'")
        debug_info["generated_sql"] = generated_sql
        debug_info["agent_output"] = answer

        # Handle empty SQL case with enhanced debugging
        if not generated_sql or not generated_sql.strip():
            logger.warning("⚠️ Agent produced empty SQL - investigating...")
            
            # Check if agent found tables but couldn't generate SQL
            if available_tables:
                logger.warning(f"🔍 Agent had access to {len(available_tables)} tables: {available_tables}")
                logger.warning(f"🤖 Agent response: '{answer}'")
                
                # Check if the answer suggests the query was successful
                if ":" in answer and any(keyword in answer.lower() for keyword in ["top", "results", "found", "data"]):
                    logger.info("✅ Agent seems to have found results despite empty SQL - this might be a logging issue")
                    # Try to extract any SQL-like content from the verbose output or use a fallback
                    rows = getattr(db, "last_result", [])
                    if rows:
                        logger.info(f"✅ Found {len(rows)} rows in last_result, query was successful!")
                        result_payload = {
                            "answer": answer,
                            "sql": "Query executed successfully (SQL not captured due to logging issue)",
                            "data": rows,
                            "rowcount": len(rows),
                        }
                        if debug:
                            result_payload["debug"] = debug_info
                        return result_payload
                
                # Check if these were the embedding-selected tables
                if 'final_tables' in locals() and final_tables:
                    logger.warning(f"🎯 These were specifically selected by embedding search: {final_tables}")
                    error_message = f"The AI agent had access to {len(available_tables)} relevant tables ({', '.join(available_tables[:3])}) found by similarity search, but couldn't generate a proper SQL query. Agent response: '{answer}'. Try rephrasing your question or being more specific."
                else:
                    error_message = f"The AI agent had access to {len(available_tables)} tables but couldn't generate SQL. This might be due to question complexity or table structure issues."
                
                debug_info["empty_sql_analysis"] = {
                    "available_tables": available_tables,
                    "embedding_selected": final_tables if 'final_tables' in locals() else [],
                    "agent_response": answer
                }
            else:
                error_message = "No tables were available to the agent."
                debug_info["empty_sql_analysis"] = {"reason": "no_tables_available"}
            
            debug_info["empty_sql_reason"] = "Agent had tables but produced no SQL"
            debug_info["available_tables_count"] = len(available_tables) if available_tables else 0
            
            return {
                "answer": error_message,
                "sql": "",
                "data": [],
                "rowcount": 0,
                "debug": debug_info,
            }

        try:
            safe_sql = verify_sql(generated_sql, engine=self.engine)
        except Exception as verify_error:
            logger.warning(f"⚠️ SQL verification failed: {verify_error}")
            logger.warning(f"🔍 Problematic SQL: '{generated_sql}'")
            # For debugging, allow the query but with a limit
            if "SELECT" in generated_sql.upper():
                safe_sql = generated_sql if "LIMIT" in generated_sql.upper() else f"{generated_sql.rstrip().rstrip(';')} LIMIT 100"
                logger.info("🔧 Allowing SELECT query with limit for debugging")
            else:
                raise verify_error

        rows = getattr(db, "last_result", [])

        result_payload = {
            "answer": answer,
            "sql": safe_sql,
            "data": rows,
            "rowcount": len(rows),
        }
        if debug:
            result_payload["debug"] = debug_info
        return result_payload