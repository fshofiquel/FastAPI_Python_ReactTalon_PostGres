"""
routers - API Router Package

This package contains FastAPI routers that define API endpoints:
- users: User CRUD operations
- ai_endpoints: AI-powered search endpoints
- health: Health check and system status endpoints
"""

from routers.users import router as users_router
from routers.ai_endpoints import router as ai_router
from routers.health import router as health_router

__all__ = [
    "users_router",
    "ai_router",
    "health_router",
]
