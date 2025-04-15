import logging
import json
import requests
from urllib.parse import urlparse
from flask import current_app
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Define Pydantic models for structured output parsing
class KeywordSuggestion(BaseModel):
    """Model for keyword suggestions."""
    keyword: str = Field(description="The suggested keyword")
    relevance: int = Field(description="Relevance score from 1-10, with 10 being most relevant")
    difficulty: int = Field(description="Difficulty score from 1-10, with 10 being most difficult")
    search_volume: str = Field(description="Estimated search volume")
    recommendation: str = Field(description="How to use this keyword")


class ContentSuggestion(BaseModel):
    """Model for content improvement suggestions."""
    section: str = Field(description="Which section of content this applies to")
    current_issues: List[str] = Field(description="Issues with the current content")
    suggested_improvements: List[str] = Field(description="Suggested improvements")
    example: str = Field(description="Example of improved content")


class MetaDataSuggestion(BaseModel):
    """Model for meta data suggestions."""
    title: str = Field(description="Suggested meta title")
    description: str = Field(description="Suggested meta description")
    reasoning: str = Field(description="Reasoning for these suggestions")


class ContentOptimizationResponse(BaseModel):
    """Model for the complete content optimization response."""
    summary: str = Field(description="Overall summary of content analysis")
    keywords: List[KeywordSuggestion] = Field(description="Keyword suggestions")
    content_improvements: List[ContentSuggestion] = Field(description="Content improvement suggestions")
    metadata: MetaDataSuggestion = Field(description="Meta data suggestions")
    additional_recommendations: List[str] = Field(description="Additional recommendations")


def fetch_page_content(url):
    """
    Fetch the content of a webpage.
    
    Args:
        url: URL of the webpage to fetch
        
    Returns:
        dict: Content data or None if failed
    """
    try:
        # Ensure the URL has a protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        # Make a request to the URL
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Return the page content and response metadata
        return {
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'content': response.text,
            'url': response.url
        }
    except Exception as e:
        logger.exception(f"Error fetching page content from {url}: {str(e)}")
        return None


def optimize_content(client, url, target_keywords=None):
    """
    Analyze and optimize webpage content using LangChain.
    
    Args:
        client: Client model instance
        url: URL of the page to optimize
        target_keywords: Optional list of target keywords
        
    Returns:
        dict: Content optimization suggestions
    """
    # Get OpenAI API key
    openai_api_key = current_app.config.get('OPENAI_API_KEY')
    if not openai_api_key:
        logger.error("OpenAI API key not found in configuration")
        return {
            'summary': "Unable to optimize content: OpenAI API key not configured.",
            'keywords': [],
            'content_improvements': [],
            'metadata': {},
            'additional_recommendations': []
        }
    
    try:
        # Fetch the page content
        page_data = fetch_page_content(url)
        if not page_data:
            return {
                'summary': f"Unable to optimize content: Failed to fetch page from {url}",
                'keywords': [],
                'content_improvements': [],
                'metadata': {},
                'additional_recommendations': []
            }
        
        # Initialize the LLM
        llm = ChatOpenAI(
            model="gpt-3.5-turbo-16k",  # Using a larger context model for content analysis
            temperature=0.2,
            openai_api_key=openai_api_key
        )
        
        # Setup the output parser
        parser = PydanticOutputParser(pydantic_object=ContentOptimizationResponse)
        
        # Extract domain information
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        path = parsed_url.path
        
        # Format target keywords if provided
        keywords_text = "No specific target keywords provided."
        if target_keywords and isinstance(target_keywords, list):
            keywords_text = "Target keywords: " + ", ".join(target_keywords)
        
        # Create a prompt template for content optimization
        template = """
        You are an expert SEO content optimizer. Analyze the content of the webpage at {url} and provide
        detailed recommendations to improve its SEO performance.
        
        WEBPAGE INFORMATION:
        URL: {url}
        Domain: {domain}
        Path: {path}
        
        TARGET KEYWORDS:
        {keywords_text}
        
        PAGE CONTENT (HTML):
        ```html
        {page_content}
        ```
        
        Based on this content, provide comprehensive SEO content optimization recommendations including:
        
        1. Keyword analysis and suggestions
        2. Content improvement recommendations for each major section
        3. Meta title and description optimization
        4. Additional recommendations for improving search visibility
        
        Focus on both on-page content quality and search engine optimization best practices.
        
        {format_instructions}
        """
        
        # Create format instructions from the output parser
        format_instructions = parser.get_format_instructions()
        
        # Create the prompt with input variables
        prompt = PromptTemplate(
            template=template,
            input_variables=["url", "domain", "path", "keywords_text", "page_content"],
            partial_variables={"format_instructions": format_instructions}
        )
        
        # Create and run the chain
        chain = LLMChain(llm=llm, prompt=prompt)
        
        # Execute the chain with our inputs
        # Limit page content to avoid token limits (first 10000 characters)
        page_content = page_data['content'][:10000]
        
        result = chain.run(
            url=url,
            domain=domain,
            path=path,
            keywords_text=keywords_text,
            page_content=page_content
        )
        
        # Parse the result into our Pydantic model
        parsed_result = parser.parse(result)
        
        # Format the optimization suggestions for storage/return
        formatted_optimization = {
            'summary': parsed_result.summary,
            'keywords': [kw.dict() for kw in parsed_result.keywords],
            'content_improvements': [ci.dict() for ci in parsed_result.content_improvements],
            'metadata': parsed_result.metadata.dict() if parsed_result.metadata else {},
            'additional_recommendations': parsed_result.additional_recommendations
        }
        
        return formatted_optimization
    
    except Exception as e:
        logger.exception(f"Error optimizing content: {str(e)}")
        return {
            'summary': f"Error optimizing content: {str(e)}",
            'keywords': [],
            'content_improvements': [],
            'metadata': {},
            'additional_recommendations': []
        }