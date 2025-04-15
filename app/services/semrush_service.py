import os
import logging
import requests
from urllib.parse import urlparse
import time
import json

logger = logging.getLogger(__name__)

def perform_site_analysis(website, client_name=None):
    """
    Perform a site analysis using the SEMrush API.
    
    Args:
        website (str): The website URL to analyze
        client_name (str, optional): The name of the client for project naming
        
    Returns:
        dict: A dictionary containing the analysis results or None if failed
    """
    # Get API key directly from environment variables 
    api_key = os.environ.get('SEMRUSH_API_KEY')
    if not api_key:
        logger.error("SEMrush API key not found in environment variables")
        raise ValueError("SEMrush API key is required")
    
    # Parse and clean the website URL
    if not website.startswith(('http://', 'https://')):
        website = 'https://' + website
    
    parsed_url = urlparse(website)
    domain = parsed_url.netloc
    
    # Remove www. if present
    if domain.startswith("www."):
        domain = domain[4:]
    
    logger.debug(f"Performing site analysis for domain: {domain}")
    
    try:
        # Check if project already exists
        project_exists = check_if_project_exists(api_key, domain, client_name)
        if project_exists:
            logger.error(f"Project already exists for domain: {domain}")
            raise ValueError(f"A SEMrush project already exists for {domain}. Please choose a different website or client name.")
        
        # Create a new project
        project_info = create_project(api_key, domain, client_name)
        if not project_info:
            logger.error(f"Failed to create project for domain: {domain}")
            return None
        
        # Extract project_id from project_info
        project_id = project_info.get('id')
        
        # Enable site audit functionality for the project
        audit_enabled = enable_site_audit(api_key, project_id, domain)
        if not audit_enabled:
            logger.error(f"Failed to enable site audit for project ID: {project_id}")
            return None
        
        # Start a site audit
        snapshot_id = start_site_audit(api_key, project_id)
        if not snapshot_id:
            logger.error(f"Failed to start site audit for project ID: {project_id}")
            return None
        
        # Wait for the audit to complete (with timeout)
        max_wait_time = 600  # 10 minutes (increased for larger sites)
        wait_interval = 10   # Check every 10 seconds
        total_wait_time = 0
        
        while total_wait_time < max_wait_time:
            status = check_audit_status(api_key, project_id, snapshot_id)
            logger.debug(f"Audit status: {status}")
            
            if status == "completed" or status == "FINISHED":
                break
            elif status == "failed" or status == "FAILED":
                logger.error(f"Audit failed for project ID: {project_id}")
                return None
            
            # Wait before checking again
            time.sleep(wait_interval)
            total_wait_time += wait_interval
        
        if total_wait_time >= max_wait_time:
            logger.error(f"Audit timed out for project ID: {project_id}")
            return None
        
        # Get the campaign information
        campaign_info = get_campaign_info(api_key, project_id, snapshot_id)
        if not campaign_info:
            logger.error(f"Failed to get campaign information for project ID: {project_id}")
            return None
        
        # Process the campaign data
        processed_data = {
            'semrush_project_info': {
                'id': project_id,
                'name': project_info.get('name'),
                'owner_id': project_info.get('owner_id'),
                'snapshot_id': snapshot_id
            },
            'campaign_info': campaign_info,
            'analysis_date': int(time.time())
        }
        
        return processed_data
        
    except Exception as e:
        logger.exception(f"Error during site analysis: {str(e)}")
        return None


def check_if_project_exists(api_key, domain, client_name=None):
    """
    Check if a project already exists for the domain or client name.
    
    Args:
        api_key (str): SEMrush API key
        domain (str): Website domain
        client_name (str, optional): The name of the client
    
    Returns:
        bool: True if project exists, False otherwise
    """
    # Using the correct SEMrush API endpoint for listing projects
    projects_url = "https://api.semrush.com/management/v1/projects"
    url_with_key = f"{projects_url}?key={api_key}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url_with_key, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to list projects: {response.status_code} - {response.text}")
            return False
        
        # Convert domain to clean format for comparison
        clean_domain = domain
        if domain.startswith(('http://', 'https://')):
            parsed = urlparse(domain)
            clean_domain = parsed.netloc
        
        if clean_domain.startswith("www."):
            clean_domain = clean_domain[4:]
        
        # If client name is provided, create sanitized project name for comparison
        if client_name:
            sanitized_client = ''.join(c for c in client_name if c.isalnum() or c in ' _-')
            project_name = f"SEO_Monitor_{sanitized_client}"[:50]
        else:
            project_name = None
        
        # Check projects in response
        projects = response.json()
        for project in projects:
            # Check if domain matches
            project_url = project.get('url', '')
            if clean_domain == project_url:
                logger.info(f"Project already exists with domain {clean_domain}: {project.get('project_id')}")
                return True
            
            # If client name was provided, also check project names
            if project_name and project.get('project_name') == project_name:
                logger.info(f"Project already exists with name {project_name}: {project.get('project_id')}")
                return True
        
        # No matching project found
        return False
            
    except Exception as e:
        logger.exception(f"Error in check_if_project_exists: {str(e)}")
        # In case of error, assume project doesn't exist to continue with creation
        return False


def create_project(api_key, domain, client_name=None):
    """
    Create a new project in SEMrush.
    
    Args:
        api_key (str): SEMrush API key
        domain (str): Website domain
        client_name (str, optional): The name of the client for project naming
    
    Returns:
        dict: Project information or None if failed
    """
    # Using the correct SEMrush API endpoint for projects
    projects_url = "https://api.semrush.com/management/v1/projects"
    # Add API key as query parameter as per documentation
    url_with_key = f"{projects_url}?key={api_key}"
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        # Create a new project based on API documentation
        # SEMrush API expects just the domain without protocol
        # Strip any http/https prefix if present
        clean_domain = domain
        if domain.startswith(('http://', 'https://')):
            parsed = urlparse(domain)
            clean_domain = parsed.netloc
        
        # Generate project name and sanitize it for SEMrush API
        # SEMrush has restrictions on project names - remove special chars and limit length
        if client_name:
            # Clean the client name - remove special characters and limit to alphanumeric chars, spaces, underscores
            sanitized_client = ''.join(c for c in client_name if c.isalnum() or c in ' _-')
            project_name = f"SEO_Monitor_{sanitized_client}"
        else:
            # For domain-based names, make sure it's safe
            sanitized_domain = ''.join(c for c in clean_domain if c.isalnum() or c == '.')
            project_name = f"SEO_Monitor_{sanitized_domain}"
        
        # Limit the length to ensure it doesn't exceed SEMrush limits (typically 50-100 chars)
        project_name = project_name[:50]
            
        payload = {
            "project_name": project_name,
            "url": clean_domain
        }
        
        logger.info(f"Creating SEMrush project with name: {project_name}, url: {clean_domain}")
        response = requests.post(url_with_key, headers=headers, json=payload)
        
        if response.status_code not in (200, 201):
            logger.error(f"Failed to create project: {response.status_code} - {response.text}")
            return None
        
        # Extract project information from response
        response_data = response.json()
        project_id = response_data.get('project_id')
        if not project_id:
            logger.error("No project_id returned in response")
            return None
            
        logger.info(f"Created new project for {domain}: {project_id}")
        
        # Return formatted project information
        return {
            'id': project_id,
            'name': project_name,
            'owner_id': response_data.get('owner_id')
        }
            
    except Exception as e:
        logger.exception(f"Error in create_project: {str(e)}")
        return None


def enable_site_audit(api_key, project_id, domain):
    """
    Enable site audit functionality for a project.
    
    Args:
        api_key (str): SEMrush API key
        project_id (str): Project ID
        domain (str): Website domain
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Using the correct endpoint for enabling site audit
    enable_url = f"https://api.semrush.com/management/v1/projects/{project_id}/siteaudit/enable"
    # Add API key as query parameter
    url_with_key = f"{enable_url}?key={api_key}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # SEMrush API expects just the domain without protocol for the enable call too
    # Strip any http/https prefix if present
    clean_domain = domain
    if domain.startswith(('http://', 'https://')):
        parsed = urlparse(domain)
        clean_domain = parsed.netloc
    
    # Create payload with required parameters
    payload = {
        "domain": clean_domain,
        "scheduleDay": 0,  # 0 means no schedule, run on demand
        "notify": True,
        "allow": [],
        "disallow": [],
        "pageLimit": 1000,
        "userAgentType": 2,
        "removedParameters": [],
        "crawlSubdomains": True,
        "respectCrawlDelay": False
    }
    
    try:
        response = requests.post(url_with_key, headers=headers, json=payload)
        
        if response.status_code in (200, 201):
            logger.info(f"Enabled site audit for project {project_id}")
            return True
        else:
            logger.error(f"Failed to enable site audit: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.exception(f"Error in enable_site_audit: {str(e)}")
        return False


def start_site_audit(api_key, project_id):
    """
    Start a site audit for a project.
    
    Args:
        api_key (str): SEMrush API key
        project_id (str): Project ID
    
    Returns:
        str: Snapshot ID or None if failed
    """
    # Using the correct endpoint for launching a site audit
    audit_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/launch"
    # Add API key as query parameter
    url_with_key = f"{audit_url}?key={api_key}"
    
    # Add headers with content type and potentially authorization
    headers = {
        "Content-Type": "application/json",
    }
    
    # For site audit launch, we may need specific parameters
    # Let's try with a payload that includes audit configuration
    payload = {
        "audit_type": "full",  # Try with explicit audit type
        "check_all": True      # Set to audit the entire site
    }
    
    try:
        # Try with headers and configuration payload
        response = requests.post(url_with_key, headers=headers, json=payload)
        
        if response.status_code in (200, 201):
            response_data = response.json()
            snapshot_id = response_data.get('snapshot_id')
            # Add very clear debug logging for the snapshot ID
            logger.info("="*50)
            logger.info(f"SNAPSHOT ID FROM RUN AUDIT: {snapshot_id}")
            logger.info("="*50)
            logger.info(f"Started site audit for project {project_id}: {snapshot_id}")
            return snapshot_id
        else:
            logger.error(f"Failed to start site audit: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.exception(f"Error in start_site_audit: {str(e)}")
        return None


def check_audit_status(api_key, project_id, snapshot_id):
    """
    Check the status of a site audit.
    
    Args:
        api_key (str): SEMrush API key
        project_id (str): Project ID
        snapshot_id (str): Snapshot ID from the launch response
    
    Returns:
        str: Audit status (in_progress, completed, failed, etc.)
    """
    # Log attempt to check status for debugging
    logger.info(f"[DETAILED DEBUG] Checking audit status for project {project_id}, snapshot {snapshot_id}")
    
    try:
        # Use the siteaudit/info endpoint as recommended by SEMrush
        # This is more reliable than checking snapshot status
        info_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/info"
        info_url_with_key = f"{info_url}?key={api_key[:5]}..." # Truncated for security
        
        logger.info(f"[DETAILED DEBUG] API Request URL: {info_url_with_key}")
        
        info_response = requests.get(f"{info_url}?key={api_key}")
        
        logger.info(f"[DETAILED DEBUG] API Response Status: {info_response.status_code}")
        logger.info(f"[DETAILED DEBUG] API Response Headers: {dict(info_response.headers)}")
        
        if info_response.status_code == 200:
            info_data = info_response.json()
            logger.info(f"[DETAILED DEBUG] API Response Body: {json.dumps(info_data)}")
            
            # Check status from the info response
            status = info_data.get('status')
            if status:
                logger.info(f"[DETAILED DEBUG] Audit status from info endpoint: {status}")
                
                # Map SEMrush status values to our standardized values
                if status == 'completed' or status == 'done' or status == 'DONE' or status == 'FINISHED':
                    return 'done'
                elif status == 'failed' or status == 'FAILED':
                    return 'failed'
                else:
                    return 'in_progress'
            
            # If no status found, check if the audit has issues data which indicates completion
            issues = info_data.get('issues')
            if issues is not None:
                logger.info(f"[DETAILED DEBUG] Audit has issues data, assuming completed")
                return 'done'
            
            logger.info(f"[DETAILED DEBUG] No status or issues found, assuming in progress")
            return 'in_progress'
        
        # If info endpoint fails, try checking the snapshots
        logger.info(f"[DETAILED DEBUG] Info endpoint failed, trying snapshots endpoint")
        snapshots_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/snapshots"
        snapshots_url_with_key = f"{snapshots_url}?key={api_key[:5]}..." # Truncated for security
        
        logger.info(f"[DETAILED DEBUG] API Request URL: {snapshots_url_with_key}")
        
        snapshots_response = requests.get(f"{snapshots_url}?key={api_key}")
        
        logger.info(f"[DETAILED DEBUG] API Response Status: {snapshots_response.status_code}")
        logger.info(f"[DETAILED DEBUG] API Response Headers: {dict(snapshots_response.headers)}")
        
        if snapshots_response.status_code == 200:
            snapshots_data = snapshots_response.json()
            logger.info(f"[DETAILED DEBUG] API Response Body: {json.dumps(snapshots_data)}")
            
            # Check for snapshot data
            snapshots = snapshots_data.get('snapshots', [])
            if snapshots:
                for snapshot in snapshots:
                    if isinstance(snapshot, dict):
                        if snapshot.get('snapshot_id') == snapshot_id and 'finish_date' in snapshot:
                            logger.info(f"[DETAILED DEBUG] Found snapshot with finish_date, assuming completed")
                            return 'done'
            
            logger.info(f"[DETAILED DEBUG] No completed snapshot found")
        
        # As a last resort, try the direct snapshot status endpoint
        status_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/snapshots/{snapshot_id}/status"
        url_with_key = f"{status_url}?key={api_key[:5]}..." # Truncated for security
        
        logger.info(f"[DETAILED DEBUG] API Request URL: {url_with_key}")
        
        response = requests.get(f"{status_url}?key={api_key}")
        
        logger.info(f"[DETAILED DEBUG] API Response Status: {response.status_code}")
        logger.info(f"[DETAILED DEBUG] API Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            status_data = response.json()
            logger.info(f"[DETAILED DEBUG] API Response Body: {json.dumps(status_data)}")
            status = status_data.get('status', 'unknown')
            logger.info(f"[DETAILED DEBUG] Audit status for snapshot {snapshot_id}: {status}")
            
            # Map SEMrush status values
            if status.upper() in ['DONE', 'FINISHED', 'COMPLETED']:
                return 'done'
            elif status.upper() in ['FAILED']:
                return 'failed'
            else:
                return 'in_progress'
        elif response.status_code == 404:
            # API might return 404 while the audit is still processing
            logger.info(f"[DETAILED DEBUG] Audit status check: got 404 for snapshot {snapshot_id}, likely still processing")
            return 'in_progress'
        else:
            logger.error(f"[DETAILED DEBUG] Failed to check audit status: {response.status_code} - {response.text}")
            # Don't immediately report failure on non-200 responses, just indicate in progress
            return 'in_progress'
    
    except Exception as e:
        logger.exception(f"[DETAILED DEBUG] Error in check_audit_status: {str(e)}")
        # Don't immediately report failure on exceptions, just indicate in progress
        return 'in_progress'


def get_campaign_info(api_key, project_id, snapshot_id):
    """
    Get information about the completed audit campaign.
    
    Args:
        api_key (str): SEMrush API key
        project_id (str): Project ID
        snapshot_id (str): Snapshot ID of the completed audit
    
    Returns:
        dict: Campaign information data or None if failed
    """
    try:
        # Ensure we have a valid snapshot_id
        if not snapshot_id or snapshot_id == 'None':
            logger.info("No snapshot ID provided. Looking for the latest completed snapshot.")
            snapshots_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/snapshots"
            snapshots_url_with_key = f"{snapshots_url}?key={api_key}"
            
            snapshots_response = requests.get(snapshots_url_with_key)
            
            if snapshots_response.status_code == 200:
                snapshots_data = snapshots_response.json()
                
                # Look for completed snapshots
                for snapshot in snapshots_data:
                    if snapshot.get('status') == 'completed' or snapshot.get('status') == 'FINISHED':
                        snapshot_id = snapshot.get('id')
                        logger.info(f"Found completed snapshot: {snapshot_id}")
                        break
                
                if not snapshot_id or snapshot_id == 'None':
                    logger.error("No completed snapshots found")
                    return None
            else:
                logger.error(f"Failed to get snapshots: {snapshots_response.status_code}")
                return None
        
        # Get information about the campaign
        logger.info(f"Getting campaign information for project {project_id} with snapshot {snapshot_id}")
        
        # Get campaign information using the snapshot ID
        campaign_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/{snapshot_id}/info"
        url_with_key = f"{campaign_url}?key={api_key}"
        
        response = requests.get(url_with_key)
        
        if response.status_code == 200:
            campaign_data = response.json()
            
            # Log some key information from the response
            logger.info(f"Campaign status: {campaign_data.get('status')}")
            logger.info(f"Errors: {campaign_data.get('errors')}, Warnings: {campaign_data.get('warnings')}, Notices: {campaign_data.get('notices')}")
            
            # Extract key data for the report
            report_data = {
                'status': campaign_data.get('status'),
                'errors': campaign_data.get('errors', 0),
                'warnings': campaign_data.get('warnings', 0),
                'notices': campaign_data.get('notices', 0),
                'broken': campaign_data.get('broken', 0),
                'blocked': campaign_data.get('blocked', 0),
                'redirected': campaign_data.get('redirected', 0),
                'healthy': campaign_data.get('healthy', 0),
                'have_issues': campaign_data.get('haveIssues', 0),
                'have_issues_delta': campaign_data.get('haveIssuesDelta', 0),
                'defects': campaign_data.get('defects', {}),
                'pages_crawled': campaign_data.get('pages_crawled', 0),
                'pages_limit': campaign_data.get('pages_limit', 0),
                'last_audit': campaign_data.get('last_audit', 0),
                'crawl_subdomains': campaign_data.get('crawlSubdomains', False),
                'markups': campaign_data.get('markups', {})
            }
            
            return report_data
        else:
            logger.error(f"Failed to get campaign info: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.exception(f"Error in get_campaign_info: {str(e)}")
        return None


def get_audit_issues(api_key, project_id, snapshot_id, domain=""):
    """
    Get issues from a completed site audit.
    
    Args:
        api_key (str): SEMrush API key
        project_id (str): Project ID
        snapshot_id (str): Snapshot ID from the launch response
        domain (str, optional): Website domain for customizing results
    
    Returns:
        dict: Audit issues data or None if failed
    """
    try:
        # First check using the info endpoint (primary data source)
        logger.info(f"Getting audit info for project {project_id}")
        info_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/info"
        info_url_with_key = f"{info_url}?key={api_key[:5]}..." # Truncated for security
        
        logger.info(f"[DETAILED DEBUG] API Request URL: {info_url_with_key}")
        
        info_response = requests.get(f"{info_url}?key={api_key}")
        
        logger.info(f"[DETAILED DEBUG] API Response Status: {info_response.status_code}")
        logger.info(f"[DETAILED DEBUG] API Response Headers: {dict(info_response.headers)}")
        
        if info_response.status_code == 200:
            info_data = info_response.json()
            logger.info(f"[DETAILED DEBUG] API Response Body: {json.dumps(info_data)}")
            
            # If we have a valid info response, use that as our primary data source
            if info_data and (info_data.get('status') == 'FINISHED' or info_data.get('snapshot_id')):
                # Extract relevant data from info response for easier processing
                # Log key data from the response
                logger.info(f"API Response keys: {list(info_data.keys())}")
                
                # Direct mapping from API response fields to our data structure
                # Based on the actual API response structure:
                # "scheme":"https","errors":21,"warnings":181,"notices":117,"broken":0,"brokenDelta":0,
                # "blocked":1,"blockedDelta":0,"redirected":67,"redirectedDelta":0,"healthy":1,
                # "healthyDelta":0,"haveIssues":22,"haveIssuesDelta":0
                
                campaign_info = {
                    'errors': info_data.get('errors', 0),
                    'warnings': info_data.get('warnings', 0),
                    'notices': info_data.get('notices', 0),
                    'broken': info_data.get('broken', 0),
                    'blocked': info_data.get('blocked', 0),
                    'redirected': info_data.get('redirected', 0),
                    'healthy': info_data.get('healthy', 0),
                    'pages_crawled': info_data.get('pages_crawled', 0),
                    'pages_limit': info_data.get('pages_limit', 0),
                    'have_issues': info_data.get('haveIssues', 0),
                    'have_issues_delta': info_data.get('haveIssuesDelta', 0),
                    'quality': info_data.get('quality', {}).get('value', 0)
                }
                
                logger.info(f"Extracted campaign info: errors={campaign_info['errors']}, " +
                           f"warnings={campaign_info['warnings']}, notices={campaign_info['notices']}, " +
                           f"broken={campaign_info['broken']}, blocked={campaign_info['blocked']}, " +
                           f"redirected={campaign_info['redirected']}, healthy={campaign_info['healthy']}, " +
                           f"have_issues={campaign_info['have_issues']}")
                
                # Prepare defects structure from issues data
                # Handle the case where these might be integers or lists
                errors = info_data.get('errors', [])
                warnings = info_data.get('warnings', [])
                notices = info_data.get('notices', [])
                
                # Convert to proper format if they're integers
                if isinstance(errors, int):
                    error_count = errors
                    error_items = []
                else:
                    error_count = len(errors)
                    error_items = [{'id': item.get('id'), 'text': f"Error {item.get('id')}", 'count': item.get('count', 0)} for item in errors]
                
                if isinstance(warnings, int):
                    warning_count = warnings
                    warning_items = []
                else:
                    warning_count = len(warnings)
                    warning_items = [{'id': item.get('id'), 'text': f"Warning {item.get('id')}", 'count': item.get('count', 0)} for item in warnings]
                
                if isinstance(notices, int):
                    notice_count = notices
                    notice_items = []
                else:
                    notice_count = len(notices)
                    notice_items = [{'id': item.get('id'), 'text': f"Notice {item.get('id')}", 'count': item.get('count', 0)} for item in notices]
                
                # Combine all issue types and count them
                defects = {
                    'errors': {
                        'group': 'error',
                        'severity': 8,
                        'count': error_count,
                        'items': error_items
                    },
                    'warnings': {
                        'group': 'warning',
                        'severity': 5,
                        'count': warning_count,
                        'items': warning_items
                    },
                    'notices': {
                        'group': 'notice',
                        'severity': 3,
                        'count': notice_count,
                        'items': notice_items
                    }
                }
                
                # Combine data into a standard format
                combined_data = {
                    'campaign_info': campaign_info,
                    'defects': defects,
                    'snapshot_id': info_data.get('snapshot_id', snapshot_id),
                    'status': info_data.get('status', 'FINISHED'),
                    'raw_info': info_data,
                    # Add these fields directly for easier access
                    'total_errors': campaign_info.get('errors', 0),
                    'total_warnings': campaign_info.get('warnings', 0),
                    'total_notices': campaign_info.get('notices', 0),
                    'broken': campaign_info.get('broken', 0),
                    'redirected': campaign_info.get('redirected', 0),
                    'healthy': campaign_info.get('healthy', 0),
                    'blocked': campaign_info.get('blocked', 0),
                    'pages_crawled': campaign_info.get('pages_crawled', 0),
                    'have_issues': campaign_info.get('have_issues', 0)
                }
                
                logger.info(f"Successfully extracted audit info from info endpoint for project {project_id}")
                return combined_data
        
        # Fallback: try to get the latest completed snapshot if we don't have a valid one
        if not snapshot_id or snapshot_id == 'None':
            logger.info("No snapshot ID provided. Looking for the latest completed snapshot.")
            snapshots_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/snapshots"
            snapshots_url_with_key = f"{snapshots_url}?key={api_key}"
            
            snapshots_response = requests.get(snapshots_url_with_key)
            
            if snapshots_response.status_code == 200:
                snapshots_data = snapshots_response.json()
                
                # Look for completed snapshots
                for snapshot in snapshots_data.get('snapshots', []):
                    if 'finish_date' in snapshot:
                        snapshot_id = snapshot.get('snapshot_id')
                        logger.info(f"Found completed snapshot: {snapshot_id}")
                        break
                
                if not snapshot_id or snapshot_id == 'None':
                    logger.error("No completed snapshots found")
                    return None
            else:
                logger.error(f"Failed to get snapshots: {snapshots_response.status_code}")
                return None
        
        # Fallback: try meta/issues endpoint if info endpoint failed
        logger.info(f"Falling back to meta/issues for project {project_id} with snapshot {snapshot_id}")
        
        # Get static information about issue types
        issues_url = f"https://api.semrush.com/reports/v1/projects/{project_id}/siteaudit/meta/issues"
        url_with_key = f"{issues_url}?key={api_key[:5]}..." # Truncated for security
        
        logger.info(f"[DETAILED DEBUG] API Request URL: {url_with_key}")
        
        response = requests.get(f"{issues_url}?key={api_key}")
        
        logger.info(f"[DETAILED DEBUG] API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            issues_data = response.json()
            issue_count = len(issues_data.get('issues', []))
            
            logger.info(f"Retrieved {issue_count} issue types for project {project_id}")
            
            # Log a sample of the first few issues if available
            if 'issues' in issues_data and len(issues_data['issues']) > 0:
                sample_issues = issues_data['issues'][:3]  # First 3 issues as sample
                logger.info(f"Sample issues: {json.dumps(sample_issues, indent=2)}")
            else:
                logger.warning("No issues found in the meta/issues API response")
            
            return issues_data
        else:
            logger.error(f"Failed to get audit issues: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.exception(f"Error in get_audit_issues: {str(e)}")
        return None


def process_audit_issues(issues_data, domain):
    """
    Process audit issues into a structured format.
    
    Args:
        issues_data (dict): Raw issues data from SEMrush API
        domain (str): Website domain
    
    Returns:
        dict: Processed issues data
    """
    try:
        # Check if we're dealing with data from the info endpoint
        if issues_data.get('campaign_info') and issues_data.get('defects'):
            # Data is already in the right format from the info endpoint
            logger.info("Using pre-processed data from info endpoint")
            return issues_data
        
        # Otherwise, process data from the meta/issues endpoint
        # Extract the key information
        issues = issues_data.get('issues', [])
        
        # Count issues by type
        error_count = 0
        warning_count = 0
        notice_count = 0
        
        for issue in issues:
            severity = issue.get('severity', 'notice').lower()
            if severity == 'error':
                error_count += 1
            elif severity == 'warning':
                warning_count += 1
            else:
                notice_count += 1
        
        # Get the actual counts from the API response if available
        actual_error_count = issues_data.get('error_count', error_count)
        actual_warning_count = issues_data.get('warning_count', warning_count)
        actual_notice_count = issues_data.get('notice_count', notice_count)
        
        # Extract the top issue types for each category
        error_types = []
        warning_types = []
        notice_types = []
        
        # This is a simplified version
        for i, issue in enumerate(issues):
            title = issue.get('title', 'Unknown Issue')
            issue_id = issue.get('id', i)
            
            # Distribute issues based on severity or other criteria
            # This is just a simple example
            if i % 3 == 0 and len(error_types) < 5:
                error_types.append({'title': title, 'id': issue_id, 'count': 1})
            elif i % 3 == 1 and len(warning_types) < 5:
                warning_types.append({'title': title, 'id': issue_id, 'count': 1})
            elif i % 3 == 2 and len(notice_types) < 5:
                notice_types.append({'title': title, 'id': issue_id, 'count': 1})
        
        # Log the final counts straight from the API
        logger.info(f"Final counts from SEMrush API: {actual_error_count} errors, {actual_warning_count} warnings, {actual_notice_count} notices")
        
        # Get the API response keys for logging
        logger.info(f"Fallback: API Response keys: {list(issues_data.keys()) if isinstance(issues_data, dict) else 'Not a dict'}")
        
        # Direct mapping from API response fields to our data structure
        # Based on the actual API response structure shared by the user:
        # "scheme":"https","errors":21,"warnings":181,"notices":117,"broken":0,"brokenDelta":0,
        # "blocked":1,"blockedDelta":0,"redirected":67,"redirectedDelta":0,"healthy":1,
        # "healthyDelta":0,"haveIssues":22,"haveIssuesDelta":0
        
        # Create campaign_info and defects in the right format for database storage
        campaign_info = {
            'errors': actual_error_count,
            'warnings': actual_warning_count,
            'notices': actual_notice_count,
            'broken': issues_data.get('broken', 0),
            'blocked': issues_data.get('blocked', 0),
            'redirected': issues_data.get('redirected', 0),
            'healthy': issues_data.get('healthy', 0),
            'pages_crawled': issues_data.get('pages_crawled', 0),
            'pages_limit': issues_data.get('pages_limit', 0),
            'have_issues': issues_data.get('haveIssues', 0),
            'have_issues_delta': issues_data.get('haveIssuesDelta', 0),
            'quality': issues_data.get('quality', {}).get('value', 0)
        }
        
        logger.info(f"Fallback: Extracted campaign info: errors={campaign_info['errors']}, " +
                   f"warnings={campaign_info['warnings']}, notices={campaign_info['notices']}, " +
                   f"broken={campaign_info['broken']}, blocked={campaign_info['blocked']}, " +
                   f"redirected={campaign_info['redirected']}, healthy={campaign_info['healthy']}, " +
                   f"have_issues={campaign_info['have_issues']}")
        
        defects = {
            'errors': {
                'group': 'error',
                'severity': 8,
                'count': actual_error_count,
                'items': [{'id': err.get('id'), 'text': err.get('title', 'Error'), 'count': err.get('count', 1)} 
                          for err in error_types]
            },
            'warnings': {
                'group': 'warning',
                'severity': 5,
                'count': actual_warning_count,
                'items': [{'id': warn.get('id'), 'text': warn.get('title', 'Warning'), 'count': warn.get('count', 1)} 
                           for warn in warning_types]
            },
            'notices': {
                'group': 'notice',
                'severity': 3,
                'count': actual_notice_count,
                'items': [{'id': note.get('id'), 'text': note.get('title', 'Notice'), 'count': note.get('count', 1)} 
                          for note in notice_types]
            }
        }
        
        # Prepare the result in expected format
        processed_result = {
            'campaign_info': campaign_info,
            'defects': defects,
            'status': 'done',
            'snapshot_id': issues_data.get('snapshot_id', ''),
            'raw_info': issues_data,
            # Direct access fields for easier consumption
            'total_errors': campaign_info.get('errors', 0),
            'total_warnings': campaign_info.get('warnings', 0),
            'total_notices': campaign_info.get('notices', 0),
            'broken': campaign_info.get('broken', 0),
            'redirected': campaign_info.get('redirected', 0),
            'healthy': campaign_info.get('healthy', 0),
            'blocked': campaign_info.get('blocked', 0),
            'pages_crawled': campaign_info.get('pages_crawled', 0),
            'have_issues': campaign_info.get('have_issues', 0)
        }
        
        return processed_result
            
    except Exception as e:
        logger.exception(f"Error in process_audit_issues: {str(e)}")
        # Return a minimal valid structure to prevent downstream errors
        minimal_data = {
            'campaign_info': {
                'errors': 0,
                'warnings': 0,
                'notices': 0,
                'broken': 0,
                'blocked': 0,
                'redirected': 0,
                'healthy': 0,
                'pages_crawled': 0,
                'pages_limit': 0,
                'have_issues': 0,
                'have_issues_delta': 0
            },
            'defects': {
                'errors': {'group': 'error', 'severity': 8, 'count': 0, 'items': []},
                'warnings': {'group': 'warning', 'severity': 5, 'count': 0, 'items': []},
                'notices': {'group': 'notice', 'severity': 3, 'count': 0, 'items': []}
            },
            'status': 'error',
            'snapshot_id': '',
            'raw_info': {},
            # Direct access fields for easier consumption
            'total_errors': 0,
            'total_warnings': 0,
            'total_notices': 0,
            'broken': 0,
            'redirected': 0,
            'healthy': 0,
            'blocked': 0,
            'pages_crawled': 0,
            'have_issues': 0
        }
        
        logger.warning("Returning minimal error structure due to exception")
        return minimal_data