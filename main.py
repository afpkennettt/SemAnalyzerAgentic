from app import create_app
from app.services.scheduler_service import start_scheduler

# Create the application instance
app = create_app()

if __name__ == "__main__":
    # Start the APScheduler for scheduled tasks
    with app.app_context():
        start_scheduler()
    
    # Run the Flask application
    app.run(host="0.0.0.0", port=5000, debug=True)