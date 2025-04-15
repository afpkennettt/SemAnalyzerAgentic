from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime
import json
import logging
import os

from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create base class for SQLAlchemy models
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy with the base class
db = SQLAlchemy(model_class=Base)

def create_app(config_object=None):
    """Create and configure the Flask application."""
    # Set template folder to the root template directory
    template_dir = os.path.abspath('templates')
    app = Flask(__name__, template_folder=template_dir)
    
    # Load configuration
    if config_object is None:
        app.config.from_object(get_config())
    else:
        app.config.from_object(config_object)
    
    # Configure ProxyFix for proper URL generation behind a proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Initialize extensions
    db.init_app(app)
    
    # Register template filters
    @app.template_filter('datetime')
    def format_datetime(value):
        if not value:
            return ''
        return value.strftime('%Y-%m-%d %H:%M:%S')
    
    @app.template_filter('from_json')
    def from_json(value):
        if not value:
            return {}
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    @app.template_filter('nl2br')
    def nl2br(value):
        if not value:
            return ''
        return value.replace('\n', '<br>')
    
    # Register template globals
    @app.context_processor
    def inject_utilities():
        from app.services.semrush_issues_service import get_issue_title
        return {
            'get_issue_title': get_issue_title
        }
    
    # Register blueprints
    with app.app_context():
        # Import here to avoid circular imports
        from app.api.routes import api_bp
        app.register_blueprint(api_bp)
        
        # Register web routes
        from app.web_routes import web_bp
        app.register_blueprint(web_bp)
    
    # Create database tables
    with app.app_context():
        # Create all tables if they don't exist yet
        db.create_all()
        logger.info("Database tables created")
        
        # Start the background scheduler for periodic tasks
        from app.services.scheduler_service import start_scheduler
        scheduler = start_scheduler(app)
        app.config['SCHEDULER'] = scheduler
        
        # Sync SEMrush issues metadata
        try:
            logger.info("Syncing SEMrush issues metadata...")
            from app.services.semrush_issues_service import sync_semrush_issues
            if sync_semrush_issues():
                logger.info("SEMrush issues metadata synced successfully")
            else:
                logger.warning("Failed to sync SEMrush issues metadata")
        except Exception as e:
            logger.exception(f"Error syncing SEMrush issues metadata: {str(e)}")
    
    return app