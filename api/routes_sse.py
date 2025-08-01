"""
api.routes_sse
~~~~~~~~~~~~~~

Server-Sent Events (SSE) endpoints for real-time progress updates.
Provides streaming progress information during query and chart generation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Generator

from flask import Blueprint, request, Response
from werkzeug.exceptions import BadRequest

from core.db.query_engine import QueryEngine
from core.charts.spec_generator import generate_chart_spec

logger = logging.getLogger(__name__)
bp = Blueprint("sse", __name__, url_prefix="/api")


def emit_progress(step: str, message: str, progress: int = 0, data: Any = None) -> str:
    """Create a Server-Sent Event formatted message."""
    event_data = {
        "step": step,
        "message": message,
        "progress": progress,
        "timestamp": time.time()
    }
    if data is not None:
        event_data["data"] = data
    
    return f"data: {json.dumps(event_data)}\n\n"


def process_query_with_progress(db_uri: str, question: str, model: str) -> Generator[str, None, None]:
    """Process a query with progress updates."""
    try:
        yield emit_progress("start", "Starting query processing...", 0)
        
        # Step 1: Initialize query engine
        yield emit_progress("init", "Initializing query engine...", 10)
        qe = QueryEngine(db_uri, llm_model=model)
        
        # Step 2: Start LLM processing
        yield emit_progress("llm_start", "LLM is analyzing your question...", 20)
        
        # Step 3: Embedding search (simulated - this happens inside LangChain)
        yield emit_progress("embedding", "Performing embedding search on database schema...", 40)
        time.sleep(0.5)  # Small delay to show progress
        
        # Step 4: Query generation
        yield emit_progress("query_gen", "Generating SQL query...", 60)
        
        # Step 5: Execute query
        yield emit_progress("query_exec", "Executing query on database...", 80)
        result = qe.ask(question)
        
        # Step 6: Complete
        yield emit_progress("complete", "Query completed successfully!", 100, result)
        
    except Exception as e:
        logger.exception("Query processing failed")
        yield emit_progress("error", f"Error: {str(e)}", -1)


def process_chart_with_progress(db_uri: str, question: str, model: str) -> Generator[str, None, None]:
    """Process a chart generation with progress updates."""
    try:
        yield emit_progress("start", "Starting chart generation...", 0)
        
        # Step 1: Initialize query engine
        yield emit_progress("init", "Initializing query engine...", 10)
        qe = QueryEngine(db_uri, llm_model=model)
        
        # Step 2: Start LLM processing
        yield emit_progress("llm_start", "LLM is analyzing your question...", 20)
        
        # Step 3: Embedding search
        yield emit_progress("embedding", "Performing embedding search on database schema...", 30)
        time.sleep(0.5)
        
        # Step 4: Query generation
        yield emit_progress("query_gen", "Generating SQL query...", 50)
        
        # Step 5: Execute query
        yield emit_progress("query_exec", "Executing query on database...", 70)
        result = qe.ask(question)
        
        # Step 6: Chart generation
        yield emit_progress("chart_gen", "Generating chart specification...", 85)
        vega_spec = generate_chart_spec(
            question=question,
            sql=result["sql"],
            data=result["data"],
            use_llm=True,
        )
        
        # Step 7: Complete
        final_result = {**result, "vega_spec": vega_spec}
        yield emit_progress("complete", "Chart generated successfully!", 100, final_result)
        
    except Exception as e:
        logger.exception("Chart generation failed")
        yield emit_progress("error", f"Error: {str(e)}", -1)


@bp.route("/query-stream", methods=["POST"])
def query_stream():
    """Stream query processing with real-time progress updates."""
    if not request.is_json:
        raise BadRequest("Content-Type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get("model", "deepseek/deepseek-chat")

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    def generate():
        yield from process_query_with_progress(db_uri, question, model)

    return Response(
        generate(),
        mimetype="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@bp.route("/chart-stream", methods=["POST"])
def chart_stream():
    """Stream chart generation with real-time progress updates."""
    if not request.is_json:
        raise BadRequest("Content-Type must be application/json")

    body = request.get_json(silent=True) or {}
    db_uri = body.get("db_uri")
    question = body.get("question")
    model = body.get("model", "deepseek/deepseek-chat")

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    def generate():
        yield from process_chart_with_progress(db_uri, question, model)

    return Response(
        generate(),
        mimetype="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )
