import os
import requests
import logging
import json
from datetime import datetime

from app import db
from app.models.database import SemrushIssue

logger = logging.getLogger(__name__)

# Set up more detailed logging for debugging
logging.basicConfig(level=logging.INFO)

def fetch_semrush_issue_meta():
    """
    Fetch metadata about all SEMrush issues from the API.
    This provides descriptions for all possible issue IDs.
    
    Returns:
        dict: Dictionary containing issue metadata or None if failed
    """
    try:
        # Get API key from environment
        api_key = os.environ.get('SEMRUSH_API_KEY')
        if not api_key:
            logger.error("SEMrush API key not found in environment variables")
            return None
        
        # Make request to the SEMrush API for issue metadata
        # Note: We need a valid project ID, so we'll fetch the first client with a project ID
        from app.models.database import Client
        
        # Find a client with a project ID to use for the API call
        client = Client.query.filter(Client.semrush_project_id.isnot(None)).first()
        
        if not client or not client.semrush_project_id:
            logger.error("No client with SEMrush project ID found")
            return None
            
        project_id = client.semrush_project_id
        logger.info(f"Using project ID {project_id} for fetching issue metadata")
        
        url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/meta/issues"
        params = {
            "key": api_key
        }
        
        logger.info("Fetching SEMrush issue metadata")
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            try:
                # Log raw response for debugging
                logger.info(f"Raw response: {response.text[:100]}...")
                
                data = response.json()
                
                # The response contains a property called 'issues' that holds the list of issues
                # For debugging (to understand the response structure)
                if isinstance(data, dict) and 'issues' in data:
                    logger.info("Response contains 'issues' key with list of issue objects")
                    issue_list = data['issues']
                    logger.info(f"Found {len(issue_list)} issues in the response")
                    
                    # Return the issue_list directly for processing
                    return issue_list
                elif isinstance(data, list):
                    logger.info(f"Response is a list with {len(data)} items")
                    return data
                else:
                    logger.info(f"Response is a dictionary with keys: {data.keys() if isinstance(data, dict) else 'not a dict'}")
                    return data
            except json.JSONDecodeError:
                logger.error("Failed to parse SEMrush response as JSON")
                logger.debug(f"Response content: {response.text[:500]}...")
                return None
        else:
            logger.error(f"SEMrush API returned error code {response.status_code}")
            logger.debug(f"Response content: {response.text[:500]}...")
            return None
            
    except Exception as e:
        logger.exception(f"Error fetching SEMrush issue metadata: {str(e)}")
        return None

def sync_semrush_issues():
    """
    Fetch and sync SEMrush issue metadata to the database.
    This performs an upsert - adding new issues and updating existing ones.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Fetch issues metadata from SEMrush API
        issues_data = fetch_semrush_issue_meta()
        
        if not issues_data:
            logger.error("Failed to fetch SEMrush issue metadata")
            return False
        
        # Count how many issues we added or updated
        added_count = 0
        updated_count = 0
        
        # Process the issues based on the response format
        # The API can either return a dictionary with issue_id as keys or a list of issues
        if isinstance(issues_data, dict):
            # If it's a dictionary, process each item directly
            items_to_process = [(issue_id, data) for issue_id, data in issues_data.items()]
        elif isinstance(issues_data, list):
            # If it's a list, check if each item has an 'id' field
            items_to_process = []
            for item in issues_data:
                if isinstance(item, dict) and 'id' in item:
                    items_to_process.append((str(item['id']), item))
                else:
                    logger.warning(f"Skipping item without ID: {item}")
        else:
            logger.error(f"Unexpected data format: {type(issues_data)}")
            return False
        
        # Process each issue
        for issue_id, issue_data in items_to_process:
            try:
                # Convert issue_id to integer
                int_issue_id = int(issue_id)
                
                # Check if issue already exists
                existing_issue = SemrushIssue.query.get(int_issue_id)
                
                # Extract fields with fallbacks
                title = issue_data.get('title', '') if isinstance(issue_data, dict) else str(issue_data)
                description = issue_data.get('description', '') if isinstance(issue_data, dict) else ''
                group = issue_data.get('group', '') if isinstance(issue_data, dict) else ''
                issue_type = issue_data.get('type', '') if isinstance(issue_data, dict) else ''
                recommendation = issue_data.get('recommendation', '') if isinstance(issue_data, dict) else ''
                
                if existing_issue:
                    # Update existing issue
                    existing_issue.title = title
                    existing_issue.description = description
                    existing_issue.group = group
                    existing_issue.issue_type = issue_type
                    existing_issue.recommendation = recommendation
                    existing_issue.updated_at = datetime.utcnow()
                    updated_count += 1
                else:
                    # Create new issue
                    new_issue = SemrushIssue(
                        id=int_issue_id,
                        title=title,
                        description=description,
                        group=group,
                        issue_type=issue_type,
                        recommendation=recommendation
                    )
                    db.session.add(new_issue)
                    added_count += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping issue {issue_id} - could not convert to integer: {str(e)}")
        
        # Commit changes to the database
        db.session.commit()
        logger.info(f"SEMrush issues synced successfully: {added_count} added, {updated_count} updated")
        return True
        
    except Exception as e:
        logger.exception(f"Error syncing SEMrush issues: {str(e)}")
        db.session.rollback()
        return False

def get_issue_title(issue_id):
    """
    Get the title for a specific SEMrush issue ID.
    
    Args:
        issue_id (str or int): The issue ID
        
    Returns:
        str: The issue title or None if not found
    """
    try:
        # Convert to integer if possible
        try:
            if isinstance(issue_id, str):
                int_issue_id = int(issue_id)
            else:
                int_issue_id = issue_id
        except (ValueError, TypeError):
            logger.warning(f"Could not convert issue_id {issue_id} to integer")
            return None
            
        issue = SemrushIssue.query.get(int_issue_id)
        return issue.title if issue else None
    except Exception as e:
        logger.exception(f"Error getting issue title for ID {issue_id}: {str(e)}")
        return None

def get_all_issues():
    """
    Get all SEMrush issues from the database.
    
    Returns:
        list: List of SemrushIssue objects
    """
    try:
        return SemrushIssue.query.all()
    except Exception as e:
        logger.exception(f"Error getting all issues: {str(e)}")
        return []