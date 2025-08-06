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
import threading
from typing import Any, Dict, Generator
from queue import Queue
import queue

from flask import Blueprint, request, Response
from werkzeug.exceptions import BadRequest

from core.db.query_engine import QueryEngine
from core.charts.spec_generator import generate_chart_spec
from api.utils import CustomJSONEncoder

logger = logging.getLogger(__name__)
bp = Blueprint("sse", __name__, url_prefix="/api")


class ProgressTracker:
    """Thread-safe progress tracker for SSE updates."""
    
    def __init__(self):
        self.progress_queue = Queue()
        self.is_complete = False
        self.error = None
        self.result = None
        
    def update(self, step: str, message: str, progress: int, data: Any = None):
        """Add a progress update to the queue."""
        self.progress_queue.put({
            "step": step,
            "message": message,
            "progress": progress,
            "timestamp": time.time(),
            "data": data
        })
        
        if step == "complete":
            self.is_complete = True
            self.result = data
        elif step == "error":
            self.error = message
            self.is_complete = True
            
    def get_updates(self) -> Generator[Dict, None, None]:
        """Generator that yields progress updates."""
        last_ping = time.time()
        while not self.is_complete:
            try:
                update = self.progress_queue.get(timeout=5)
                yield update
                self.progress_queue.task_done()
            except queue.Empty:
                if time.time() - last_ping > 30:
                    yield {
                        "step": "heartbeat",
                        "message": "Processing...",
                        "progress": -1,
                        "timestamp": time.time(),
                    }
                    last_ping = time.time()
                
        # Yield any remaining updates
        while not self.progress_queue.empty():
            try:
                update = self.progress_queue.get_nowait()
                yield update
                self.progress_queue.task_done()
            except:
                break


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
    
    return f"data: {json.dumps(event_data, cls=CustomJSONEncoder)}\n\n"


def execute_query_in_background(db_uri: str, question: str, model: str, tracker: ProgressTracker):
    """Execute query in a background thread with progress tracking."""
    try:
        tracker.update("start", "Starting query processing...", 0)
        
        # Step 1: Initialize query engine
        tracker.update("init", "Initializing query engine...", 10)
        qe = QueryEngine(db_uri, llm_model=model)
        
        # Step 2: Create progress callback
        def progress_callback(step: str, message: str, progress: int):
            tracker.update(step, message, progress)
        
        # Step 3: Execute query
        tracker.update("agent_start", "Starting AI agent...", 20)
        result = qe.ask(question, progress_callback=progress_callback)
        
        # Step 4: Complete
        tracker.update("complete", "Query completed successfully!", 100, result)
        
    except Exception as e:
        logger.exception("Query processing failed")
        tracker.update("error", f"Error: {str(e)}", -1)


def execute_chart_in_background(
    db_uri: str, question: str, model: str, use_llm: bool, tracker: ProgressTracker
):
    """Execute chart generation in a background thread with progress tracking."""
    try:
        tracker.update("start", "Starting chart generation...", 0)

        # Step 1: Initialize query engine
        tracker.update("init", "Initializing query engine...", 10)
        qe = QueryEngine(db_uri, llm_model=model)
        
        # Step 2: Create progress callback
        def progress_callback(step: str, message: str, progress: int):
            # Adjust progress for chart generation (reserve 15% for chart creation)
            adjusted_progress = min(progress * 0.85, 85)
            tracker.update(step, message, int(adjusted_progress))
        
        # Step 3: Execute query
        tracker.update("agent_start", "Starting AI agent...", 20)
        result = qe.ask(question, progress_callback=progress_callback)
        
        # Step 4: Chart generation
        tracker.update("chart_gen", "Generating chart specification...", 90)
        vega_spec = generate_chart_spec(
            question=question,
            sql=result["sql"],
            data=result["data"],
            use_llm=use_llm,
        )
        
        # Step 5: Complete
        final_result = {**result, "vega_spec": vega_spec}
        tracker.update("complete", "Chart generated successfully!", 100, final_result)
        
    except Exception as e:
        logger.exception("Chart generation failed")
        tracker.update("error", f"Error: {str(e)}", -1)


def process_query_with_progress(db_uri: str, question: str, model: str) -> Generator[str, None, None]:
    """Process a query with progress updates using background thread."""
    tracker = ProgressTracker()
    
    # Start background thread
    thread = threading.Thread(
        target=execute_query_in_background,
        args=(db_uri, question, model, tracker)
    )
    thread.daemon = True
    thread.start()
    
    # Stream progress updates
    for update in tracker.get_updates():
        if update["step"] != "heartbeat":  # Don't emit heartbeat messages
            yield emit_progress(
                update["step"],
                update["message"],
                update["progress"],
                update.get("data")
            )


def process_chart_with_progress(db_uri: str, question: str, model: str, use_llm: bool) -> Generator[str, None, None]:
    """Process a chart generation with progress updates using background thread."""
    tracker = ProgressTracker()

    # Start background thread
    thread = threading.Thread(
        target=execute_chart_in_background,
        args=(db_uri, question, model, use_llm, tracker)
    )
    thread.daemon = True
    thread.start()

    # Stream progress updates
    for update in tracker.get_updates():
        if update["step"] != "heartbeat":  # Don't emit heartbeat messages
            yield emit_progress(
                update["step"],
                update["message"],
                update["progress"],
                update.get("data")
            )


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
    use_llm = bool(body.get("use_llm", False))

    if not db_uri or not question:
        raise BadRequest("Both 'db_uri' and 'question' fields are required")

    def generate():
        yield from process_chart_with_progress(db_uri, question, model, use_llm)

    return Response(
        generate(),
        mimetype="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )
