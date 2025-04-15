import logging
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app

from app import db
from app.models.database import Client, SiteAnalysis, AgentTask, AnalysisError
from app.services.semrush_service import perform_site_analysis, check_audit_status, get_audit_issues, process_audit_issues
from app.agents.seo_analyzer import generate_insights

logger = logging.getLogger(__name__)

def weekly_analysis_job(app=None):
    """
    Job to run weekly analysis for all active clients.
    This function queries all active clients, runs analysis for each,
    and generates AI-driven insights.
    
    Args:
        app: Flask application instance
    """
    logger.info("Starting weekly analysis job")
    
    # Use app context to ensure database connection is properly handled
    with app.app_context():
        try:
            # Get all active clients
            clients = Client.query.filter_by(active=True).all()
            logger.info(f"Found {len(clients)} active clients")
            
            for client in clients:
                try:
                    logger.info(f"Running analysis for client: {client.name} ({client.website})")
                    
                    # Create a task for this analysis
                    task = AgentTask(
                        client_id=client.id,
                        task_type='analysis',
                        status='pending',
                        parameters=json.dumps({
                            'client_id': client.id,
                            'website': client.website,
                            'stage': 'init'
                        })
                    )
                    db.session.add(task)
                    db.session.commit()
                    
                    # Import process_analysis_task here to avoid circular imports
                    from app.web_routes import process_analysis_task  
                    
                    # Process the task
                    process_analysis_task(task)
                    
                    logger.info(f"Analysis scheduled for client: {client.name}")
                    
                except Exception as e:
                    logger.exception(f"Error scheduling analysis for client {client.name}: {str(e)}")
                    # Roll back any pending changes
                    db.session.rollback()
        
        except Exception as e:
            logger.exception(f"Error in weekly_analysis_job: {str(e)}")
    
    logger.info("Weekly analysis job completed")


def daily_insight_job(app=None):
    """
    Job to run daily analysis of trends and opportunities.
    This uses LangChain agents to perform deeper analysis on existing data.
    
    Args:
        app: Flask application instance
    """
    logger.info("Starting daily insight job")
    
    # Use app context to ensure database connection is properly handled
    with app.app_context():
        try:
            # Get analyses from the last week
            one_week_ago = datetime.utcnow() - timedelta(days=7)
            recent_analyses = SiteAnalysis.query.filter(SiteAnalysis.analysis_date >= one_week_ago).all()
            
            if not recent_analyses:
                logger.info("No recent analyses found for insight generation")
                return
            
            logger.info(f"Found {len(recent_analyses)} recent analyses for insight generation")
            
            # Implementation of daily insight generation
            # This could involve analyzing trends across all clients
            # or finding new opportunities based on recent data
            
        except Exception as e:
            logger.exception(f"Error in daily_insight_job: {str(e)}")
    
    logger.info("Daily insight job completed")


def check_running_audits_job(app=None):
    """
    Job to periodically check the status of SEMrush audits for running tasks.
    Runs every 2 minutes to check all running audit tasks and update their status.
    
    Args:
        app: Flask application instance
    """
    logger.info("Checking for running SEMrush audit tasks")
    
    # Use app context to ensure database connection is properly handled
    with app.app_context():
        try:
            # Get all running analysis tasks with the 'audit_started' stage
            running_tasks = AgentTask.query.filter_by(status='running', task_type='analysis').all()
            
            if not running_tasks:
                logger.info("No running analysis tasks found")
                return
            
            logger.info(f"Found {len(running_tasks)} running analysis tasks to check")
            
            for task in running_tasks:
                try:
                    # Parse the task parameters
                    if not task.parameters:
                        logger.warning(f"Task {task.id} has no parameters, skipping")
                        continue
                    
                    params = json.loads(task.parameters)
                    stage = params.get('stage')
                    
                    # Skip tasks that are marked to be excluded from future checks
                    if params.get('skip_future_checks'):
                        logger.info(f"Task {task.id} is marked to skip future checks, skipping")
                        continue
                    
                    # Only process tasks that have started a SEMrush audit
                    if stage == 'audit_started':
                        project_id = params.get('project_id')
                        snapshot_id = params.get('snapshot_id')
                        
                        if not project_id or not snapshot_id:
                            logger.warning(f"Task {task.id} missing project_id or snapshot_id, skipping")
                            continue
                        
                        # Get client info for domain
                        client = Client.query.get(task.client_id)
                        if not client:
                            logger.warning(f"Client {task.client_id} not found for task {task.id}, skipping")
                            continue
                        
                        # Get API key from config
                        api_key = app.config.get('SEMRUSH_API_KEY')
                        if not api_key:
                            logger.error("SEMrush API key not found in configuration")
                            continue
                        
                        # Check audit status
                        logger.info(f"Checking audit status for project {project_id}, snapshot {snapshot_id}")
                        audit_status = check_audit_status(api_key, project_id, snapshot_id)
                        
                        if not audit_status:
                            logger.warning(f"Could not get audit status for project {project_id}")
                            continue
                        
                        logger.info(f"Audit status for project {project_id}: {audit_status}")
                        
                        if audit_status.upper() in ["DONE", "FINISHED"]:
                            # Audit is complete, get audit issues
                            logger.info(f"Audit complete for project {project_id}, getting issues data")
                            issues_data = get_audit_issues(api_key, project_id, snapshot_id, client.website)
                            
                            if issues_data:
                                # Process audit issues and create SiteAnalysis record
                                processed_data = process_audit_issues(issues_data, client.website)
                                
                                # Create a new SiteAnalysis record
                                defects = processed_data.get('defects', {})
                                campaign_info = processed_data.get('campaign_info', {})
                                
                                # Create analysis record
                                analysis = SiteAnalysis(
                                    client_id=client.id,
                                    semrush_project_id=project_id,
                                    semrush_snapshot_id=snapshot_id,
                                    total_errors=campaign_info.get('errors', 0),
                                    total_warnings=campaign_info.get('warnings', 0),
                                    total_notices=campaign_info.get('notices', 0),
                                    total_broken=campaign_info.get('broken', 0),
                                    total_blocked=campaign_info.get('blocked', 0),
                                    total_redirected=campaign_info.get('redirected', 0),
                                    total_healthy=campaign_info.get('healthy', 0),
                                    total_pages_crawled=campaign_info.get('pages_crawled', 0),
                                    pages_with_issues=campaign_info.get('have_issues', 0),
                                    defects=json.dumps(defects),
                                    raw_response=json.dumps(processed_data)
                                )
                                
                                db.session.add(analysis)
                                db.session.commit()
                                
                                # Add specific errors as AnalysisError records
                                if defects:
                                    # Loop through the defects by category (errors, warnings, notices)
                                    for category_key, category_data in defects.items():
                                        # Get the error type (error, warning, notice)
                                        error_type = category_data.get('group', 'warning')
                                        severity_base = category_data.get('severity', 5)
                                        
                                        # Extract items from each category
                                        items = category_data.get('items', [])
                                        
                                        for item in items:
                                            # For each item, create an AnalysisError record
                                            # Get issue id and count from the item
                                            issue_id = item.get('id', 'Unknown')
                                            count = item.get('count', 1)
                                            
                                            error = AnalysisError(
                                                analysis_id=analysis.id,
                                                error_type=error_type,
                                                category=category_key.capitalize(),  # Use the category key as category
                                                description=item.get('text', f"Issue ID: {issue_id}"),
                                                url=item.get('url', ''),
                                                severity=severity_base,
                                                semrush_issue_id=str(issue_id),
                                                count=count
                                            )
                                            db.session.add(error)
                                    
                                    # Also extract detailed issues from the raw data if available
                                    raw_info = processed_data.get('raw_info', {})
                                    defect_ids = raw_info.get('defects', {})
                                    
                                    # Get the full error, warning, notice arrays from the current_snapshot if available
                                    current_snapshot = raw_info.get('current_snapshot', {})
                                    if not current_snapshot:
                                        current_snapshot = raw_info  # Sometimes data is at the root level
                                    
                                    # Extract semrush issue classifications
                                    semrush_errors = []
                                    semrush_warnings = []
                                    semrush_notices = []
                                    
                                    # Get the actual errors, warnings, notices arrays with their correct categorizations
                                    if isinstance(current_snapshot.get('errors'), list):
                                        semrush_errors = [str(item.get('id')) for item in current_snapshot.get('errors', []) if item.get('count', 0) > 0]
                                    if isinstance(current_snapshot.get('warnings'), list):
                                        semrush_warnings = [str(item.get('id')) for item in current_snapshot.get('warnings', []) if item.get('count', 0) > 0]
                                    if isinstance(current_snapshot.get('notices'), list):
                                        semrush_notices = [str(item.get('id')) for item in current_snapshot.get('notices', []) if item.get('count', 0) > 0]
                                    
                                    logger.info(f"SEMrush categorization - Errors: {semrush_errors}, Warnings: {semrush_warnings}, Notices: {semrush_notices}")
                                    
                                    # If we have detailed defect IDs, add them as specific errors
                                    for defect_id, count in defect_ids.items():
                                        if isinstance(defect_id, str) and isinstance(count, int) and count > 0:
                                            # Determine type and severity based on SEMrush's categorization
                                            if defect_id in semrush_errors:
                                                error_type = 'error'
                                                severity = 8
                                            elif defect_id in semrush_warnings:
                                                error_type = 'warning'
                                                severity = 5
                                            elif defect_id in semrush_notices:
                                                error_type = 'notice'
                                                severity = 3
                                            else:
                                                # Fallback logic if not found in any category
                                                issue_id_int = int(defect_id)
                                                if issue_id_int < 100:
                                                    error_type = 'error'
                                                    severity = 8
                                                elif issue_id_int < 200:
                                                    error_type = 'warning'
                                                    severity = 5
                                                else:
                                                    error_type = 'notice'
                                                    severity = 3
                                            
                                            # Create error record for each defect type with proper categorization
                                            error = AnalysisError(
                                                analysis_id=analysis.id,
                                                error_type=error_type,
                                                category='SEMrush Issue ID',
                                                description=f"Issue ID: {defect_id} (Found on {count} pages)",
                                                url='',
                                                severity=severity,
                                                semrush_issue_id=defect_id,
                                                count=count
                                            )
                                            db.session.add(error)
                                    
                                    # Commit all the error records
                                    db.session.commit()
                                
                                # Update the task to completed status
                                task.status = 'completed'
                                task.completed_at = datetime.utcnow()
                                task.result = json.dumps({'analysis_id': analysis.id})
                                # Mark this task to skip future checks since it's now completed
                                params['skip_future_checks'] = True
                                task.parameters = json.dumps(params)
                                db.session.commit()
                                
                                logger.info(f"Task {task.id} completed successfully")
                            else:
                                # No issues data, mark as failed
                                task.status = 'failed'
                                task.error_message = "Failed to get audit issues data"
                                task.completed_at = datetime.utcnow()
                                # Mark this task to skip future checks
                                params['skip_future_checks'] = True
                                task.parameters = json.dumps(params)
                                db.session.commit()
                                
                                logger.error(f"Task {task.id} failed - no audit issues data")
                        elif audit_status.upper() == "FAILED":
                            # Audit failed, update task status
                            task.status = 'failed'
                            task.error_message = "SEMrush audit failed"
                            task.completed_at = datetime.utcnow()
                            # Mark this task to skip future checks
                            params['skip_future_checks'] = True
                            task.parameters = json.dumps(params)
                            db.session.commit()
                            
                            logger.error(f"Task {task.id} failed - SEMrush audit failed")
                        else:
                            # Audit is still in progress, just update the parameters with the current status
                            # This ensures we keep track of the latest status but don't modify the task's overall status
                            params['audit_status'] = audit_status
                            task.parameters = json.dumps(params)
                            db.session.commit()
                            
                            logger.info(f"Task {task.id} still in progress, status: {audit_status}")
                except Exception as e:
                    logger.exception(f"Error checking task {task.id}: {str(e)}")
        
        except Exception as e:
            logger.exception(f"Error in check_running_audits_job: {str(e)}")


def start_scheduler(app=None):
    """
    Initialize and start the background scheduler for recurring tasks.
    
    Args:
        app: Flask application instance
    """
    if app is None:
        from flask import current_app
        app = current_app
        
    logger.info("Initializing scheduler")
    
    # Create a scheduler
    scheduler = BackgroundScheduler(timezone=app.config.get('SCHEDULER_TIMEZONE', 'UTC'))
    
    # Add weekly analysis job (runs every Monday at 1 AM)
    scheduler.add_job(
        weekly_analysis_job,
        trigger=CronTrigger(day_of_week='mon', hour=1, minute=0),
        id='weekly_analysis',
        replace_existing=True,
        args=[app]
    )
    
    # Add daily insight job (runs every day at 3 AM)
    scheduler.add_job(
        daily_insight_job,
        trigger=CronTrigger(hour=3, minute=0),
        id='daily_insights',
        replace_existing=True,
        args=[app]
    )
    
    # Add job to check running SEMrush audit tasks every 2 minutes
    scheduler.add_job(
        check_running_audits_job,
        trigger=IntervalTrigger(minutes=2),
        id='check_running_audits',
        replace_existing=True,
        args=[app]
    )
    
    # Start the scheduler if it's not already running
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started with the following jobs:")
        for job in scheduler.get_jobs():
            logger.info(f"- {job.id}: {job.next_run_time}")
    
    return scheduler