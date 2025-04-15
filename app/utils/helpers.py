import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)

def get_comparison_data(previous_analysis, current_analysis):
    """
    Compare the current analysis with the previous one and generate comparison data.
    
    Args:
        previous_analysis: Previous site analysis
        current_analysis: Current site analysis
    
    Returns:
        dict: Comparison data with changes and trends
    """
    if not previous_analysis or not current_analysis:
        return {
            'has_previous': False,
            'comparison': {}
        }
    
    try:
        # Calculate changes in key metrics
        error_change = current_analysis.total_errors - previous_analysis.total_errors
        warning_change = current_analysis.total_warnings - previous_analysis.total_warnings
        notice_change = current_analysis.total_notices - previous_analysis.total_notices
        
        # Calculate percentage changes
        error_percent = calculate_percent_change(previous_analysis.total_errors, current_analysis.total_errors)
        warning_percent = calculate_percent_change(previous_analysis.total_warnings, current_analysis.total_warnings)
        notice_percent = calculate_percent_change(previous_analysis.total_notices, current_analysis.total_notices)
        
        # Determine trends (improving, worsening, stable)
        error_trend = 'stable' if error_change == 0 else ('improving' if error_change < 0 else 'worsening')
        warning_trend = 'stable' if warning_change == 0 else ('improving' if warning_change < 0 else 'worsening')
        notice_trend = 'stable' if notice_change == 0 else ('improving' if notice_change < 0 else 'worsening')
        
        # Calculate days between analyses
        days_between = (current_analysis.analysis_date - previous_analysis.analysis_date).days
        
        # Build comparison data
        comparison = {
            'has_previous': True,
            'comparison': {
                'previous_date': previous_analysis.analysis_date.strftime('%Y-%m-%d'),
                'current_date': current_analysis.analysis_date.strftime('%Y-%m-%d'),
                'days_between': days_between,
                'errors': {
                    'previous': previous_analysis.total_errors,
                    'current': current_analysis.total_errors,
                    'change': error_change,
                    'percent_change': error_percent,
                    'trend': error_trend
                },
                'warnings': {
                    'previous': previous_analysis.total_warnings,
                    'current': current_analysis.total_warnings,
                    'change': warning_change,
                    'percent_change': warning_percent,
                    'trend': warning_trend
                },
                'notices': {
                    'previous': previous_analysis.total_notices,
                    'current': current_analysis.total_notices,
                    'change': notice_change,
                    'percent_change': notice_percent,
                    'trend': notice_trend
                }
            }
        }
        
        return comparison
        
    except Exception as e:
        logger.exception(f"Error generating comparison data: {str(e)}")
        return {
            'has_previous': False,
            'comparison': {},
            'error': str(e)
        }


def calculate_percent_change(old_value, new_value):
    """
    Calculate the percentage change between two values.
    
    Args:
        old_value: Previous value
        new_value: Current value
    
    Returns:
        float: Percentage change, or 0 if old_value is 0
    """
    if old_value == 0:
        return 0 if new_value == 0 else 100  # 100% increase if starting from 0
    
    return ((new_value - old_value) / old_value) * 100


def group_errors_by_category(errors):
    """
    Group errors by their category.
    
    Args:
        errors: List of AnalysisError objects
    
    Returns:
        dict: Dictionary with category as key and list of errors as value
    """
    if not errors:
        return {}
    
    grouped = {}
    for error in errors:
        category = error.category or 'Uncategorized'
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(error)
    
    return grouped


def format_date(date):
    """
    Format a datetime object to a readable string.
    
    Args:
        date: Datetime object
    
    Returns:
        str: Formatted date string
    """
    if not date:
        return ""
    
    return date.strftime('%Y-%m-%d %H:%M:%S')


def safe_json_loads(json_str, default=None):
    """
    Safely load a JSON string.
    
    Args:
        json_str: JSON string to load
        default: Default value to return if JSON loading fails
    
    Returns:
        dict/list: Loaded JSON data or default value
    """
    if not json_str:
        return default if default is not None else {}
    
    try:
        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Error loading JSON: {str(e)}")
        return default if default is not None else {}