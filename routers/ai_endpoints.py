"""
routers/ai_endpoints.py - AI-Powered Search Endpoints

Endpoints for AI functionality:
- POST /ai/test: Test AI connection
- GET /ai/search: AI-powered user search
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ai import chat_completion, filter_records_ai
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
            db, query, batch_size=limit, skip=skip
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
