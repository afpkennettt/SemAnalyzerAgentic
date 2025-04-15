from flask import Blueprint, jsonify, request, current_app
import logging
import json
from datetime import datetime

from app import db
from app.models.database import Client, SiteAnalysis, ConversationHistory, AgentTask
from app.services.semrush_service import perform_site_analysis
from app.agents.seo_analyzer import generate_insights
from app.agents.recommendation_engine import generate_recommendations

logger = logging.getLogger(__name__)

# Create a blueprint for the API routes
api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/health', methods=['GET'])
def health_check():
    """API endpoint for health check."""
    return jsonify({
        'status': 'ok',
        'message': 'SemAnalyzerAgentic API is operational',
        'timestamp': datetime.utcnow().isoformat()
    })


@api_bp.route('/clients', methods=['GET'])
def get_clients():
    """Get all clients."""
    clients = Client.query.all()
    
    # Convert to a list of dictionaries
    client_list = [{
        'id': client.id,
        'name': client.name,
        'website': client.website,
        'email': client.email,
        'active': client.active,
        'created_at': client.created_at.isoformat() if client.created_at else None
    } for client in clients]
    
    return jsonify(client_list)


@api_bp.route('/clients', methods=['POST'])
def create_client():
    """Create a new client."""
    data = request.json
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Validate required fields
    required_fields = ['name', 'website', 'email']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # Create a new client
    client = Client(
        name=data['name'],
        website=data['website'],
        email=data['email'],
        active=data.get('active', True)
    )
    
    # Add to database and commit
    db.session.add(client)
    db.session.commit()
    
    return jsonify({
        'id': client.id,
        'name': client.name,
        'website': client.website,
        'email': client.email,
        'active': client.active,
        'created_at': client.created_at.isoformat() if client.created_at else None
    }), 201


@api_bp.route('/clients/<int:client_id>', methods=['GET'])
def get_client(client_id):
    """Get a specific client by ID."""
    client = Client.query.get_or_404(client_id)
    
    return jsonify({
        'id': client.id,
        'name': client.name,
        'website': client.website,
        'email': client.email,
        'active': client.active,
        'created_at': client.created_at.isoformat() if client.created_at else None,
        'updated_at': client.updated_at.isoformat() if client.updated_at else None,
        'semrush_project_id': client.semrush_project_id,
        'semrush_project_name': client.semrush_project_name
    })


@api_bp.route('/clients/<int:client_id>', methods=['PUT'])
def update_client(client_id):
    """Update a specific client."""
    client = Client.query.get_or_404(client_id)
    data = request.json
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Update fields
    if 'name' in data:
        client.name = data['name']
    if 'website' in data:
        client.website = data['website']
    if 'email' in data:
        client.email = data['email']
    if 'active' in data:
        client.active = data['active']
    
    # Update database
    db.session.commit()
    
    return jsonify({
        'id': client.id,
        'name': client.name,
        'website': client.website,
        'email': client.email,
        'active': client.active,
        'updated_at': client.updated_at.isoformat() if client.updated_at else None
    })


@api_bp.route('/clients/<int:client_id>', methods=['DELETE'])
def delete_client(client_id):
    """Delete a specific client."""
    client = Client.query.get_or_404(client_id)
    
    # Delete from database
    db.session.delete(client)
    db.session.commit()
    
    return jsonify({'message': f'Client {client_id} deleted successfully'})


@api_bp.route('/clients/<int:client_id>/analyze', methods=['POST'])
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
    # For now, we'll run the analysis synchronously
    try:
        # Update task status
        task.status = 'running'
        task.started_at = datetime.utcnow()
        db.session.commit()
        
        # Perform site analysis
        analysis_data = perform_site_analysis(client.website)
        
        if not analysis_data:
            task.status = 'failed'
            task.error_message = 'Analysis failed to retrieve data'
            db.session.commit()
            return jsonify({'error': 'Analysis failed', 'task_id': task.id}), 500
        
        # Create a new SiteAnalysis record
        analysis = SiteAnalysis(
            client_id=client.id,
            total_errors=analysis_data.get('details', {}).get('errors', 0),
            total_warnings=analysis_data.get('details', {}).get('warnings', 0),
            total_notices=analysis_data.get('details', {}).get('notices', 0),
            raw_response=str(analysis_data)
        )
        
        db.session.add(analysis)
        db.session.commit()
        
        # Get the previous analysis for comparison
        previous_analysis = SiteAnalysis.query.filter_by(client_id=client.id) \
            .filter(SiteAnalysis.id != analysis.id) \
            .order_by(SiteAnalysis.analysis_date.desc()).first()
        
        # Generate AI insights
        insights_data = generate_insights(client, analysis, previous_analysis, analysis_data)
        
        # Update the analysis with AI-generated insights
        analysis.summary = insights_data.get('summary', '')
        analysis.insights = insights_data.get('insights', '')
        analysis.recommendations = insights_data.get('recommendations', '')
        
        # Update task status
        task.status = 'completed'
        task.completed_at = datetime.utcnow()
        task.result = json.dumps({
            'analysis_id': analysis.id,
            'summary': analysis.summary
        })
        
        db.session.commit()
        
        return jsonify({
            'task_id': task.id,
            'status': 'completed',
            'analysis_id': analysis.id,
            'summary': analysis.summary
        })
        
    except Exception as e:
        logger.exception(f"Error during analysis: {str(e)}")
        
        # Update task status
        task.status = 'failed'
        task.error_message = str(e)
        db.session.commit()
        
        return jsonify({'error': str(e), 'task_id': task.id}), 500


@api_bp.route('/analyses/<int:analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    """Get a specific analysis by ID."""
    analysis = SiteAnalysis.query.get_or_404(analysis_id)
    
    # Get all errors for this analysis
    errors = [{
        'id': error.id,
        'error_type': error.error_type,
        'category': error.category,
        'description': error.description,
        'url': error.url,
        'severity': error.severity,
        'impact': error.impact,
        'solution': error.solution
    } for error in analysis.errors]
    
    return jsonify({
        'id': analysis.id,
        'client_id': analysis.client_id,
        'analysis_date': analysis.analysis_date.isoformat() if analysis.analysis_date else None,
        'total_errors': analysis.total_errors,
        'total_warnings': analysis.total_warnings,
        'total_notices': analysis.total_notices,
        'summary': analysis.summary,
        'insights': analysis.insights,
        'recommendations': analysis.recommendations,
        'errors': errors
    })


@api_bp.route('/chat', methods=['POST'])
def chat():
    """Chat with the AI to get insights about SEO data."""
    data = request.json
    
    if not data or 'client_id' not in data or 'message' not in data:
        return jsonify({'error': 'Missing required fields: client_id and message'}), 400
    
    client_id = data['client_id']
    message = data['message']
    
    # Get the client
    client = Client.query.get_or_404(client_id)
    
    # TODO: Implement the chat functionality using LangChain
    # For now, we'll just return a placeholder response
    ai_response = "This is a placeholder response. The actual implementation will use LangChain to provide intelligent responses to your questions about SEO data."
    
    # Store the conversation in the database
    conversation = ConversationHistory(
        client_id=client_id,
        user_query=message,
        ai_response=ai_response,
        query_type='question'
    )
    db.session.add(conversation)
    db.session.commit()
    
    return jsonify({
        'response': ai_response,
        'conversation_id': conversation.id
    })


@api_bp.route('/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Get the status of a specific task."""
    task = AgentTask.query.get_or_404(task_id)
    
    return jsonify({
        'id': task.id,
        'client_id': task.client_id,
        'task_type': task.task_type,
        'status': task.status,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'started_at': task.started_at.isoformat() if task.started_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        'result': json.loads(task.result) if task.result else None,
        'error_message': task.error_message
    })