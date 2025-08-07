"""
Worker communication routes for the Flask application.
Provides endpoints to communicate with the background schema worker.
"""

from flask import Blueprint, request, jsonify, Response
import requests
import logging
import json
import queue
import threading
import time

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


@bp.route("/refresh_embeddings", methods=["POST"])
def refresh_embeddings():
    """Manually refresh embeddings via the schema worker."""
    try:
        data = request.get_json()
        if not data:
            data = {}

        response = requests.post(f"{WORKER_BASE_URL}/refresh_embeddings", json=data, timeout=30)

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


@bp.route("/add_database_listener", methods=["POST"])
def add_database_listener():
    """Add a database to the monitoring pool."""
    try:
        data = request.get_json()
        if not data or "database" not in data:
            return (
                jsonify({"status": "error", "message": "Database name is required"}),
                400,
            )

        response = requests.post(f"{WORKER_BASE_URL}/add_database_listener", json=data, timeout=10)

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
    """
    Server-Sent Events endpoint for real-time schema change notifications.
    """
    # Import worker functions
    from core.worker.listen_and_refresh import add_sse_client, remove_sse_client
    
    # Create a queue for this client
    event_queue = add_sse_client()
    
    def generate_events():
        try:
            yield 'data: {"type": "connected", "message": "Schema monitoring connected"}\n\n'
            
            while True:
                try:
                    # Try to get event from queue with timeout
                    event_data = event_queue.get(timeout=30)  # 30 second timeout
                    yield f"data: {event_data}\n\n"
                except queue.Empty:
                    # Send heartbeat to keep connection alive
                    heartbeat = {
                        "type": "heartbeat",
                        "timestamp": time.time(),
                        "message": "Connection alive"
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                except:
                    break
        finally:
            # Clean up when client disconnects
            remove_sse_client(event_queue)
    
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
