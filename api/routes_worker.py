"""
Worker communication routes for the Flask application.
Provides endpoints to communicate with the background schema worker.
"""

from flask import Blueprint, request, jsonify
import requests
import logging

logger = logging.getLogger(__name__)

bp = Blueprint("worker", __name__, url_prefix="/api/worker")

WORKER_BASE_URL = "http://localhost:9500"


@bp.route("/status", methods=["GET"])
def get_worker_status():
    """Get the status of the background schema worker."""
    try:
        response = requests.get(f"{WORKER_BASE_URL}/status", timeout=5)
        if response.status_code == 200:
            return jsonify(
                {"status": "success", "worker_online": True, "data": response.json()}
            )
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "worker_online": False,
                        "message": f"Worker returned status {response.status_code}",
                    }
                ),
                503,
            )
    except requests.RequestException as e:
        logger.warning(f"Failed to connect to schema worker: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "worker_online": False,
                    "message": "Worker is offline or unreachable",
                }
            ),
            503,
        )


@bp.route("/set_db", methods=["POST"])
def set_active_database():
    """Set the active database in the schema worker."""
    try:
        data = request.get_json()
        if not data or "database" not in data:
            return (
                jsonify({"status": "error", "message": "Database name is required"}),
                400,
            )

        response = requests.post(f"{WORKER_BASE_URL}/set_db", json=data, timeout=10)

        if response.status_code == 200:
            return jsonify({"status": "success", "data": response.json()})
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Worker returned status {response.status_code}",
                        "details": response.text,
                    }
                ),
                response.status_code,
            )

    except requests.RequestException as e:
        logger.error(f"Failed to communicate with schema worker: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Failed to communicate with worker",
                    "details": str(e),
                }
            ),
            503,
        )


@bp.route("/schema_events", methods=["GET"])
def schema_events_stream():
    """Proxy SSE stream from the worker to frontend clients."""

    from flask import Response

    def generate_events():
        try:
            with requests.get(
                f"{WORKER_BASE_URL}/events", stream=True, timeout=(5, None)
            ) as r:
                for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                    if chunk:
                        yield chunk
        except requests.RequestException as e:
            logger.error(f"SSE proxy error: {e}")
            yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"

    return Response(
        generate_events(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@bp.errorhandler(Exception)
def handle_worker_error(error):
    """Handle unexpected errors in worker communication."""
    logger.error(f"Worker communication error: {error}")
    return (
        jsonify(
            {
                "status": "error",
                "message": "Internal worker communication error",
                "details": str(error),
            }
        ),
        500,
    )
