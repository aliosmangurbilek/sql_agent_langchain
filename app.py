from __future__ import annotations
import logging
from flask import Flask, render_template
from config import get_config

# Import blueprints lazily in register_blueprints to avoid heavy imports at startup
def register_blueprints(app: Flask) -> None:
    from api import routes_health, routes_connection, routes_query, routes_chart, routes_sse, routes_worker, routes_models, routes_database
    app.register_blueprint(routes_health.bp)
    app.register_blueprint(routes_connection.bp)
    app.register_blueprint(routes_query.bp)
    app.register_blueprint(routes_chart.bp)
    app.register_blueprint(routes_sse.bp)
    app.register_blueprint(routes_worker.bp)
    app.register_blueprint(routes_models.bp)
    app.register_blueprint(routes_database.bp)

def create_app() -> Flask:
    cfg = get_config()
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Basic configuration
    app.config["ENV"] = cfg.FLASK_ENV
    app.config["DEBUG"] = bool(cfg.FLASK_DEBUG)
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False
    app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

    # Routes
    @app.get("/")
    def index():
        return render_template("index.html")

    register_blueprints(app)

    logging.getLogger(__name__).info("✅ Flask app initialized")
    return app

if __name__ == "__main__":
    app = create_app()
    cfg = get_config()
    app.run(host="0.0.0.0", port=5000, debug=bool(cfg.FLASK_DEBUG))