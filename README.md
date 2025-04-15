# SemAnalyzerAgentic

An advanced AI-powered SEO monitoring and analysis platform that combines SEMrush API data with LangChain and LLM capabilities to provide intelligent insights and recommendations.

## Features

- **AI-Driven SEO Analysis**: Utilize LangChain and OpenAI to generate intelligent insights from SEMrush data
- **Autonomous Agents**: Task-specific agents for analysis, recommendations, and content optimization
- **Natural Language Interface**: Ask questions about your SEO performance in plain English
- **Comprehensive Reports**: Detailed analysis with actionable recommendations
- **Content Optimization**: AI-powered suggestions for improving page content
- **Automated Monitoring**: Scheduled analysis of your websites

## Technology Stack

- **Backend**: Python, Flask
- **Database**: PostgreSQL
- **AI/ML**: LangChain, OpenAI GPT models
- **Data Source**: SEMrush API
- **Visualization**: Chart.js
- **Frontend**: Bootstrap, HTML/CSS, JavaScript

## Getting Started

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up the environment variables:
   - `DATABASE_URL`: PostgreSQL connection string
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `SEMRUSH_API_KEY`: Your SEMrush API key
   - `SESSION_SECRET`: Secret key for Flask sessions

4. Run the application:
   ```
   python main.py
   ```

## Architecture

The application is built with an agent-based architecture:

- **SEO Analyzer Agent**: Analyzes SEMrush data and generates insights
- **Recommendation Engine Agent**: Creates actionable recommendations
- **Content Optimizer Agent**: Suggests improvements for webpage content

All agents utilize LangChain for orchestration and OpenAI models for intelligence.

## API Documentation

The application provides both a web interface and REST API endpoints for integration:

- `/api/health`: Health check endpoint
- `/api/clients`: Client management
- `/api/analyses`: Analysis results
- `/api/chat`: Natural language interaction

## License

MIT