"""
main.py - FastAPI Application Entry Point

This is the main entry point for the AI-powered User Management API.
It defines all HTTP endpoints, middleware, and application configuration.

The API provides:
- User CRUD operations (Create, Read, Update, Delete)
- AI-powered natural language search using Ollama LLM
- File upload handling for profile pictures
- Health monitoring endpoints

Architecture:
    Client Request → FastAPI → SQLAlchemy → PostgreSQL
                         ↓
                    AI Module → Ollama LLM (for search queries)
"""

# ==============================================================================
# IMPORTS
# ==============================================================================

# FastAPI framework components
from fastapi import (
    FastAPI,           # Main application class
    Depends,           # Dependency injection decorator
    HTTPException,     # HTTP error responses
    UploadFile,        # File upload handling
    File,              # File parameter marker
    Form,              # Form data parameter marker
    Query,             # Query parameter marker
    Request,           # HTTP request object
    BackgroundTasks    # Background task execution
)
from fastapi.middleware.cors import CORSMiddleware  # Cross-Origin Resource Sharing
from fastapi.staticfiles import StaticFiles          # Static file serving
from fastapi.responses import JSONResponse           # JSON response helper

# Database components
from sqlalchemy.orm import Session  # Database session type
from sqlalchemy import text         # Raw SQL text wrapper

# Standard library
from pathlib import Path     # File path handling
import shutil                # File operations (copy, move)
import uuid                  # Unique identifier generation
import os                    # Environment variables
import logging               # Application logging
import time                  # Timing operations
from typing import Optional, Dict, Any  # Type hints

# Third-party
import magic  # python-magic for reliable MIME type detection (not just file extension)

# Local application modules
from ai import chat_completion, filter_records_ai  # AI search functionality
import models   # SQLAlchemy database models
import schemas  # Pydantic request/response schemas
import crud     # Database CRUD operations
from database import (
    engine,                # SQLAlchemy database engine
    get_db,                # Database session dependency
    check_database_health, # Health check function
    get_pool_stats         # Connection pool statistics
)

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================

# Configure logging format with timestamp, module name, level, and message
# This helps with debugging and monitoring in production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# CONSTANTS
# ==============================================================================

INTERNAL_SERVER_MSG_ERROR = "Internal server error"

# ==============================================================================
# APPLICATION SETUP
# ==============================================================================

# Create database tables
models.Base.metadata.create_all(bind=engine)
logger.info("✅ Database tables created/verified")

# Initialize FastAPI app with metadata
app = FastAPI(
    title="User Management API",
    description="AI-powered user management system with natural language search",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# File upload constraints
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_IMAGE_DIMENSION = 4096  # 4096x4096 max
ALLOWED_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp"
]

logger.info(f"🚀 Application starting in {ENVIRONMENT} mode")
logger.info(f"📁 Upload directory: {UPLOAD_DIR.absolute()}")

# ==============================================================================
# MIDDLEWARE
# ==============================================================================

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log all incoming requests and their processing time.
    """
    start_time = time.time()

    # Log request
    logger.info(
        f"📨 {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'}"
    )

    # Process request
    response = await call_next(request)

    # Log response
    process_time = time.time() - start_time
    logger.info(
        f"✅ {request.method} {request.url.path} "
        f"completed in {process_time:.3f}s "
        f"with status {response.status_code}"
    )

    # Add timing header
    response.headers["X-Process-Time"] = str(process_time)

    return response

# CORS Configuration
if ENVIRONMENT == "development":
    # Permissive CORS for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://localhost:3000",  # HTTPS support
            "https://127.0.0.1:3000"   # HTTPS support
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        max_age=3600,
    )
    logger.info("🔓 CORS enabled for development")
else:
    # Restrictive CORS for production
    frontend_url = os.getenv("FRONTEND_URL", "https://yourfrontend.com")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_url],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    logger.info(f"🔒 CORS enabled for production: {frontend_url}")

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ==============================================================================
# FILE VALIDATION HELPERS
# ==============================================================================

def _check_file_size(content: bytes) -> None:
    """Check file size constraints."""
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.1f}MB. "
                   f"Your file is {file_size / (1024*1024):.1f}MB."
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")


def _detect_mime_type(content: bytes, fallback_type: str) -> str:
    """Detect MIME type using python-magic with fallback."""
    try:
        return magic.from_buffer(content, mime=True)
    except Exception as e:
        logger.error(f"Error detecting MIME type: {e}")
        return fallback_type


def _check_mime_type(mime_type: str) -> None:
    """Validate MIME type against allowed types."""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {mime_type}. "
                   f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )


def _check_image_dimensions(content: bytes) -> None:
    """Validate image dimensions using PIL."""
    try:
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(content))
        width, height = image.size

        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise HTTPException(
                status_code=400,
                detail=f"Image dimensions too large. "
                       f"Maximum: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}. "
                       f"Your image: {width}x{height}"
            )
        logger.info(f"✅ Image validated: {width}x{height}, {len(content)} bytes")

    except ImportError:
        logger.warning("PIL not installed, skipping dimension validation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating image: {e}")
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file")


async def validate_image_upload(file: UploadFile) -> None:
    """
    Validate uploaded image file for security.

    Checks:
    - File size (max 5MB)
    - MIME type (images only)
    - Image dimensions (max 4096x4096)
    """
    content = await file.read()
    await file.seek(0)

    _check_file_size(content)
    mime_type = _detect_mime_type(content, file.content_type)
    _check_mime_type(mime_type)
    _check_image_dimensions(content)

# ==============================================================================
# USER INPUT VALIDATION HELPERS
# ==============================================================================

VALID_GENDERS = ["Male", "Female", "Other"]


def _validate_gender(gender: str) -> None:
    """Validate gender value."""
    if gender not in VALID_GENDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Gender must be one of: {', '.join(VALID_GENDERS)}"
        )


async def _save_profile_picture(file: UploadFile, username: str) -> str:
    """
    Validate and save profile picture.

    Returns:
        str: Path to saved file (e.g., 'uploads/username_uuid.jpg')
    """
    await validate_image_upload(file)

    file_extension = Path(file.filename).suffix.lower() or ".jpg"
    filename = f"{username}_{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"📸 Saved profile picture: {filename}")
        return f"uploads/{filename}"
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")


# ==============================================================================
# BACKGROUND TASKS
# ==============================================================================

def cleanup_old_file(file_path: Path):
    """
    Background task to delete old profile picture.
    
    This runs after the response is sent to the user, so it doesn't
    slow down the API response time.
    """
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"🗑️  Deleted old file: {file_path.name}")
    except Exception as e:
        logger.error(f"❌ Failed to delete {file_path}: {e}")

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
# HEALTH & STATUS ENDPOINTS
# ==============================================================================

@app.get("/", tags=["System"])
def read_root():
    """Root endpoint with API information"""
    return {
        "message": "User Management API is running",
        "version": "1.0.0",
        "environment": ENVIRONMENT,
        "docs": "/docs",
        "health": "/health"
    }

@app.get(
    "/health",
    tags=["System"],
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
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }

    # Check file system
    try:
        test_file = UPLOAD_DIR / ".health_check"
        test_file.touch()
        test_file.unlink()
        health_status["checks"]["file_system"] = {"status": "healthy"}
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["file_system"] = {
            "status": "unhealthy",
            "error": str(e)
        }

    # Return appropriate status code
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)

# ==============================================================================
# AI ENDPOINTS
# ==============================================================================

@app.post(
    "/ai/test",
    tags=["AI"],
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
    except Exception as e:
        logger.error(f"AI test failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"AI service error: {str(e)}"
        )

@app.get(
    "/ai/search",
    tags=["AI", "Users"],
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
        # Perform AI search with pagination
        result = await filter_records_ai(db, query, batch_size=limit, skip=skip, enable_ranking=enable_ranking)

        # Build response message based on parse status
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
            # Pagination info
            "count": len(result.results),
            "total": result.total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(result.results)) < result.total_count,
            "message": message,
            # Parse feedback fields
            "query_understood": result.query_understood,
            "parse_warnings": result.parse_warnings,
            "filters_applied": result.filters_applied
        }

    except Exception as e:
        logger.error(f"AI search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )

# ==============================================================================
# USER CRUD ENDPOINTS
# ==============================================================================

@app.post(
    "/users/",
    response_model=schemas.User,
    tags=["Users"],
    status_code=201,
    summary="Create a new user",
    description="Create a new user with optional profile picture upload"
)
async def create_user(
        full_name: str = Form(..., description="User's full name", min_length=2, max_length=255),
        username: str = Form(..., description="Unique username", min_length=3, max_length=50),
        password: str = Form(..., description="User password", min_length=8),
        gender: str = Form(..., description="User gender (Male, Female, Other)"),
        profile_pic: UploadFile = File(None, description="Optional profile picture (max 5MB)"),
        db: Session = Depends(get_db),
):
    """
    Create a new user with profile picture support.

    **File Upload Requirements:**
    - Maximum size: 5MB
    - Allowed formats: JPEG, PNG, GIF, WebP
    - Maximum dimensions: 4096x4096
    """
    try:
        # Validate inputs
        if crud.username_exists(db, username):
            raise HTTPException(
                status_code=400,
                detail=f"Username '{username}' is already taken. Please choose a different username."
            )
        _validate_gender(gender)

        # Process profile picture if provided
        profile_pic_path = None
        if profile_pic and profile_pic.filename:
            profile_pic_path = await _save_profile_picture(profile_pic, username)

        # Create user
        user_data = schemas.UserCreate(
            full_name=full_name,
            username=username,
            password=password,
            gender=gender,
        )
        created_user = crud.create_user(db=db, user=user_data, profile_pic=profile_pic_path)
        logger.info(f"✅ Created user: {username} (ID: {created_user.id})")

        return created_user

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)

@app.get(
    "/users/",
    tags=["Users"],
    summary="Get all users with pagination",
    description="Retrieve a paginated list of users"
)
def read_users(
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
        db: Session = Depends(get_db)
):
    """Get all users with pagination - returns paginated response"""
    # Get total count first (fast with indexes)
    total = db.query(models.User).count()

    # Get paginated users - FORCE the limit!
    users_query = db.query(models.User).offset(skip).limit(limit)
    users = users_query.all()

    logger.info(f"📋 Retrieved {len(users)} users (skip={skip}, limit={limit}, total={total})")

    return {
        "users": [schemas.User.from_orm(user) for user in users],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + len(users)) < total
    }

@app.get(
    "/users/{user_id}",
    response_model=schemas.User,
    tags=["Users"],
    summary="Get user by ID",
    description="Retrieve a specific user by their ID"
)
def read_user(
        user_id: int,
        db: Session = Depends(get_db)
):
    """Get a specific user by ID"""
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User with ID {user_id} not found"
        )
    return user

@app.put(
    "/users/{user_id}",
    response_model=schemas.User,
    tags=["Users"],
    summary="Update user",
    description="Update an existing user's information"
)
async def update_user(
        user_id: int,
        background_tasks: BackgroundTasks,
        full_name: str = Form(..., min_length=2, max_length=255),
        username: str = Form(..., min_length=3, max_length=50),
        password: Optional[str] = Form(None, min_length=8),
        gender: str = Form(...),
        profile_pic: UploadFile = File(None),
        db: Session = Depends(get_db),
):
    """
    Update user information.

    - Password is optional - leave empty to keep current password
    - Profile picture is optional - leave empty to keep current picture
    - New profile picture will replace the old one
    """
    try:
        # Verify user exists
        existing_user = crud.get_user(db, user_id)
        if not existing_user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")

        _validate_gender(gender)

        # Process new profile picture if provided
        profile_pic_path = None
        if profile_pic and profile_pic.filename:
            # Schedule old file deletion in background
            if existing_user.profile_pic:
                background_tasks.add_task(cleanup_old_file, Path(existing_user.profile_pic))
            profile_pic_path = await _save_profile_picture(profile_pic, username)

        # Update user
        user_data = schemas.UserCreate(
            full_name=full_name,
            username=username,
            password=password if password else "",
            gender=gender,
        )
        updated_user = crud.update_user(db=db, user_id=user_id, user=user_data, profile_pic=profile_pic_path)

        if not updated_user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")

        logger.info(f"✅ Updated user: {username} (ID: {user_id})")
        return updated_user

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)

@app.delete(
    "/users/{user_id}",
    tags=["Users"],
    summary="Delete user",
    description="Delete a user and their associated profile picture"
)
async def delete_user(
        user_id: int,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """
    Delete a user and their profile picture.

    The profile picture file will be deleted from the file system.
    """
    try:
        user = crud.get_user(db, user_id)
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"User with ID {user_id} not found"
            )

        # Schedule profile picture deletion in background
        if user.profile_pic:
            file_path = Path(user.profile_pic)
            background_tasks.add_task(cleanup_old_file, file_path)

        # Delete user from database
        deleted_user = crud.delete_user(db, user_id)
        if not deleted_user:
            raise HTTPException(
                status_code=404,
                detail=f"User with ID {user_id} not found"
            )

        logger.info(f"🗑️  Deleted user: {deleted_user.username} (ID: {user_id})")
        return {
            "message": "User and profile image deleted successfully",
            "user_id": user_id,
            "username": deleted_user.username
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)

# ==============================================================================
# STARTUP & SHUTDOWN EVENTS
# ==============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup"""
    logger.info("🚀 Application startup complete")
    logger.info(f"📊 Environment: {ENVIRONMENT}")
    logger.info(f"📁 Upload directory: {UPLOAD_DIR.absolute()}")

    # Verify database connection
    if check_database_health():
        logger.info("✅ Database connection verified")
    else:
        logger.warning("⚠️  Database health check failed")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on application shutdown"""
    logger.info("👋 Application shutting down")