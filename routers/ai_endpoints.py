"""
routers/ai_endpoints.py - AI-Powered Search Endpoints

Endpoints for AI functionality:
- POST /ai/test: Test AI connection
- POST /ai/cache/clear: Clear query caches
- GET /ai/search: AI-powered user search
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ai import chat_completion, filter_records_ai, clear_all_caches
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post(
    "/test",
    summary="Test AI connection",
    description="Test the connection to the AI model"
)
async def test_ai(
        prompt: str = Query(..., description="Prompt to send to the AI", examples=["Hello, how are you?"])
):
    """Test endpoint for AI functionality"""
    try:
        response = await chat_completion(prompt)
        return {
            "input": prompt,
            "output": response,
            "status": "success"
        }
    except Exception as exc:
        logger.error(f"AI test failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"AI service error: {str(exc)}"
        )


@router.post(
    "/cache/clear",
    tags=["System"],
    summary="Clear AI query cache",
    description="Clear all cached query results to force fresh parsing"
)
async def clear_ai_cache():
    """
    Clear all AI query caches (in-memory, Redis, and file).

    This endpoint clears all three cache layers:
    1. In-memory cache: Python dict, fastest
    2. Redis cache: Distributed cache (if available)
    3. File cache: Persistent JSON file

    Use cases:
    - After updating query parsing logic
    - During development to test query parsing
    - Troubleshooting cache-related issues
    """
    try:
        result = clear_all_caches()
        return {
            "status": "success",
            "cleared": result
        }
    except Exception as exc:
        logger.error(f"Cache clear failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {str(exc)}"
        )


@router.get(
    "/search",
    tags=["Users"],
    summary="AI-powered user search",
    description="Search users using natural language queries with pagination"
)
async def ai_search_users(
        query: str = Query(
            ...,
            description="Natural language search query",
            examples=["female users with Taylor in their name"]
        ),
        skip: int = Query(
            0,
            description="Number of results to skip (for pagination)",
            ge=0
        ),
        limit: int = Query(
            50,
            description="Maximum number of results per page",
            ge=1,
            le=200
        ),
        enable_ranking: bool = Query(
            False,
            description="Enable AI-based result ranking (slower)"
        ),
        db: Session = Depends(get_db)
):
    """
    AI-powered search/filter for users based on natural language query.

    Examples:
    - "female users with Taylor"
    - "users starting with J"
    - "list all male"
    - "users named Jordan"
    - "users with odd number of letters in their name"

    Supports pagination with skip and limit parameters.
    """
    try:
        result = await filter_records_ai(
            db, query, batch_size=limit, skip=skip, enable_ranking=enable_ranking
        )

        # Build response message
        if not result.query_understood:
            message = "Query could not be fully understood - showing all users"
        elif len(result.results) > 0:
            message = "Search completed successfully"
        else:
            message = "No users found matching your search criteria"

        return {
            "query": query,
            "results": [user.model_dump() for user in result.results],
            "ranked_ids": result.ranked_ids,
            "count": len(result.results),
            "total": result.total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(result.results)) < result.total_count,
            "message": message,
            "query_understood": result.query_understood,
            "parse_warnings": result.parse_warnings,
            "filters_applied": result.filters_applied
        }

    except Exception as exc:
        logger.error(f"AI search failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(exc)}"
        )
