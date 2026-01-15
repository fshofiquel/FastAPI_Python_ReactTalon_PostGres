"""
ai - AI-Powered Natural Language Search Package

This package provides natural language search capabilities for the user
management system. It converts human-readable queries like "show me female
users named Taylor" into structured database filters.

Architecture:
    User Query -> Query Normalization -> Cache Check -> AI Parsing -> SQL Filters

The package uses a 3-tier approach for query processing:
    1. CACHE LOOKUP: Check Redis, in-memory, and file-based caches
    2. PATTERN MATCHING: Use regex patterns for common queries
    3. AI PARSING: Use Ollama LLM for complex queries

Modules:
    - models: Pydantic data models (UserRecord, UserQueryFilters, FilteredResult)
    - cache: Multi-layer caching system (Redis, memory, file)
    - llm: LLM integration with Ollama API
    - detectors: Query pattern detection functions
    - query_parser: Query parsing orchestration
    - db_queries: Database query functions

Main exports:
    - filter_records_ai: Main search function
    - chat_completion: Direct LLM chat
    - clear_all_caches: Cache management
    - close_http_client: Cleanup function
"""

# Re-export main functions for backward compatibility
from ai.llm import chat_completion, close_http_client
from ai.cache import clear_all_caches, get_cache_stats
from ai.db_queries import filter_records_ai
from ai.models import UserRecord, UserQueryFilters, FilteredResult
from ai.query_parser import parse_query_ai, normalize_query

__all__ = [
    # Main functions
    "filter_records_ai",
    "chat_completion",
    "parse_query_ai",
    # Cache management
    "clear_all_caches",
    "get_cache_stats",
    # Cleanup
    "close_http_client",
    # Models
    "UserRecord",
    "UserQueryFilters",
    "FilteredResult",
    # Utilities
    "normalize_query",
]
