import logging
import json
from flask import current_app
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Define Pydantic models for structured output parsing
class SEOAction(BaseModel):
    """Model for a specific SEO action recommendation."""
    title: str = Field(description="A brief title for the action")
    description: str = Field(description="Detailed description of what to do")
    implementation_steps: List[str] = Field(description="Step-by-step implementation guide")
    expected_outcome: str = Field(description="What to expect after implementing this action")
    time_estimate: str = Field(description="Estimated time to implement (e.g., '2-3 hours', '1 day')")
    expertise_required: str = Field(description="Level of expertise required (Beginner, Intermediate, Advanced)")


class RecommendationSet(BaseModel):
    """Model for a complete set of recommendations."""
    high_priority: List[SEOAction] = Field(description="High priority actions that should be implemented immediately")
    medium_priority: List[SEOAction] = Field(description="Medium priority actions to implement after high priority items")
    low_priority: List[SEOAction] = Field(description="Lower priority actions that would still provide benefit")
    summary: str = Field(description="Executive summary of the recommendations")


def generate_recommendations(client, analysis, analysis_data):
    """
    Generate actionable SEO recommendations using LangChain.
    
    Args:
        client: Client model instance
        analysis: SiteAnalysis model instance
        analysis_data: Raw analysis data from SEMrush
        
    Returns:
        dict: Structured recommendations
    """
    # Get OpenAI API key
    openai_api_key = current_app.config.get('OPENAI_API_KEY')
    if not openai_api_key:
        logger.error("OpenAI API key not found in configuration")
        # Return placeholder data if no API key is available
        return {
            'summary': "Unable to generate recommendations: OpenAI API key not configured.",
            'high_priority': [],
            'medium_priority': [],
            'low_priority': []
        }
    
    try:
        # Initialize the LLM
        llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.2,
            openai_api_key=openai_api_key
        )
        
        # Setup the output parser
        parser = PydanticOutputParser(pydantic_object=RecommendationSet)
        
        # Prepare the data for the prompt
        website = client.website
        total_errors = analysis.total_errors
        total_warnings = analysis.total_warnings
        total_notices = analysis.total_notices
        
        # Extract issues from analysis_data
        issues = analysis_data.get('issues', [])
        # Limit to top 10 issues to avoid token limits
        top_issues = issues[:10] if len(issues) > 10 else issues
        
        # Get the summary and insights from the analysis
        analysis_summary = analysis.summary if analysis.summary else "No summary available."
        analysis_insights = analysis.insights if analysis.insights else "No insights available."
        
        # Create a prompt template for SEO recommendations
        template = """
        You are an expert SEO consultant tasked with developing an actionable plan to improve the SEO performance
        of {website}. Based on the analysis results, provide specific, detailed recommendations.
        
        ANALYSIS SUMMARY:
        {analysis_summary}
        
        KEY INSIGHTS:
        {analysis_insights}
        
        CURRENT SEO METRICS:
        - Total errors: {total_errors}
        - Total warnings: {total_warnings}
        - Total notices: {total_notices}
        
        TOP ISSUES IDENTIFIED:
        {top_issues}
        
        Based on this data, develop a comprehensive set of recommendations that will help improve the website's SEO performance.
        Organize recommendations into high, medium, and low priority categories. For each recommendation, provide:
        
        1. A clear title
        2. Detailed description
        3. Step-by-step implementation instructions
        4. Expected outcome
        5. Time estimate for implementation
        6. Required expertise level
        
        Ensure all recommendations are specific, actionable, and tailored to the website's needs.
        
        {format_instructions}
        """
        
        # Create format instructions from the output parser
        format_instructions = parser.get_format_instructions()
        
        # Format top issues for the prompt
        formatted_issues = json.dumps(top_issues)
        
        # Create the prompt with input variables
        prompt = PromptTemplate(
            template=template,
            input_variables=["website", "analysis_summary", "analysis_insights", 
                             "total_errors", "total_warnings", "total_notices", "top_issues"],
            partial_variables={"format_instructions": format_instructions}
        )
        
        # Create and run the chain
        chain = LLMChain(llm=llm, prompt=prompt)
        
        # Execute the chain with our inputs
        result = chain.run(
            website=website,
            analysis_summary=analysis_summary,
            analysis_insights=analysis_insights,
            total_errors=total_errors,
            total_warnings=total_warnings,
            total_notices=total_notices,
            top_issues=formatted_issues
        )
        
        # Parse the result into our Pydantic model
        parsed_result = parser.parse(result)
        
        # Format the recommendations for storage
        formatted_recommendations = {
            'summary': parsed_result.summary,
            'high_priority': [action.dict() for action in parsed_result.high_priority],
            'medium_priority': [action.dict() for action in parsed_result.medium_priority],
            'low_priority': [action.dict() for action in parsed_result.low_priority]
        }
        
        return formatted_recommendations
    
    except Exception as e:
        logger.exception(f"Error generating recommendations: {str(e)}")
        return {
            'summary': f"Error generating recommendations: {str(e)}",
            'high_priority': [],
            'medium_priority': [],
            'low_priority': []
        }