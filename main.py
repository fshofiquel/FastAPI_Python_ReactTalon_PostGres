"""
main.py - FastAPI Application Entry Point

This is the main entry point for the AI-powered User Management API.
It initializes the FastAPI application, configures middleware, and
includes the API routers.

The API provides:
- User CRUD operations (Create, Read, Update, Delete)
- AI-powered natural language search using Ollama LLM
- File upload handling for profile pictures
- Health monitoring endpoints

Architecture:
    Client Request -> FastAPI -> SQLAlchemy -> PostgreSQL
                         |
                    AI Module -> Ollama LLM (for search queries)
"""

import os
import time
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

import models
from database import engine, check_database_health
from config import ENVIRONMENT, UPLOAD_DIR, INTERNAL_SERVER_MSG_ERROR
from ai import close_http_client, warmup_model
from routers import users_router, ai_router, health_router

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)

# ==============================================================================
# APPLICATION SETUP
# ==============================================================================

# Create database tables
models.Base.metadata.create_all(bind=engine)
logger.info("Database tables created/verified")

# Initialize FastAPI app
app = FastAPI(
    title="User Management API",
    description="AI-powered user management system with natural language search",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

logger.info(f"Application starting in {ENVIRONMENT} mode")
logger.info(f"Upload directory: {UPLOAD_DIR.absolute()}")

# ==============================================================================
# MIDDLEWARE
# ==============================================================================


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests and their processing time."""
    start_time = time.time()

    logger.info(
        f"{request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'}"
    )

    response = await call_next(request)

    process_time = time.time() - start_time
    logger.info(
        f"{request.method} {request.url.path} "
        f"completed in {process_time:.3f}s "
        f"with status {response.status_code}"
    )

    response.headers["X-Process-Time"] = str(process_time)
    return response


# CORS Configuration
if ENVIRONMENT == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://localhost:3000",
            "https://127.0.0.1:3000"
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        max_age=3600,
    )
    logger.info("CORS enabled for development")
else:
    frontend_url = os.getenv("FRONTEND_URL", "https://yourfrontend.com")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_url],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    logger.info(f"CORS enabled for production: {frontend_url}")

# ==============================================================================
# STATIC FILES & ROUTERS
# ==============================================================================

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include routers
app.include_router(health_router)
app.include_router(ai_router)
app.include_router(users_router)

# ==============================================================================
# ERROR HANDLERS
# ==============================================================================


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle validation errors"""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)}
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    """Handle runtime errors"""
    logger.error(f"Runtime error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": INTERNAL_SERVER_MSG_ERROR}
    )


# ==============================================================================
# STARTUP & SHUTDOWN EVENTS
# ==============================================================================


@app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup"""
    logger.info("Application startup complete")
    logger.info(f"Environment: {ENVIRONMENT}")
    logger.info(f"Upload directory: {UPLOAD_DIR.absolute()}")

    if check_database_health():
        logger.info("Database connection verified")
    else:
        logger.warning("Database health check failed")

    # Warm up AI model (loads weights into memory, avoids cold-start on first request)
    await warmup_model()


@app.on_event("shutdown")
async def shutdown_event():
    """
    Cleanup resources on application shutdown.

    Ensures all resources are properly released:
    - HTTP client connections
    - Database connections (handled by SQLAlchemy)
    """
    logger.info("Application shutting down")
    await close_http_client()
