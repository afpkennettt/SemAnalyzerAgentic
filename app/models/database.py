from datetime import datetime
from app import db

class Client(db.Model):
    """Model for storing client information."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    website = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # SEMrush project information
    semrush_project_id = db.Column(db.String(100))
    semrush_project_name = db.Column(db.String(255))
    semrush_owner_id = db.Column(db.String(100))
    
    # Relationships
    analyses = db.relationship('SiteAnalysis', backref='client', lazy=True, cascade="all, delete-orphan")
    conversation_history = db.relationship('ConversationHistory', backref='client', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Client {self.name}>"


class SiteAnalysis(db.Model):
    """Model for storing website analysis results."""
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    analysis_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # SEMrush integration data
    semrush_project_id = db.Column(db.String(100))
    semrush_snapshot_id = db.Column(db.String(100))
    
    # Analysis metrics
    total_errors = db.Column(db.Integer, default=0)
    total_warnings = db.Column(db.Integer, default=0)
    total_notices = db.Column(db.Integer, default=0)
    total_broken = db.Column(db.Integer, default=0)
    total_blocked = db.Column(db.Integer, default=0)
    total_redirected = db.Column(db.Integer, default=0)
    total_healthy = db.Column(db.Integer, default=0)
    total_pages_crawled = db.Column(db.Integer, default=0)
    total_pages_limit = db.Column(db.Integer, default=0)
    
    # Additional SEMrush data
    raw_response = db.Column(db.Text)  # Store the raw JSON response
    defects = db.Column(db.Text)  # JSON string with defect details
    pages_with_issues = db.Column(db.Integer, default=0)
    pages_with_issues_delta = db.Column(db.Integer, default=0)
    
    # AI-generated insights
    summary = db.Column(db.Text)
    insights = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    
    # Relationships
    errors = db.relationship('AnalysisError', backref='analysis', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<SiteAnalysis {self.id} for client {self.client_id}>"


class AnalysisError(db.Model):
    """Model for storing individual errors found during analysis."""
    id = db.Column(db.Integer, primary_key=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('site_analysis.id'), nullable=False)
    error_type = db.Column(db.String(50), nullable=False)  # 'error', 'warning', 'notice'
    category = db.Column(db.String(100))  # e.g., 'SEO', 'Performance', 'Accessibility'
    description = db.Column(db.Text)
    url = db.Column(db.String(255))  # The specific URL where the error was found
    severity = db.Column(db.Integer)  # 1-10 scale, with 10 being most severe
    semrush_issue_id = db.Column(db.Integer)  # ID from SEMrush API (e.g., 2, 6, 102)
    count = db.Column(db.Integer, default=1)  # Number of occurrences of this issue
    
    # AI-generated fields
    impact = db.Column(db.Text)  # AI explanation of the impact
    solution = db.Column(db.Text)  # AI-generated solution
    
    def __repr__(self):
        return f"<AnalysisError {self.id} of type {self.error_type}>"


class ConversationHistory(db.Model):
    """Model for storing conversation history with the AI."""
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_query = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text, nullable=False)
    
    # Metadata
    query_type = db.Column(db.String(50))  # e.g., 'insight', 'recommendation', 'question'
    related_analysis_id = db.Column(db.Integer, db.ForeignKey('site_analysis.id'), nullable=True)
    
    def __repr__(self):
        return f"<ConversationHistory {self.id} for client {self.client_id}>"


class AgentTask(db.Model):
    """Model for storing agent tasks and their status."""
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    task_type = db.Column(db.String(50), nullable=False)  # e.g., 'analysis', 'recommendation', 'research'
    status = db.Column(db.String(20), default='pending')  # 'pending', 'running', 'completed', 'failed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    # Task details
    parameters = db.Column(db.Text)  # JSON string of parameters
    result = db.Column(db.Text)  # JSON string of result
    error_message = db.Column(db.Text)
    
    def __repr__(self):
        return f"<AgentTask {self.id} of type {self.task_type} for client {self.client_id}>"


class SemrushIssue(db.Model):
    """Model for storing SEMrush issue types and descriptions."""
    id = db.Column(db.Integer, primary_key=True)  # Issue ID from SEMrush (e.g., 2, 6, 102)
    title = db.Column(db.Text, nullable=False)  # Issue title
    description = db.Column(db.Text)  # Detailed description
    group = db.Column(db.String(50))  # Group category (error, warning, notice, etc.)
    issue_type = db.Column(db.String(100))  # More specific issue type
    recommendation = db.Column(db.Text)  # SEMrush recommendation for fixing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<SemrushIssue {self.id}: {self.title}>"