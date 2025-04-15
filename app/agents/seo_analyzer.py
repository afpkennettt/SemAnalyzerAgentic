import logging
import json
from datetime import datetime
from flask import current_app
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Define Pydantic models for structured output parsing
class SEOInsight(BaseModel):
    """Model for SEO insights from analysis."""
    insight: str = Field(description="The specific insight about the SEO issue")
    impact: str = Field(description="The potential impact of this issue on website performance")
    priority: int = Field(description="Priority level from 1-10, with 10 being highest priority")


class SEORecommendation(BaseModel):
    """Model for SEO recommendations."""
    recommendation: str = Field(description="Specific recommendation to improve SEO")
    rationale: str = Field(description="Why this recommendation is important")
    effort: str = Field(description="Estimated effort to implement (Low, Medium, High)")
    expected_impact: str = Field(description="Expected impact of implementing this recommendation")


class SiteAnalysisResponse(BaseModel):
    """Model for the complete site analysis response."""
    summary: str = Field(description="Overall summary of the site analysis")
    insights: List[SEOInsight] = Field(description="List of key insights from the analysis")
    recommendations: List[SEORecommendation] = Field(description="List of recommendations based on the analysis")
    error_impacts: Dict[str, str] = Field(description="Map of error IDs to impact descriptions")
    error_solutions: Dict[str, str] = Field(description="Map of error IDs to solution descriptions")


def generate_insights(website, errors=0, warnings=0, notices=0, broken=0, redirected=0, healthy=0, raw_data=None):
    """
    Generate AI-driven insights from SEO analysis data using LangChain.
    
    Args:
        website (str): The website URL
        errors (int): Number of errors
        warnings (int): Number of warnings
        notices (int): Number of notices
        broken (int): Number of broken pages
        redirected (int): Number of redirected pages
        healthy (int): Number of healthy pages
        raw_data (dict, optional): Raw analysis data from SEMrush
        
    Returns:
        dict: AI-generated insights, recommendations, and summary
    """
    # Get OpenAI API key from environment variable
    import os
    openai_api_key = os.environ.get('OPENAI_API_KEY')
    if not openai_api_key:
        logger.error("OpenAI API key not found in environment variables")
        # If API key is not available, prompt the user to add one
        return {
            'summary': "OpenAI API key required for AI-driven insights",
            'insights': "To generate intelligent insights from your SEO data, please add your OpenAI API key in the settings page.",
            'recommendations': "After adding your OpenAI API key, you'll be able to get detailed recommendations for improving your website's SEO performance.",
            'error_impacts': {},
            'error_solutions': {}
        }
    
    try:
        # Initialize the LLM
        llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.2,
            openai_api_key=openai_api_key
        )
        
        # Setup the output parser
        parser = PydanticOutputParser(pydantic_object=SiteAnalysisResponse)
        
        # Prepare the data for the prompt
        total_errors = errors
        total_warnings = warnings
        total_notices = notices
        
        # Extract key issues from raw_data if available
        issues = []
        error_types = []
        warning_types = []
        notice_types = []
        
        if raw_data:
            issues = raw_data.get('issues', [])
            error_types = raw_data.get('details', {}).get('error_types', [])
            warning_types = raw_data.get('details', {}).get('warning_types', [])
            notice_types = raw_data.get('details', {}).get('notice_types', [])
        
        # No comparison data in this simplified version
        comparison_data = "No previous analysis data available for comparison."
        
        # Create a prompt template for SEO analysis insights
        template = """
        You are an expert SEO consultant analyzing website performance data. Your task is to provide professional, 
        data-driven insights and recommendations based on the SEO analysis results for {website}.
        
        CURRENT ANALYSIS RESULTS:
        - Total errors: {total_errors}
        - Total warnings: {total_warnings}
        - Total notices: {total_notices}
        
        COMPARISON WITH PREVIOUS ANALYSIS:
        {comparison_data}
        
        TOP ISSUES BY CATEGORY:
        Error types: {error_types}
        Warning types: {warning_types}
        Notice types: {notice_types}
        
        DETAILED ISSUES (sample):
        {issues_sample}
        
        Based on this data, provide:
        1. A concise summary of the website's SEO health
        2. Key insights identified from the analysis
        3. Specific, actionable recommendations to improve SEO performance
        4. For the top issues, provide impact descriptions and solution recommendations
        
        {format_instructions}
        """
        
        # Create format instructions from the output parser
        format_instructions = parser.get_format_instructions()
        
        # Prepare a sample of issues (limit to avoid token limits)
        issues_sample = json.dumps(issues[:5] if len(issues) > 5 else issues)
        
        # Add additional context about the website
        site_info = f"""
        Website details:
        - URL: {website}
        - Pages with issues: {broken + redirected}
        - Healthy pages: {healthy}
        """
        
        # Create the prompt with input variables
        prompt = PromptTemplate(
            template=template,
            input_variables=["website", "total_errors", "total_warnings", "total_notices", 
                             "comparison_data", "error_types", "warning_types", "notice_types", "issues_sample"],
            partial_variables={"format_instructions": format_instructions}
        )
        
        # Create and run the chain
        chain = LLMChain(llm=llm, prompt=prompt)
        
        # Execute the chain with our inputs
        result = chain.run(
            website=website,
            total_errors=total_errors,
            total_warnings=total_warnings,
            total_notices=total_notices,
            comparison_data=comparison_data,
            error_types=error_types,
            warning_types=warning_types,
            notice_types=notice_types,
            issues_sample=issues_sample
        )
        
        # Parse the result into our Pydantic model
        parsed_result = parser.parse(result)
        
        # Convert insights and recommendations to formatted strings
        insights_text = ""
        for i, insight in enumerate(parsed_result.insights):
            insights_text += f"Insight {i+1}: {insight.insight}\n"
            insights_text += f"Impact: {insight.impact}\n"
            insights_text += f"Priority: {insight.priority}/10\n\n"
        
        recommendations_text = ""
        for i, rec in enumerate(parsed_result.recommendations):
            recommendations_text += f"Recommendation {i+1}: {rec.recommendation}\n"
            recommendations_text += f"Rationale: {rec.rationale}\n"
            recommendations_text += f"Effort: {rec.effort}\n"
            recommendations_text += f"Expected Impact: {rec.expected_impact}\n\n"
        
        # Return the structured data
        return {
            'summary': parsed_result.summary,
            'insights': insights_text,
            'recommendations': recommendations_text,
            'error_impacts': parsed_result.error_impacts,
            'error_solutions': parsed_result.error_solutions
        }
    
    except Exception as e:
        logger.exception(f"Error generating insights: {str(e)}")
        return {
            'summary': f"Error generating insights: {str(e)}",
            'insights': "",
            'recommendations': "",
            'error_impacts': {},
            'error_solutions': {}
        }