import logging
import threading
import time
import subprocess
import sys
import os

# Suppress ALL TensorFlow and CUDA warnings/errors BEFORE any imports
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress TensorFlow logs
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # Disable CUDA completely
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'  # Prevent tokenizer warnings

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore')

# Suppress TensorFlow logging at Python level
import logging
logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('transformers').setLevel(logging.ERROR)

from flask import Flask, render_template
from api.routes_query import bp as query_bp
from api.routes_chart import bp as chart_bp
from api.routes_health import bp as health_bp
from api.routes_sse import bp as sse_bp
from api.routes_worker import bp as worker_bp
from api.routes_connection import bp as connection_bp
from api.routes_models import bp as models_bp
from config import AppConfig

def create_app() -> Flask:
    """Flask application factory"""
    app = Flask(__name__)

    # Configure logging once
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    
    # Ensure all loggers show DEBUG messages
    logging.getLogger('api.routes_query').setLevel(logging.DEBUG)
    logging.getLogger('core.db.query_engine').setLevel(logging.DEBUG)
    logging.getLogger('core.db.embedder').setLevel(logging.DEBUG)
    
    # Test logging
    logging.info("🔧 Logging configuration completed")
    logging.debug("🔍 Debug logging is active")

    # Load configuration
    config = AppConfig()
    app.config.update(config.model_dump())

    # Register blueprints
    app.register_blueprint(query_bp)
    app.register_blueprint(chart_bp)
    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(models_bp)  # New models blueprint
    app.register_blueprint(sse_bp)
    app.register_blueprint(worker_bp)
    app.register_blueprint(connection_bp)

    # Main route for the web interface
    @app.route('/')
    def index():
        return render_template('index.html')

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'Not found'}, 404

    @app.errorhandler(500)
    def internal_error(error):
        return {'error': 'Internal server error'}, 500

    return app


def start_schema_worker():
    """Start the schema worker in a separate process instead of thread"""
    try:
        # Don't import the worker module at startup to avoid ML library issues
        # Instead, start it as a separate process
        import subprocess
        import sys
        
        # Start worker as separate process
        worker_process = subprocess.Popen([
            sys.executable, '-m', 'core.worker.listen_and_refresh'
        ], cwd=os.getcwd())
        
        logging.info(f"✅ Schema worker started as separate process (PID: {worker_process.pid})")
        return worker_process
        
    except Exception as e:
        logging.error(f"❌ Failed to start schema worker: {e}")
        return None


def check_environment():
    """Check if required environment variables are set"""
    config = AppConfig()
    base_db_url = config.BASE_DATABASE_URL
    
    if base_db_url == "postgresql+asyncpg://user:password@localhost/":
        logging.warning("⚠️  Using default BASE_DATABASE_URL placeholder.")
        logging.info("   For production, set BASE_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/")
        logging.info("   Schema worker will start but may not connect to real databases.")
    else:
        logging.info(f"✅ BASE_DATABASE_URL configured: {base_db_url[:50]}...")
    
    # Set environment variable for worker
    os.environ['BASE_DATABASE_URL'] = base_db_url


if __name__ == "__main__":
    # Check environment
    check_environment()
    
    # Create Flask app
    app = create_app()
    
    # For now, don't start schema worker automatically to avoid segfault
    # User can start it manually if needed
    logging.info("🚀 Starting Flask application without schema worker")
    logging.info("💡 To start schema worker manually: python -m core.worker.listen_and_refresh")
    
    logging.info("🌐 Starting Flask application...")
    logging.info("   📊 Web Interface: http://localhost:5000")
    logging.info("   🛑 Press Ctrl+C to stop")
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
    except KeyboardInterrupt:
        logging.info("🛑 Shutting down services...")
        logging.info("👋 Application stopped")

