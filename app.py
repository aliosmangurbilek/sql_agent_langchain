from dotenv import load_dotenv
# Load environment variables first, before any other imports
load_dotenv()

# Suppress TensorFlow and CUDA warnings
import os
import warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress TensorFlow logs
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # Disable CUDA if not needed
warnings.filterwarnings('ignore', category=FutureWarning, module='torch')
warnings.filterwarnings('ignore', category=UserWarning, module='transformers')

from flask import Flask, render_template
from api.routes_query import bp as query_bp
from api.routes_chart import bp as chart_bp
from api.routes_health import bp as health_bp
from config import AppConfig
import os

def create_app() -> Flask:
    """Flask application factory"""
    app = Flask(__name__)

    # Load configuration
    config = AppConfig()
    app.config.update(config.model_dump())

    # Register blueprints
    app.register_blueprint(query_bp)
    app.register_blueprint(chart_bp)
    app.register_blueprint(health_bp)

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

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
