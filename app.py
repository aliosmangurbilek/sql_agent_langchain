import logging

# Suppress TensorFlow and CUDA warnings
import os
import warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress TensorFlow logs
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # Disable CUDA if not needed
warnings.filterwarnings('ignore', category=FutureWarning, module='torch')
warnings.filterwarnings('ignore', category=UserWarning, module='transformers')

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix
from api.routes_query import bp as query_bp
from api.routes_chart import bp as chart_bp
from api.routes_health import bp as health_bp
from api.routes_databases import bp as databases_bp
from api.routes_models import bp as models_bp
from api.routes_admin import bp as admin_bp
from config import AppConfig, has_default_db_uri

def create_app() -> Flask:
    """Flask application factory"""
    app = Flask(__name__)

    # Configure logging once
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    # Load configuration
    config = AppConfig()
    app.config.update(config.model_dump())

    if config.TRUST_PROXY_HEADERS:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    # Register blueprints
    app.register_blueprint(query_bp)
    app.register_blueprint(chart_bp)
    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(databases_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(admin_bp)

    # Main route for the web interface
    @app.route('/')
    def index():
        return render_template('index.html', has_default_db=has_default_db_uri())

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'Not found'}, 404

    @app.errorhandler(500)
    def internal_error(error):
        return {'error': 'Internal server error'}, 500

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
