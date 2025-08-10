"""
api.routes_sse
~~~~~~~~~~~~~~
Simple SSE endpoint to stream query progress.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from queue import Queue, Empty
from typing import Any, Dict, Generator, Optional

from flask import Blueprint, Response, request, stream_with_context
import sqlalchemy as sa

logger = logging.getLogger(__name__)
bp = Blueprint("sse", __name__, url_prefix="/api/sse")


class ProgressTracker:
    def __init__(self) -> None:
        self._q: "Queue[Dict[str, Any]]" = Queue(maxsize=100)
        self._closed = False

    def push(self, step: str, message: str, progress: int, data: Optional[Dict[str, Any]] = None) -> None:
        payload = {"step": step, "message": message, "progress": int(progress), "ts": time.time()}
        if data:
            payload["data"] = data
        try:
            self._q.put_nowait(payload)
        except Exception:
            pass

    def close(self) -> None:
        self._closed = True

    def generator(self) -> Generator[str, None, None]:
        yield f": heartbeat\n\n"
        while not self._closed:
            try:
                item = self._q.get(timeout=0.5)
            except Empty:
                # Send keepalive
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"


def run_query(db_uri: str, question: str, model: str, tracker: ProgressTracker) -> None:
    tracker.push("start", "Starting query...", 5)
    try:
        from core.db.query_engine import QueryEngine
        engine = QueryEngine(db_uri, llm_model=model)
        def cb(step: str, msg: str, prog: int) -> None:
            tracker.push(step, msg, prog)
        # If QueryEngine accepts callback; else ignore
        result = engine.ask(question, progress_callback=cb)  # type: ignore[call-arg]
        tracker.push("done", "Completed", 100, {"result": {
            "answer": result.get("answer"),
            "sql": result.get("sql"),
            "rowcount": result.get("rowcount", 0),
        }})
    except Exception as e:
        logger.exception("SSE query failed")
        tracker.push("error", str(e), 100)
    finally:
        tracker.close()


@bp.get("/query")
def sse_query():
    db_uri = (request.args.get("db_uri") or "").strip()
    question = (request.args.get("question") or "").strip()
    model = (request.args.get("model") or "deepseek/deepseek-chat").strip()
    if not db_uri or not question:
        return Response("missing db_uri or question", status=400)

    tracker = ProgressTracker()
    t = threading.Thread(target=run_query, args=(db_uri, question, model, tracker), daemon=True)
    t.start()

    return Response(stream_with_context(tracker.generator()), mimetype="text/event-stream")