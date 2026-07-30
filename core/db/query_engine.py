""""core.db.query_engine
~~~~~~~~~~~~~~~~~~~~~~~

LangChain tabanlı tam yetenekli bir SQL ajanı.

Bu sürüm, LangChain'in ``SQLDatabaseToolkit`` ve ``create_sql_agent``
yardımıyla veritabanıyla etkileşen bir ajan yaratır. Ajan gerekli
olduğunda tablolari listeler, şemayı sorar ve sorguyu çalıştırır.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

import os
import re
import sqlalchemy as sa
from langchain_openai import ChatOpenAI
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.utilities.sql_database import truncate_word
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from config import get_engine_kwargs
from core.db.verify_sql import verify_sql  # SQL guardrail
from core.db.embedder import DBEmbedder  # Table selection via embeddings

logger = logging.getLogger(__name__)

_VALID_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_schema(s: str | None) -> str | None:
    if not s:
        return None
    return s if _VALID_SCHEMA.match(s) else None


def _hits_to_fqn(hits: List[Dict[str, Any]]) -> tuple[list[str], Set[str]]:
    """Embedder hitlerinden FQN (schema.table) listesi ve şema kümesi üret."""
    fqns: list[str] = []
    schemas: set[str] = set()
    for h in hits:
        t = (h.get("table") or "").strip()
        s = _safe_schema((h.get("schema") or "").strip())
        if not t or t.startswith("langchain_pg_"):
            continue
        q = f"{s}.{t}" if s else t
        if q not in fqns:
            fqns.append(q)
        if s:
            schemas.add(s)
    return fqns, schemas


def _extract_final_answer(text: str) -> str:
    """Best-effort extraction of a Final Answer from a parsing error string."""
    if not text:
        return ""
    matches = list(re.finditer(r"Final Answer:\s*(.*)", text, flags=re.S))
    if not matches:
        return ""
    answer = matches[-1].group(1).strip()
    # Strip langchain troubleshooting footer if present.
    answer = re.split(r"For troubleshooting", answer)[0].strip()
    return answer


def _extract_error_text(err: Exception) -> str:
    """Try to recover raw LLM output from parsing errors, falling back to str(err)."""
    llm_out = getattr(err, "llm_output", None)
    if llm_out:
        return str(llm_out)
    cause = getattr(err, "__cause__", None)
    if cause is not None:
        cause_out = getattr(cause, "llm_output", None)
        if cause_out:
            return str(cause_out)
    return str(err)


def _is_output_parsing_error(err: Exception) -> bool:
    """Return whether an exception chain represents an agent parser failure."""
    current: BaseException | None = err
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if current.__class__.__name__ == "OutputParserException":
            return True
        message = str(current).lower()
        if "output parsing error" in message or "could not parse llm output" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_unhelpful_answer(answer: str) -> bool:
    normalized = answer.strip().lower().rstrip(".")
    return (
        not normalized
        or normalized.startswith("agent stopped due to")
        or normalized
        in {
            "i don't know",
            "i do not know",
            "unable to answer",
            "cannot answer",
        }
    )


def _existing_tables(engine: sa.Engine, schema: str | None) -> set[str]:
    """Return tables + views + materialized views for a schema."""
    insp = sa.inspect(engine)
    existing = set(insp.get_table_names(schema=schema))
    try:
        existing.update(insp.get_view_names(schema=schema))
    except Exception:
        pass
    get_mat = getattr(insp, "get_materialized_view_names", None)
    if callable(get_mat):
        try:
            existing.update(get_mat(schema=schema))
        except Exception:
            pass
    return existing


def _get_fallback_table_info(engine: sa.Engine, schema: str | None) -> str:
    """Describe base tables without querying sample rows or broken views."""
    table_names = [
        name
        for name in sa.inspect(engine).get_table_names(schema=schema)
        if not name.startswith("langchain_pg_")
        and name != DBEmbedder._META_TABLE_NAME
    ]
    schema_db = SQLDatabase(
        engine,
        schema=schema,
        include_tables=table_names or None,
        sample_rows_in_table_info=0,
        view_support=False,
    )
    return schema_db.get_table_info()


def _small_schema_base_tables(
    engine: sa.Engine,
    schema: str | None,
) -> list[str] | None:
    """Return all base tables when the schema is small enough not to restrict."""
    raw_limit = (os.getenv("EMBEDDING_RESTRICTION_MIN_TABLES") or "30").strip()
    try:
        limit = max(0, int(raw_limit))
    except ValueError:
        limit = 30

    tables = [
        name
        for name in sa.inspect(engine).get_table_names(schema=schema)
        if not name.startswith("langchain_pg_")
        and name != DBEmbedder._META_TABLE_NAME
    ]
    return tables if tables and len(tables) <= limit else None


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
        self.engine = sa.create_engine(db_uri, **get_engine_kwargs(db_uri))

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

        # Varsayılan DB (tüm şema için, kısıtlama yok)
        self.db = LoggingSQLDatabase(
            self.engine,
            sample_rows_in_table_info=2,
            view_support=True,
        )

    # Kalıcı agent yaratmıyoruz; her çağrıda seçili tablo/şema ile transient agent kuruyoruz.

        logger.info(f"Using OpenRouter with model: {llm_model}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ask(self, nl_query: str) -> Dict[str, Any]:
        """Doğal dil sorusunu LangChain SQL ajanına ilet.
        Embedding ile en alakalı tabloları seçip ajanı sınırlı şema ile koşturur.
        """
        # 1) Relevant tables via embeddings (best-effort)
        db_for_run: LoggingSQLDatabase = self.db
        try:
            if getattr(self.embedder, 'meta_writable', True):
                hits = self.embedder.similarity_search(nl_query, k=6)
            else:
                logger.info("Read-only meta (embed store not writable); skipping embedding-based table restriction.")
                hits = []

            # Log embedding hits for observability
            try:
                hit_summ = [
                    f"{(h.get('schema') + '.' if h.get('schema') else '')}{h.get('table')} (score={h.get('score'):.3f})"
                    for h in hits if h.get('table')
                ]
                logger.info("Embedding hits: %s", ", ".join(hit_summ))
            except Exception:
                logger.debug("Could not log embedding hits; continuing.")

            # FQN + şema kümesi
            fqns, schemas = _hits_to_fqn(hits)

            if fqns:
                # LangChain SQLDatabase include_tables param'ı şema nitelikli isim (schema.table) değil sadece tablo adı bekler.
                # Bu nedenle önce hit'leri şemaya göre gruplayıp güvenli strateji seçiyoruz.
                schema_table_map: dict[str | None, list[str]] = {}
                for f in fqns:
                    if "." in f:
                        sch, tbl = f.split(".", 1)
                    else:
                        sch, tbl = None, f
                    schema_table_map.setdefault(sch, []).append(tbl)

                if len(schema_table_map) == 1:
                    # Tek şema (veya None): direkt kısıtlı DB oluştur
                    only_schema, tables = next(iter(schema_table_map.items()))
                    base_tables = _small_schema_base_tables(self.engine, only_schema)
                    if base_tables is not None:
                        logger.info(
                            "Small schema detected (%d base tables); skipping embedding restriction.",
                            len(base_tables),
                        )
                        db_for_run = LoggingSQLDatabase(
                            self.engine,
                            schema=only_schema,
                            include_tables=base_tables,
                            sample_rows_in_table_info=2,
                            view_support=False,
                        )
                    else:
                        log_list = [f"{only_schema+'.' if only_schema else ''}{t}" for t in tables]
                        logger.info("Restricting agent to tables (schema-aware): %s", ", ".join(log_list))
                        existing = _existing_tables(self.engine, only_schema)
                        missing = [t for t in tables if t not in existing]
                        if missing:
                            logger.info("Dropping missing tables/views from restriction: %s", ", ".join(missing))
                            tables = [t for t in tables if t in existing]
                        if not tables:
                            logger.info("No matching tables after filtering; using full DB.")
                            db_for_run = self.db
                        else:
                            db_for_run = LoggingSQLDatabase(
                                self.engine,
                                schema=only_schema,  # None ise varsayılan search_path
                                include_tables=tables,
                                sample_rows_in_table_info=2,
                                view_support=True,
                            )
                else:
                    # Çoklu şema senaryosu: SQLDatabase aynı anda birden fazla şemayı include_tables ile daraltamıyor.
                    # Bu durumda fail-open yerine ileride özel filtre için not bırak.
                    logger.info(
                        "Multiple schemas in embedding hits (%s); skipping hard restriction (using full DB).",
                        ", ".join(fqns),
                    )
                    db_for_run = self.db
            else:
                db_for_run = self.db

        except Exception as e:  # noqa: BLE001
            logger.warning(f"Embedding-based table selection failed, falling back. Reason: {e}")
            db_for_run = self.db

        # 2) Build a transient agent bound to the selected DB
        toolkit = SQLDatabaseToolkit(db=db_for_run, llm=self.llm)
        try:
            max_iterations = max(1, int(os.getenv("SQL_AGENT_MAX_ITERATIONS") or "8"))
        except ValueError:
            max_iterations = 8
        agent = create_sql_agent(
            llm=self.llm,
            toolkit=toolkit,
            agent_type=(os.getenv("SQL_AGENT_TYPE") or "tool-calling").strip(),
            verbose=(os.getenv("LANGCHAIN_VERBOSE") or "").strip().lower()
            in {"1", "true", "yes", "on"},
            max_iterations=max_iterations,
            agent_executor_kwargs={"handle_parsing_errors": False},
        )

        # 3) Invoke agent
        # QueryEngine instances are cached, so never let a previous request's
        # tool output satisfy the fallback checks for this request.
        db_for_run.last_query = ""
        db_for_run.last_result = []
        answer = ""
        try:
            result = agent.invoke({"input": nl_query})
            raw_output = result.get("output", "") if isinstance(result, dict) else str(result)
            extracted = _extract_final_answer(raw_output)
            answer = extracted or raw_output
        except Exception as e:  # noqa: BLE001
            err_text = _extract_error_text(e)
            extracted = _extract_final_answer(err_text)
            if extracted:
                logger.warning("Agent output parsing failed; using extracted Final Answer.")
                answer = extracted
            elif _is_output_parsing_error(e):
                logger.warning("Agent returned an invalid or empty response; using SQL-only fallback.")
            else:
                raise

        # 4) Ensure we have SQL + data for downstream charting
        sql_str = getattr(db_for_run, "last_query", "")
        data_rows = getattr(db_for_run, "last_result", [])

        if sql_str and isinstance(data_rows, list) and _is_unhelpful_answer(answer):
            answer = "Query completed successfully."

        if not sql_str or not isinstance(data_rows, list) or len(data_rows) == 0:
            # Fallback: ask LLM to emit only SQL, then verify and execute
            try:
                logger.info("Agent produced no tool output; attempting SQL-only fallback…")
                table_info = _get_fallback_table_info(
                    self.engine,
                    getattr(db_for_run, "_schema", None),
                )
                sql_only_prompt = (
                    f"Return ONLY one valid {db_for_run.dialect} SQL query that answers "
                    "the question. Do not include explanations or backticks.\n\n"
                    f"Database schema:\n{table_info}\n\nQuestion: {nl_query}"
                )
                sql_resp = self.llm.invoke(sql_only_prompt)
                raw_sql = getattr(sql_resp, "content", None) or str(sql_resp)
                raw_sql = raw_sql.strip()
                safe_sql = verify_sql(raw_sql, engine=self.engine, auto_limit=True, cost_guard=False)
                # Execute to populate last_query/last_result
                _ = db_for_run.run(safe_sql, fetch="all")
                sql_str = getattr(db_for_run, "last_query", str(safe_sql))
                data_rows = getattr(db_for_run, "last_result", [])
                if _is_unhelpful_answer(answer):
                    answer = "Executed fallback SQL."
            except Exception as e:  # noqa: BLE001
                logger.warning(f"SQL-only fallback failed: {e}")

        return {
            "answer": answer,
            "sql": sql_str,
            "data": data_rows,
        }

    def close(self) -> None:
        """Release SQLAlchemy resources held by this engine."""
        try:
            self.engine.dispose()
        except Exception:  # noqa: BLE001
            pass
