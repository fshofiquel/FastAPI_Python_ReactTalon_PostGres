"""
routers/health.py - Health Check and System Status Endpoints

Endpoints for monitoring application health:
- GET /: Root endpoint with API info
- GET /health: Comprehensive health check
"""

import time
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db, get_pool_stats
from config import ENVIRONMENT, UPLOAD_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System"])


@router.get("/")
def read_root():
    """Root endpoint with API information"""
    return {
        "message": "User Management API is running",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
        "docs": "/docs",
        "health": "/health"
    }


@router.get(
    "/health",
    summary="Health check endpoint",
    description="Check the health status of the API and its dependencies"
)
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Comprehensive health check that validates:
    - Database connectivity
    - File system access
    - System status
    """
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "checks": {}
    }

    # Check database
    try:
        db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "pool_stats": get_pool_stats()
        }
    except Exception as exc:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(exc)
        }

    # Check file system
    try:
        test_file = UPLOAD_DIR / ".health_check"
        test_file.touch()
        test_file.unlink()
        health_status["checks"]["file_system"] = {"status": "healthy"}
    except Exception as exc:
        health_status["status"] = "unhealthy"
        health_status["checks"]["file_system"] = {
            "status": "unhealthy",
            "error": str(exc)
        }

    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)
