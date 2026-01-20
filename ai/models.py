"""
ai/models.py - Pydantic Data Models for AI Search

This module defines the data structures used throughout the AI search system:
- UserRecord: Represents a user returned from search results
- UserQueryFilters: Parsed filters extracted from natural language queries
- FilteredResult: Complete search response with pagination and metadata
"""

from typing import List, Optional
from pydantic import BaseModel


class UserRecord(BaseModel):
    """
    Represents a user record returned from search results.

    This is a simplified view of the User model, containing only
    the fields needed for display in search results.
    """
    id: int
    full_name: str
    username: str
    gender: str
    profile_pic: Optional[str] = None


class UserQueryFilters(BaseModel):
    """
    Structured filters extracted from natural language queries.

    The AI parser converts user queries like "show female users named Taylor"
    into these structured filters.

    Attributes:
        gender: Filter by gender ("Male", "Female", "Other", or None)
        name_substr: Substring to search in user names
        starts_with_mode: If True, name_substr matches only at start of name
        name_length_parity: Filter by odd/even name length
        has_profile_pic: True = has pic, False = no pic, None = don't filter
        sort_by: Field to sort by (name_length, username_length, name, etc.)
        sort_order: Sort direction ("asc" or "desc")
        query_understood: False if query couldn't be meaningfully parsed
        parse_warnings: Warnings about unsupported features
    """
    gender: Optional[str] = None
    name_substr: Optional[str] = None
    starts_with_mode: bool = False
    name_length_parity: Optional[str] = None  # "odd" or "even"
    has_profile_pic: Optional[bool] = None
    sort_by: Optional[str] = None  # "name_length", "username_length", "name", "username", "created_at"
    sort_order: str = "desc"  # "asc" or "desc"
    query_understood: bool = True
    parse_warnings: list = []


class FilteredResult(BaseModel):
    """
    Complete search response including results and metadata.

    This is the return type of the main filter_records_ai() function,
    containing search results along with pagination info and parse feedback.

    Attributes:
        results: List of matching user records
        total_count: Total matches (for pagination)
        query_understood: Whether the query was successfully parsed
        parse_warnings: Any warnings from parsing
        filters_applied: Human-readable description of applied filters
    """
    results: List[UserRecord]
    total_count: int = 0
    query_understood: bool = True
    parse_warnings: list = []
    filters_applied: Optional[dict] = None
