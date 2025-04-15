from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, timedelta
import logging
import json
import time
from sqlalchemy import desc
from urllib.parse import urlparse

from app import db
from app.models.database import Client, SiteAnalysis, AnalysisError, ConversationHistory, AgentTask
from app.services.semrush_service import perform_site_analysis
from app.agents.seo_analyzer import generate_insights
from app.agents.recommendation_engine import generate_recommendations
from app.agents.content_optimizer import optimize_content
from app.services.llm_service import run_chat_query
from app.utils.helpers import get_comparison_data, group_errors_by_category, format_date

logger = logging.getLogger(__name__)

# Create a blueprint for the web routes
web_bp = Blueprint('web', __name__)


@web_bp.route('/')
def index():
    """Home page with dashboard summary."""
    try:
        # Get count of active clients
        client_count = Client.query.filter_by(active=True).count()
        
        # Get count of analyses
        analysis_count = SiteAnalysis.query.count()
        
        # Get total issues
        total_issues = db.session.query(db.func.sum(SiteAnalysis.total_errors + SiteAnalysis.total_warnings + SiteAnalysis.total_notices)).scalar() or 0
        
        # Get recent AI insights (placeholder for now)
        ai_insights = []
        
        # Get recent activity
        recent_activity = []
        recent_analyses = SiteAnalysis.query.order_by(desc(SiteAnalysis.analysis_date)).limit(5).all()
        for analysis in recent_analyses:
            client = Client.query.get(analysis.client_id)
            if client:
                recent_activity.append({
                    'title': f"Analysis for {client.website}",
                    'description': f"Found {analysis.total_errors} errors, {analysis.total_warnings} warnings, and {analysis.total_notices} notices.",
                    'time': format_date(analysis.analysis_date),
                    'client': client.name
                })
        
        return render_template('index.html',
                              clients=client_count,
                              analyses=analysis_count,
                              total_issues=total_issues,
                              ai_insights=ai_insights,
                              recent_activity=recent_activity)
    
    except Exception as e:
        logger.exception(f"Error in index route: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return render_template('index.html')


@web_bp.route('/clients')
def list_clients():
    """List all clients in the system."""
    clients = Client.query.all()
    return render_template('clients/list.html', clients=clients)


@web_bp.route('/clients/add', methods=['GET', 'POST'])
def add_client():
    """Form to add a new client."""
    if request.method == 'POST':
        name = request.form.get('name')
        website = request.form.get('website')
        email = request.form.get('email')
        
        if not name or not website or not email:
            flash("All fields are required", "danger")
            return render_template('clients/add.html')
        
        # Create a new client
        client = Client(
            name=name,
            website=website,
            email=email,
            active=True
        )
        
        try:
            db.session.add(client)
            db.session.commit()
            
            # Create an analysis task for the new client
            task = AgentTask(
                client_id=client.id,
                task_type='analysis',
                status='pending',
                parameters=json.dumps({'client_id': client.id})
            )
            db.session.add(task)
            db.session.commit()
            
            flash(f"Client {name} added successfully. SEMrush analysis task has been queued.", "success")
            
            # Redirect to the task status page
            return redirect(url_for('web.task_status', task_id=task.id))
        except ValueError as e:
            # This catches the error if client already exists in SEMrush
            db.session.rollback()
            flash(f"Error: {str(e)}", "danger")
            return render_template('clients/add.html')
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error adding client: {str(e)}")
            flash(f"An error occurred: {str(e)}", "danger")
            return render_template('clients/add.html')
    
    return render_template('clients/add.html')


@web_bp.route('/clients/<int:client_id>')
def client_detail(client_id):
    """Show detailed information about a specific client."""
    client = Client.query.get_or_404(client_id)
    
    # Get all analyses for this client, sorted by date (newest first)
    all_analyses = SiteAnalysis.query.filter_by(client_id=client_id).order_by(desc(SiteAnalysis.analysis_date)).all()
    
    # Get the most recent analysis
    recent_analysis = all_analyses[0] if all_analyses else None
    
    # Get previous analysis for comparison
    previous_analysis = all_analyses[1] if len(all_analyses) > 1 else None
    
    # Get comparison data
    comparison = get_comparison_data(previous_analysis, recent_analysis)
    
    return render_template('clients/detail.html',
                          client=client,
                          recent_analysis=recent_analysis,
                          previous_analysis=previous_analysis,
                          comparison=comparison,
                          latest_analysis=recent_analysis,
                          analyses=all_analyses)


@web_bp.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
def edit_client(client_id):
    """Edit an existing client."""
    client = Client.query.get_or_404(client_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        website = request.form.get('website')
        email = request.form.get('email')
        active = request.form.get('active') == 'on'
        
        if not name or not website or not email:
            flash("All fields are required", "danger")
            return render_template('clients/edit.html', client=client)
        
        # Update client
        client.name = name
        client.website = website
        client.email = email
        client.active = active
        
        db.session.commit()
        
        flash(f"Client {name} updated successfully", "success")
        return redirect(url_for('web.client_detail', client_id=client.id))
    
    return render_template('clients/edit.html', client=client)


@web_bp.route('/clients/<int:client_id>/delete', methods=['POST'])
def delete_client(client_id):
    """Delete a client and all related data."""
    client = Client.query.get_or_404(client_id)
    
    try:
        # First delete any related agent tasks
        agent_tasks = AgentTask.query.filter_by(client_id=client_id).all()
        if agent_tasks:
            logger.info(f"Deleting {len(agent_tasks)} related agent tasks for client {client.name}")
            for task in agent_tasks:
                db.session.delete(task)
            db.session.commit()
            
        # Delete any related conversation history
        conversation_history = ConversationHistory.query.filter_by(client_id=client_id).all()
        if conversation_history:
            logger.info(f"Deleting {len(conversation_history)} related conversation history items for client {client.name}")
            for history in conversation_history:
                db.session.delete(history)
            db.session.commit()
            
        # Then delete any related site analyses (which will cascade delete analysis errors)
        analyses = SiteAnalysis.query.filter_by(client_id=client_id).all()
        if analyses:
            logger.info(f"Deleting {len(analyses)} related site analyses for client {client.name}")
            for analysis in analyses:
                # Delete related analysis errors first
                errors = AnalysisError.query.filter_by(analysis_id=analysis.id).all()
                for error in errors:
                    db.session.delete(error)
                # Then delete the analysis
                db.session.delete(analysis)
            db.session.commit()
        
        # Finally delete the client
        db.session.delete(client)
        db.session.commit()
        flash(f"Client {client.name} deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting client: {str(e)}")
        flash(f"Error deleting client: {str(e)}", "danger")
    
    return redirect(url_for('web.list_clients'))


@web_bp.route('/reports')
def list_reports():
    """List all analysis reports."""
    analyses = SiteAnalysis.query.order_by(desc(SiteAnalysis.analysis_date)).all()
    
    # Add client name to each analysis
    for analysis in analyses:
        client = Client.query.get(analysis.client_id)
        analysis.client_name = client.name if client else "Unknown"
    
    return render_template('reports/list.html', analyses=analyses)


@web_bp.route('/reports/<int:analysis_id>')
def report_detail(analysis_id):
    """Show detailed information about a specific analysis report."""
    analysis = SiteAnalysis.query.get_or_404(analysis_id)
    client = Client.query.get(analysis.client_id)
    
    # Import needed classes
    from app.models.database import SemrushIssue
    from sqlalchemy.orm import joinedload
    
    # Get all SEMrush issues from the database to use their metadata
    semrush_issues = SemrushIssue.query.all()
    issue_map = {issue.id: issue for issue in semrush_issues}
    
    # Get errors for this analysis
    errors = AnalysisError.query.filter_by(analysis_id=analysis_id).all()
    
    # Enhance errors with issue details from SemrushIssue table if available
    for error in errors:
        if error.semrush_issue_id and error.semrush_issue_id in issue_map:
            issue = issue_map[error.semrush_issue_id]
            # If we have a count field, include it in the description
            count_text = f" (Found on {error.count} page{'s' if error.count != 1 else ''})" if error.count else ""
            error.description = f"{issue.title}{count_text}"
            # If we have more details in the SemrushIssue table, add them to the error object
            if issue.description:
                error.issue_details = issue.description
            if issue.recommendation:
                error.issue_recommendation = issue.recommendation
    
    # Group errors by category
    grouped_errors = group_errors_by_category(errors)
    
    # Get previous analysis for comparison
    previous_analysis = SiteAnalysis.query.filter(
        SiteAnalysis.client_id == client.id,
        SiteAnalysis.id != analysis.id,
        SiteAnalysis.analysis_date < analysis.analysis_date
    ).order_by(desc(SiteAnalysis.analysis_date)).first()
    
    # Get comparison data
    comparison = get_comparison_data(previous_analysis, analysis)
    
    # Create a mapping of issue IDs to titles from the database
    issue_titles = {issue.id: issue.title for issue in semrush_issues}
    
    # Add some fallback titles for common issues if they're not in the database
    fallback_titles = {
        "1": "5xx server errors",
        "2": "4xx client errors",
        "3": "3xx redirects",
        "4": "Broken links",
        "6": "Connection timeout errors",
        "8": "HTTPS implementation issues",
        "12": "Mixed content issues",
        "102": "Missing meta descriptions",
        "104": "Missing title tags",
        "112": "Title too short",
        "117": "Title too long",
        "123": "Duplicate title tags",
        "202": "Low content pages",
        "213": "Missing alt attributes",
        "215": "Missing or invalid canonical URLs",
        "216": "Missing H1 headings",
        "217": "Multiple H1 headings",
        "218": "Broken images"
    }
    
    # Only use fallback titles if the issue is not in the database
    for issue_id, title in fallback_titles.items():
        if issue_id not in issue_titles:
            issue_titles[issue_id] = title
    
    return render_template('reports/detail.html',
                          analysis=analysis,
                          client=client,
                          errors=errors,
                          grouped_errors=grouped_errors,
                          comparison=comparison,
                          issue_titles=issue_titles)


@web_bp.route('/analyze', methods=['GET', 'POST'])
def analyze():
    """Form to run a new analysis for a client."""
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        
        if not client_id:
            flash("Please select a client", "danger")
            clients = Client.query.filter_by(active=True).all()
            return render_template('analyze.html', clients=clients)
        
        # Redirect to the analyze_client route
        return redirect(url_for('web.analyze_client', client_id=client_id))
    
    # Get active clients
    clients = Client.query.filter_by(active=True).all()
    return render_template('analyze.html', clients=clients)


@web_bp.route('/analyze/<int:client_id>', methods=['GET', 'POST'])
def analyze_client(client_id):
    """Run analysis for a specific client."""
    client = Client.query.get_or_404(client_id)
    
    # Create a task for the analysis
    task = AgentTask(
        client_id=client_id,
        task_type='analysis',
        status='pending',
        parameters=json.dumps({'client_id': client_id})
    )
    db.session.add(task)
    db.session.commit()
    
    # In a production environment, this would be handled asynchronously
    # For now, we'll redirect to a status page that polls for updates
    return redirect(url_for('web.task_status', task_id=task.id))


@web_bp.route('/tasks/<int:task_id>')
def task_status(task_id):
    """Show status of a task and update via AJAX."""
    task = AgentTask.query.get_or_404(task_id)
    client = Client.query.get(task.client_id)
    
    # If the task is pending, start processing it
    if task.status == 'pending':
        try:
            # Update task status to running
            task.status = 'running'
            task.started_at = datetime.utcnow()
            
            # Store the current stage in the task parameters
            task_params = json.loads(task.parameters) if task.parameters else {}
            task_params['stage'] = 'starting'
            task.parameters = json.dumps(task_params)
            
            db.session.commit()
            
            # For analysis tasks, handle the initial setup but don't wait for completion
            if task.task_type == 'analysis':
                # Only start the analysis process but don't wait for it to complete
                # This prevents worker timeouts
                initiate_analysis_task(task)
            
        except Exception as e:
            # Log the error and update task status
            logger.exception(f"Error processing task {task_id}: {str(e)}")
            task.status = 'failed'
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            db.session.commit()
    
    return render_template('task_status.html', task=task, client=client)


def initiate_analysis_task(task):
    """
    Initiates an analysis task without waiting for completion.
    Only performs the initial steps and updates the task with progress info.
    
    Args:
        task (AgentTask): The task to process
    """
    try:
        # Parse parameters
        params = json.loads(task.parameters)
        client_id = params.get('client_id')
        
        if not client_id:
            raise ValueError("Client ID is required for analysis task")
        
        # Get the client
        client = Client.query.get(client_id)
        if not client:
            raise ValueError(f"Client with ID {client_id} not found")
        
        # Update task parameters with project info - will be needed for polling
        params['stage'] = 'starting_analysis'
        params['website'] = client.website
        task.parameters = json.dumps(params)
        db.session.commit()
        
        # Start the SEMrush workflow but only go up to starting the audit
        # This part doesn't take too long
        try:
            from app.services.semrush_service import create_project, enable_site_audit, start_site_audit
            import os
            
            # Get API key from environment
            api_key = os.environ.get('SEMRUSH_API_KEY')
            if not api_key:
                raise ValueError("SEMrush API key not found")
            
            # Parse and clean the website URL
            website = client.website
            if not website.startswith(('http://', 'https://')):
                website = 'https://' + website
            
            parsed_url = urlparse(website)
            domain = parsed_url.netloc
            
            # Remove www. if present
            if domain.startswith("www."):
                domain = domain[4:]
            
            # Create a new project - using a try-except to handle existing projects 
            project_info = None
            try:
                project_info = create_project(api_key, domain, client.name)
            except ValueError as e:
                if "already exists" in str(e).lower():
                    # If project exists, we need to handle this case differently
                    # For now, we'll just return a message
                    task.status = 'failed'
                    task.error_message = f"A project for {domain} already exists in SEMrush. Please use a different website or client name."
                    task.completed_at = datetime.utcnow()
                    db.session.commit()
                    return
                else:
                    raise
            
            if not project_info:
                raise ValueError(f"Failed to create project for domain: {domain}")
            
            # Extract project_id from project_info
            project_id = project_info.get('id')
            
            # Update client with SEMrush project info
            client.semrush_project_id = project_id
            client.semrush_project_name = project_info.get('name')
            client.semrush_owner_id = project_info.get('owner_id')
            
            # Enable site audit functionality for the project
            audit_enabled = enable_site_audit(api_key, project_id, domain)
            if not audit_enabled:
                raise ValueError(f"Failed to enable site audit for project ID: {project_id}")
            
            # Start a site audit
            snapshot_id = start_site_audit(api_key, project_id)
            if not snapshot_id:
                raise ValueError(f"Failed to start site audit for project ID: {project_id}")
            
            # Store the project_id and snapshot_id in the task parameters
            params['project_id'] = project_id
            params['snapshot_id'] = snapshot_id
            params['stage'] = 'audit_started'
            task.parameters = json.dumps(params)
            db.session.commit()
            
            # Return without waiting for the audit to complete
            # The client-side JavaScript will poll for completion
            
        except Exception as e:
            task.status = 'failed'
            task.error_message = f"Error in SEMrush workflow: {str(e)}"
            task.completed_at = datetime.utcnow()
            db.session.commit()
            logger.exception(f"Error in initiate_analysis_task: {str(e)}")
    
    except Exception as e:
        task.status = 'failed'
        task.error_message = f"Error initiating analysis task: {str(e)}"
        task.completed_at = datetime.utcnow()
        db.session.commit()
        logger.exception(f"Error in initiate_analysis_task: {str(e)}")


@web_bp.route('/api/tasks/<int:task_id>/status')
def api_task_status(task_id):
    """API endpoint to get the current status of a task."""
    task = AgentTask.query.get_or_404(task_id)
    
    # If the task is in 'running' state and it's an analysis task, we need to check
    # the actual SEMrush audit status and possibly update the database
    if task.status == 'running' and task.task_type == 'analysis':
        try:
            params = json.loads(task.parameters) if task.parameters else {}
            # Check if we have started an audit
            if params.get('stage') == 'audit_started':
                project_id = params.get('project_id')
                snapshot_id = params.get('snapshot_id')
                
                if project_id and snapshot_id:
                    # Import here to avoid circular imports
                    from app.services.semrush_service import check_audit_status, get_audit_issues
                    import os
                    
                    # Get API key
                    api_key = os.environ.get('SEMRUSH_API_KEY')
                    
                    # Check the current status of the audit
                    audit_status = check_audit_status(api_key, project_id, snapshot_id)
                    
                    # Update response with more detailed status
                    if audit_status == "completed" or audit_status == "FINISHED":
                        # Audit is complete, get the results and update the database
                        website = params.get('website', '')
                        client_id = params.get('client_id')
                        client = Client.query.get(client_id)
                        
                        # Process the audit results
                        try:
                            # Get the parsed domain
                            if not website.startswith(('http://', 'https://')):
                                website = 'https://' + website
                            parsed_url = urlparse(website)
                            domain = parsed_url.netloc
                            if domain.startswith("www."):
                                domain = domain[4:]
                            
                            # Get audit issues
                            issues_data = get_audit_issues(api_key, project_id, snapshot_id, domain)
                            
                            if issues_data:
                                # Create analysis record
                                campaign_info = issues_data.get('campaign_info', {})
                                defects = issues_data.get('defects', {})
                                
                                # Create a new SiteAnalysis record
                                analysis = SiteAnalysis(
                                    client_id=client.id,
                                    analysis_date=datetime.utcnow(),
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
                                    total_pages_limit=campaign_info.get('pages_limit', 0),
                                    pages_with_issues=campaign_info.get('have_issues', 0),
                                    pages_with_issues_delta=campaign_info.get('have_issues_delta', 0),
                                    defects=json.dumps(defects),
                                    raw_response=json.dumps(issues_data)
                                )
                                
                                db.session.add(analysis)
                                db.session.commit()
                                
                                # Add specific errors as AnalysisError records
                                if defects:
                                    # Import SemrushIssue model and issues service for getting titles
                                    from app.models.database import SemrushIssue
                                    from app.services.semrush_issues_service import get_issue_title
                                    
                                    # Get all issue titles for faster lookup
                                    all_issues = SemrushIssue.query.all()
                                    
                                    # Ensure all keys are strings for consistent lookup
                                    issue_titles = {}
                                    for issue in all_issues:
                                        issue_titles[str(issue.id)] = issue.title
                                        
                                    # Log the first few issue titles for debugging
                                    sample_titles = {k: issue_titles[k] for k in list(issue_titles.keys())[:5]} if issue_titles else {}
                                    logger.info(f"Loaded {len(issue_titles)} issue titles. Sample: {sample_titles}")
                                    
                                    for category, items in defects.items():
                                        for item in items.get('items', []):
                                            # Try to get the issue ID from the item
                                            issue_id = item.get('id', '')
                                            
                                            # Debug logging to understand the issue better
                                            logger.debug(f"Processing issue ID: {issue_id}, type: {type(issue_id)}")
                                            logger.debug(f"Available issue titles keys: {list(issue_titles.keys())[:5]}")
                                            
                                            # Get the issue title if available - ensure both are strings for comparison
                                            issue_title = None
                                            issue_id_str = str(issue_id)
                                            if issue_id_str and issue_id_str in issue_titles:
                                                issue_title = issue_titles[issue_id_str]
                                                logger.debug(f"Found title for issue {issue_id_str}: {issue_title}")
                                            else:
                                                logger.debug(f"No title found for issue {issue_id_str} in titles dictionary")
                                            
                                            # Create a more descriptive error text with the format the user wants
                                            issue_id = item.get('id', '')
                                            count = item.get('count', 0)
                                            pages_text = f"Found on {count} page{'s' if count != 1 else ''}"
                                            
                                            if issue_title:
                                                description = f"Issue ID: {issue_id} ({pages_text}) - Issue Title: {issue_title}"
                                            else:
                                                description = f"Issue ID: {issue_id} ({pages_text})"
                                            
                                            # Convert issue_id to an integer if possible
                                            try:
                                                issue_id_int = int(issue_id)
                                            except (ValueError, TypeError):
                                                # If conversion fails, log an error but continue with a null value
                                                logger.warning(f"Could not convert issue_id {issue_id} to integer")
                                                issue_id_int = None
                                            
                                            error = AnalysisError(
                                                analysis_id=analysis.id,
                                                error_type=items.get('group', 'warning'),
                                                category=category,
                                                description=description,
                                                url=item.get('url', ''),
                                                severity=items.get('severity', 5),
                                                semrush_issue_id=issue_id_int,
                                                count=count
                                            )
                                            db.session.add(error)
                                    
                                    db.session.commit()
                                
                                # Update the task
                                task.status = 'completed'
                                task.completed_at = datetime.utcnow()
                                task.result = json.dumps({'analysis_id': analysis.id})
                                db.session.commit()
                            else:
                                # No issues data, mark as failed
                                task.status = 'failed'
                                task.error_message = "Failed to get audit issues data"
                                task.completed_at = datetime.utcnow()
                                db.session.commit()
                        except Exception as e:
                            logger.exception(f"Error processing audit results: {str(e)}")
                            task.status = 'failed'
                            task.error_message = f"Error processing audit results: {str(e)}"
                            task.completed_at = datetime.utcnow()
                            db.session.commit()
                    elif audit_status == "failed" or audit_status == "FAILED":
                        # Audit failed, update task status
                        task.status = 'failed'
                        task.error_message = "SEMrush audit failed"
                        task.completed_at = datetime.utcnow()
                        db.session.commit()
                    else:
                        # Audit is still in progress, just update the parameters with the current status
                        params['audit_status'] = audit_status
                        task.parameters = json.dumps(params)
                        db.session.commit()
        except Exception as e:
            logger.exception(f"Error checking audit status: {str(e)}")
            # Don't update the task status here, just log the error
    
    # Prepare the response
    response = {
        'id': task.id,
        'status': task.status,
        'error': task.error_message if task.error_message else None
    }
    
    # Add task parameters if available
    if task.parameters:
        try:
            params = json.loads(task.parameters)
            response['stage'] = params.get('stage', 'unknown')
            
            # Add audit status if available
            if 'audit_status' in params:
                response['audit_status'] = params['audit_status']
                
            # For analysis tasks in progress, add next check time information
            if task.status == 'running' and task.task_type == 'analysis' and params.get('stage') == 'audit_started':
                # SEMrush audits can take several minutes, let's add a countdown
                # We check every 2 minutes to avoid hitting API rate limits
                response['next_check_in'] = 120  # 2 minutes in seconds
        except:
            pass
    
    # If task is completed and has a result, include redirect info
    if task.status == 'completed' and task.result:
        try:
            result = json.loads(task.result)
            if 'analysis_id' in result:
                response['redirect'] = url_for('web.report_detail', analysis_id=result['analysis_id'])
        except:
            pass
    
    return jsonify(response)


def process_analysis_task(task):
    """
    Process an analysis task using the SEMrush API.
    
    Args:
        task (AgentTask): The task to process
    """
    try:
        # Parse parameters
        params = json.loads(task.parameters)
        client_id = params.get('client_id')
        
        if not client_id:
            raise ValueError("Client ID is required for analysis task")
        
        # Get the client
        client = Client.query.get(client_id)
        if not client:
            raise ValueError(f"Client with ID {client_id} not found")
        
        # Perform site analysis using SEMrush API
        analysis_result = perform_site_analysis(client.website, client.name)
        if not analysis_result:
            raise ValueError(f"Site analysis failed for website: {client.website}")
        
        # Extract SEMrush project data
        semrush_info = analysis_result.get('semrush_project_info', {})
        campaign_info = analysis_result.get('campaign_info', {})
        
        # Update client with SEMrush project info
        client.semrush_project_id = semrush_info.get('id')
        client.semrush_project_name = semrush_info.get('name')
        client.semrush_owner_id = semrush_info.get('owner_id')
        
        # Create a new SiteAnalysis record
        analysis = SiteAnalysis(
            client_id=client.id,
            analysis_date=datetime.utcnow(),
            semrush_project_id=semrush_info.get('id'),
            semrush_snapshot_id=semrush_info.get('snapshot_id'),
            total_errors=campaign_info.get('errors', 0),
            total_warnings=campaign_info.get('warnings', 0),
            total_notices=campaign_info.get('notices', 0),
            total_broken=campaign_info.get('broken', 0),
            total_blocked=campaign_info.get('blocked', 0),
            total_redirected=campaign_info.get('redirected', 0),
            total_healthy=campaign_info.get('healthy', 0),
            total_pages_crawled=campaign_info.get('pages_crawled', 0),
            total_pages_limit=campaign_info.get('pages_limit', 0),
            pages_with_issues=campaign_info.get('have_issues', 0),
            pages_with_issues_delta=campaign_info.get('have_issues_delta', 0),
            defects=json.dumps(campaign_info.get('defects', {})),
            raw_response=json.dumps(analysis_result)
        )
        
        db.session.add(analysis)
        db.session.commit()
        
        # Update the task with the result
        task.result = json.dumps({'analysis_id': analysis.id})
        db.session.commit()
        
        return analysis
    
    except Exception as e:
        logger.exception(f"Error in process_analysis_task: {str(e)}")
        raise


@web_bp.route('/chat')
def chat():
    """Chat interface for asking the AI questions."""
    # Get active clients for the dropdown
    clients = Client.query.filter_by(active=True).all()
    
    # Get recent conversation history
    history = ConversationHistory.query.order_by(desc(ConversationHistory.timestamp)).limit(10).all()
    
    return render_template('chat.html', clients=clients, history=history)


@web_bp.route('/chat/query', methods=['POST'])
def chat_query():
    """Process a chat query and return a response."""
    client_id = request.form.get('client_id')
    query = request.form.get('query')
    
    if not query:
        flash("Please enter a question", "danger")
        return redirect(url_for('web.chat'))
    
    client = None
    context = None
    
    # If client ID is provided, get context for that client
    if client_id:
        client = Client.query.get(client_id)
        
        # Get recent analyses for context
        recent_analysis = SiteAnalysis.query.filter_by(client_id=client_id).order_by(desc(SiteAnalysis.analysis_date)).first()
        
        if recent_analysis:
            # Create context from recent analysis
            context = f"""
            Website: {client.website}
            Recent analysis date: {recent_analysis.analysis_date}
            Summary: {recent_analysis.summary if recent_analysis.summary else 'No summary available'}
            Total errors: {recent_analysis.total_errors}
            Total warnings: {recent_analysis.total_warnings}
            Total notices: {recent_analysis.total_notices}
            Insights: {recent_analysis.insights if recent_analysis.insights else 'No insights available'}
            """
    
    # Get response from AI
    ai_response = run_chat_query(query, context)
    
    # Store the conversation in the database
    conversation = ConversationHistory(
        client_id=client_id if client_id else 1,  # Default to ID 1 if no client selected
        user_query=query,
        ai_response=ai_response,
        query_type='question'
    )
    db.session.add(conversation)
    db.session.commit()
    
    # Return the response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'response': ai_response})
    else:
        # For non-AJAX requests, redirect back to chat with the response in session
        session['last_response'] = ai_response
        session['last_query'] = query
        return redirect(url_for('web.chat'))


@web_bp.route('/optimization', methods=['GET', 'POST'])
def content_optimization():
    """Content optimization interface."""
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        url = request.form.get('url')
        keywords = request.form.get('keywords', '').strip()
        
        if not url:
            flash("Please enter a URL to analyze", "danger")
            clients = Client.query.filter_by(active=True).all()
            return render_template('optimization.html', clients=clients)
        
        # Process keywords
        keyword_list = [k.strip() for k in keywords.split(',') if k.strip()] if keywords else None
        
        # Get client if ID is provided
        client = Client.query.get(client_id) if client_id else None
        
        # Run content optimization
        optimization_results = optimize_content(client, url, keyword_list)
        
        # Store results in session for display
        session['optimization_results'] = optimization_results
        
        return redirect(url_for('web.optimization_results'))
    
    # Get active clients
    clients = Client.query.filter_by(active=True).all()
    return render_template('optimization.html', clients=clients)


@web_bp.route('/optimization/results')
def optimization_results():
    """Show content optimization results."""
    # Get results from session
    results = session.get('optimization_results')
    
    if not results:
        flash("No optimization results found", "warning")
        return redirect(url_for('web.content_optimization'))
    
    return render_template('optimization_results.html', results=results)


@web_bp.route('/reports/<int:analysis_id>/generate-insights')
def generate_insights(analysis_id):
    """Generate AI insights and recommendations for an analysis report."""
    analysis = SiteAnalysis.query.get_or_404(analysis_id)
    client = Client.query.get(analysis.client_id)
    
    try:
        # Create a task for generating insights
        task = AgentTask(
            client_id=client.id,
            task_type='generate_insights',
            status='pending',
            parameters=json.dumps({'analysis_id': analysis_id})
        )
        db.session.add(task)
        db.session.commit()
        
        # Update task status
        task.status = 'running'
        task.started_at = datetime.utcnow()
        db.session.commit()
        
        # Generate insights and recommendations using the SEO analyzer
        from app.agents.seo_analyzer import generate_insights
        
        # Get raw data from the analysis
        raw_data = json.loads(analysis.raw_response) if analysis.raw_response else {}
        
        # Generate insights
        insights = generate_insights(
            website=client.website,
            errors=analysis.total_errors,
            warnings=analysis.total_warnings,
            notices=analysis.total_notices,
            broken=analysis.total_broken,
            redirected=analysis.total_redirected,
            healthy=analysis.total_healthy,
            raw_data=raw_data
        )
        
        # Update analysis with insights
        if insights:
            analysis.insights = insights.get('insights', '')
            analysis.recommendations = insights.get('recommendations', '')
            db.session.commit()
        
        # Update task status
        task.status = 'completed'
        task.completed_at = datetime.utcnow()
        task.result = json.dumps({'success': True})
        db.session.commit()
        
        flash("AI insights and recommendations generated successfully", "success")
    
    except Exception as e:
        # Log the error and handle it
        logger.exception(f"Error generating insights: {str(e)}")
        flash(f"Error generating insights: {str(e)}", "danger")
    
    return redirect(url_for('web.report_detail', analysis_id=analysis_id))


@web_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    """Display and edit system settings."""
    if request.method == 'POST':
        # Update API keys and settings
        semrush_api_key = request.form.get('semrush_api_key')
        openai_api_key = request.form.get('openai_api_key')
        
        # In a real app, we'd store these in the database or environment variables
        # For demo purposes, we'll just show a success message
        flash("Settings updated successfully", "success")
        return redirect(url_for('web.settings'))
    
    # Get current settings from environment or config
    from config import get_config
    config = get_config()
    
    return render_template('settings.html', config=config)


@web_bp.route('/test-semrush-api')
def test_semrush_api():
    """Test the SEMrush API connection."""
    import os
    import requests
    
    # Get API key from environment
    api_key = os.environ.get('SEMRUSH_API_KEY')
    
    if not api_key:
        flash("SEMrush API key is not configured. Please add your API key in the settings.", "danger")
        return redirect(url_for('web.settings'))
    
    # Test API with a simple request to list projects
    projects_url = f"https://api.semrush.com/management/v1/projects?key={api_key}"
    
    try:
        response = requests.get(projects_url)
        
        if response.status_code == 200:
            # Success! Count projects 
            projects = response.json()
            project_count = len(projects)
            
            flash(f"SEMrush API connection successful! Found {project_count} projects.", "success")
        else:
            # Error - show response for debugging
            error_msg = f"Error connecting to SEMrush API: {response.status_code} - {response.text}"
            flash(error_msg, "danger")
            logger.error(error_msg)
    
    except Exception as e:
        # Error - show exception for debugging
        error_msg = f"Exception while connecting to SEMrush API: {str(e)}"
        flash(error_msg, "danger")
        logger.exception(error_msg)
    
    return redirect(url_for('web.settings'))