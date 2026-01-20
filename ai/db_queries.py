"""
ai/db_queries.py - Database Query Functions for AI Search

This module handles all database interactions for AI-powered search:
- Applying filters to SQLAlchemy queries
- Applying sorting options
- Building filter descriptions for user feedback
- Main filter_records_ai function that orchestrates the search

The module uses SQLAlchemy for database operations and integrates
with the AI query parser module.
"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from ai.models import UserRecord, UserQueryFilters, FilteredResult
from ai.query_parser import parse_query_ai

logger = logging.getLogger(__name__)

# ==============================================================================
# FILTER APPLICATION
# ==============================================================================


def _apply_filters(query, filters: UserQueryFilters, models):
    """
    Apply all filters to the SQLAlchemy query.

    Args:
        query: SQLAlchemy query object
        filters: Parsed query filters
        models: Models module reference

    Returns:
        Modified query with filters applied
    """
    if filters.gender:
        query = query.filter(models.User.gender == filters.gender)

    if filters.name_substr:
        name_str = str(filters.name_substr)
        pattern = f"{name_str}%" if filters.starts_with_mode else f"%{name_str}%"
        query = query.filter(models.User.full_name.ilike(pattern))

    if filters.name_length_parity:
        name_without_spaces = func.replace(models.User.full_name, ' ', '')
        name_length = func.length(name_without_spaces)
        remainder = 1 if filters.name_length_parity == "odd" else 0
        query = query.filter(name_length % 2 == remainder)

    if filters.has_profile_pic is True:
        query = query.filter(models.User.profile_pic.isnot(None))
        query = query.filter(models.User.profile_pic != '')
    elif filters.has_profile_pic is False:
        query = query.filter(
            (models.User.profile_pic.is_(None)) | (models.User.profile_pic == '')
        )

    return query


def _apply_sorting(query, filters: UserQueryFilters, models):
    """
    Apply sorting to the SQLAlchemy query.

    Args:
        query: SQLAlchemy query object
        filters: Parsed query filters
        models: Models module reference

    Returns:
        Modified query with sorting applied
    """
    if not filters.sort_by:
        return query

    from sqlalchemy import desc, asc
    order_func = desc if filters.sort_order == "desc" else asc

    sort_columns = {
        "name_length": func.length(func.replace(models.User.full_name, ' ', '')),
        "username_length": func.length(models.User.username),
        "name": models.User.full_name,
        "username": models.User.username,
        "created_at": models.User.created_at,
    }

    column = sort_columns.get(filters.sort_by)
    if column is not None:
        query = query.order_by(order_func(column))

    return query


# ==============================================================================
# DATABASE QUERY
# ==============================================================================


def query_users(db: Session, filters: UserQueryFilters, limit: int = 20, skip: int = 0) -> tuple:
    """
    Query users from database using SQLAlchemy with pagination.

    Args:
        db: Database session
        filters: Query filters
        limit: Maximum number of results per page
        skip: Number of results to skip (for pagination)

    Returns:
        Tuple of (List of UserRecord objects, total count of matching records)
    """
    import models

    query = db.query(models.User)
    query = _apply_filters(query, filters, models)
    query = _apply_sorting(query, filters, models)

    logger.debug("Query filters: %s", filters.model_dump())

    try:
        # Get total count BEFORE applying limit/offset
        total_count = query.count()

        # Apply pagination
        query = query.offset(skip).limit(limit)

        results = query.all()
        logger.info(f"Found {len(results)} users (total matching: {total_count})")

        user_records = [
            UserRecord(
                id=user.id,
                full_name=user.full_name,
                username=user.username,
                gender=user.gender,
                profile_pic=user.profile_pic
            )
            for user in results
        ]

        return user_records, total_count

    except Exception as exc:
        logger.error(f"Database error querying users: {exc}")
        raise


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def _format_sort_label(sort_by: str, sort_order: str) -> str:
    """Format sort criteria into human-readable label."""
    sort_labels = {
        "name_length": "name length",
        "username_length": "username length",
        "name": "name",
        "username": "username",
        "created_at": "creation date"
    }

    if sort_by in ["name", "username"]:
        order_label = "Z-A" if sort_order == "desc" else "A-Z"
    elif sort_by == "created_at":
        order_label = "newest first" if sort_order == "desc" else "oldest first"
    else:
        order_label = "longest first" if sort_order == "desc" else "shortest first"

    return f"{sort_labels.get(sort_by, sort_by)} ({order_label})"


def build_filters_applied(filters: UserQueryFilters) -> Optional[dict]:
    """
    Build a human-readable dictionary of applied filters for transparency.

    Args:
        filters: The parsed query filters

    Returns:
        Dictionary describing applied filters, or None if no filters applied
    """
    filters_applied = {}

    if filters.gender:
        filters_applied["gender"] = filters.gender

    if filters.name_substr:
        key = "name_starts_with" if filters.starts_with_mode else "name_contains"
        filters_applied[key] = filters.name_substr

    if filters.name_length_parity:
        filters_applied["name_length"] = f"{filters.name_length_parity} number of letters"

    if filters.has_profile_pic is True:
        filters_applied["profile_picture"] = "has profile picture"
    elif filters.has_profile_pic is False:
        filters_applied["profile_picture"] = "no profile picture"

    if filters.sort_by:
        filters_applied["sorted_by"] = _format_sort_label(filters.sort_by, filters.sort_order)

    return filters_applied if filters_applied else None


# ==============================================================================
# MAIN FILTER FUNCTION
# ==============================================================================


async def filter_records_ai(
        db: Session,
        user_query: str,
        batch_size: int = 20,
        skip: int = 0
) -> FilteredResult:
    """
    Main function to filter users based on natural language query.

    This is the primary entry point for AI-powered search. It:
    1. Parses the natural language query into filters using AI
    2. Queries the database with those filters

    Args:
        db: Database session
        user_query: Natural language search query
        batch_size: Maximum number of results per page
        skip: Number of results to skip (for pagination)

    Returns:
        FilteredResult with users and pagination info
    """
    # Parse query using AI
    filters = await parse_query_ai(user_query)

    # Query database with pagination
    db_results, total_count = query_users(db, filters, limit=batch_size, skip=skip)

    return FilteredResult(
        results=db_results,
        total_count=total_count,
        query_understood=filters.query_understood,
        parse_warnings=filters.parse_warnings,
        filters_applied=build_filters_applied(filters)
    )
