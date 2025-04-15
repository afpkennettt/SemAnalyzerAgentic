import logging
import os
from flask import current_app
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def get_llm(model_name="gpt-3.5-turbo", temperature=0.2):
    """
    Get a Language Model instance using LangChain.
    
    Args:
        model_name (str): Name of the OpenAI model to use
        temperature (float): Temperature parameter for generation
        
    Returns:
        ChatOpenAI: LLM instance or None if no API key is available
    """
    # Get OpenAI API key
    openai_api_key = current_app.config.get('OPENAI_API_KEY')
    if not openai_api_key:
        logger.error("OpenAI API key not found in configuration")
        return None
    
    # Initialize the LLM
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        openai_api_key=openai_api_key
    )


def create_chain(prompt_template, input_variables, partial_variables=None, model_name="gpt-3.5-turbo", temperature=0.2):
    """
    Create a LangChain for running LLM queries.
    
    Args:
        prompt_template (str): Template string for the prompt
        input_variables (list): List of input variable names in the template
        partial_variables (dict, optional): Dictionary of variables that will be partially filled in the prompt
        model_name (str): Name of the OpenAI model to use
        temperature (float): Temperature parameter for generation
        
    Returns:
        LLMChain: The created chain or None if failed
    """
    llm = get_llm(model_name, temperature)
    if not llm:
        return None
    
    try:
        # Create the prompt with input variables
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=input_variables,
            partial_variables=partial_variables or {}
        )
        
        # Create and return the chain
        return LLMChain(llm=llm, prompt=prompt)
    
    except Exception as e:
        logger.exception(f"Error creating LangChain: {str(e)}")
        return None


def run_chat_query(query, context=None, model_name="gpt-3.5-turbo"):
    """
    Run a simple chat query with the LLM.
    
    Args:
        query (str): The query to send to the model
        context (str, optional): Additional context to include
        model_name (str): Name of the OpenAI model to use
        
    Returns:
        str: The model's response or an error message
    """
    llm = get_llm(model_name, temperature=0.7)  # Higher temperature for more conversational responses
    if not llm:
        return "Unable to process query: OpenAI API key not configured."
    
    try:
        # Create prompt based on whether context is provided
        if context:
            prompt_template = """
            You are an expert SEO consultant helping with website analysis.
            
            CONTEXT:
            {context}
            
            USER QUERY:
            {query}
            
            Please provide a helpful, professional response based on the context and your SEO expertise.
            """
            
            # Create chain with context
            chain = create_chain(
                prompt_template=prompt_template,
                input_variables=["context", "query"],
                model_name=model_name,
                temperature=0.7
            )
            
            # Run the chain
            return chain.run(context=context, query=query)
        else:
            prompt_template = """
            You are an expert SEO consultant helping with website analysis.
            
            USER QUERY:
            {query}
            
            Please provide a helpful, professional response based on your SEO expertise.
            """
            
            # Create chain without context
            chain = create_chain(
                prompt_template=prompt_template,
                input_variables=["query"],
                model_name=model_name,
                temperature=0.7
            )
            
            # Run the chain
            return chain.run(query=query)
    
    except Exception as e:
        logger.exception(f"Error running chat query: {str(e)}")
        return f"Error processing your query: {str(e)}"