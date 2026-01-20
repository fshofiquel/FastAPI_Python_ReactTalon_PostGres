"""
ai - AI-Powered Natural Language Search Package

This package provides natural language search capabilities for the user
management system. It converts human-readable queries like "show me female
users named Taylor" into structured database filters.

Architecture:
    User Query -> AI Parsing (Ollama LLM) -> SQL Filters

All queries are processed directly by the AI (Ollama LLM) which converts
natural language into structured filters. The AI handles synonyms,
abbreviations, typos, and complex query patterns.

Modules:
    - models: Pydantic data models (UserRecord, UserQueryFilters, FilteredResult)
    - llm: LLM integration with Ollama API
    - query_parser: AI-based query parsing
    - db_queries: Database query functions

Main exports:
    - filter_records_ai: Main search function
    - chat_completion: Direct LLM chat
    - close_http_client: Cleanup function
"""

# Re-export main functions
from ai.llm import chat_completion, close_http_client, warmup_model
from ai.db_queries import filter_records_ai
from ai.models import UserRecord, UserQueryFilters, FilteredResult
from ai.query_parser import parse_query_ai

__all__ = [
    # Main functions
    "filter_records_ai",
    "chat_completion",
    "parse_query_ai",
    # Lifecycle
    "close_http_client",
    "warmup_model",
    # Models
    "UserRecord",
    "UserQueryFilters",
    "FilteredResult",
]
