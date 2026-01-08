from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pathlib import Path
import shutil
import uuid
import os
import logging
import time
from typing import Optional, Dict, Any
import magic  # python-magic for MIME type detection

# Import local modules
from ai import chat_completion, filter_records_ai
import models, schemas, crud
from database import engine, get_db, check_database_health, get_pool_stats

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

async def validate_image_upload(file: UploadFile) -> None:
    """
    Validate uploaded image file for security.
    
    Checks:
    - File size (max 5MB)
    - MIME type (images only)
    - Image dimensions (max 4096x4096)
    
    Args:
        file: Uploaded file to validate
        
    Raises:
        HTTPException: If validation fails
    """
    # Read file content
    content = await file.read()
    await file.seek(0)  # Reset file pointer for later use

    # Check file size
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.1f}MB. "
                   f"Your file is {file_size / (1024*1024):.1f}MB."
        )

    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail="Empty file uploaded"
        )

    # Validate MIME type using python-magic (more reliable than content_type header)
    try:
        mime_type = magic.from_buffer(content, mime=True)
    except Exception as e:
        logger.error(f"Error detecting MIME type: {e}")
        mime_type = file.content_type  # Fallback to header

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {mime_type}. "
                   f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # Validate image dimensions using PIL
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

        logger.info(f"✅ Image validated: {width}x{height}, {file_size} bytes, {mime_type}")

    except ImportError:
        logger.warning("PIL not installed, skipping dimension validation")
    except Exception as e:
        logger.error(f"Error validating image: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or corrupted image file"
        )

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
        content={"detail": "Internal server error"}
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
    description="Search users using natural language queries"
)
async def ai_search_users(
        query: str = Query(
            ...,
            description="Natural language search query",
            examples=["female users with Taylor in their name"]
        ),
        batch_size: Optional[int] = Query(
            None,
            description="Maximum number of results (auto if not specified)",
            ge=1,
            le=200
        ),
        enable_ranking: bool = Query(
            False,
            description="Enable AI-based result ranking (slower)"
        )
):
    """
    AI-powered search/filter for users based on natural language query.
    
    Examples:
    - "female users with Taylor"
    - "users starting with J"
    - "list all male"
    - "users named Jordan"
    """
    try:
        # Smart batch sizing if not specified
        if batch_size is None:
            query_lower = query.lower()
            if any(word in query_lower for word in ['named', 'name', 'called', 'with', 'has']):
                batch_size = 50
            elif any(word in query_lower for word in ['all', 'list', 'show', 'every']):
                batch_size = 100
            else:
                batch_size = 50

        # Perform AI search
        result = await filter_records_ai(query, batch_size, enable_ranking)

        return {
            "query": query,
            "results": [user.dict() for user in result.results],
            "ranked_ids": result.ranked_ids,
            "count": len(result.results),
            "total_possible": batch_size,
            "truncated": len(result.results) >= batch_size,
            "message": "Search completed successfully" if len(result.results) > 0
            else "No users found matching your search criteria"
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
    Create a new user with the following features:
    
    - Validates username uniqueness before insert
    - Hashes password using Argon2
    - Validates and stores profile picture
    - Returns created user object
    
    **File Upload Requirements:**
    - Maximum size: 5MB
    - Allowed formats: JPEG, PNG, GIF, WebP
    - Maximum dimensions: 4096x4096
    """
    try:
        # Check username uniqueness BEFORE processing file
        if crud.username_exists(db, username):
            raise HTTPException(
                status_code=400,
                detail=f"Username '{username}' is already taken. Please choose a different username."
            )

        # Validate gender
        if gender not in ["Male", "Female", "Other"]:
            raise HTTPException(
                status_code=400,
                detail="Gender must be 'Male', 'Female', or 'Other'"
            )

        profile_pic_path = None

        # Process profile picture if provided
        if profile_pic and profile_pic.filename:
            # Validate image
            await validate_image_upload(profile_pic)

            # Generate safe filename
            file_extension = Path(profile_pic.filename).suffix.lower()
            if not file_extension:
                file_extension = ".jpg"  # Default extension

            filename = f"{username}_{uuid.uuid4().hex}{file_extension}"
            file_path = UPLOAD_DIR / filename

            # Save file
            try:
                with file_path.open("wb") as buffer:
                    shutil.copyfileobj(profile_pic.file, buffer)
                profile_pic_path = f"uploads/{filename}"
                logger.info(f"📸 Saved profile picture: {filename}")
            except Exception as e:
                logger.error(f"Failed to save file: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save uploaded file"
                )

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
        raise HTTPException(status_code=500, detail="Internal server error")

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
        # Get existing user
        existing_user = crud.get_user(db, user_id)
        if not existing_user:
            raise HTTPException(
                status_code=404,
                detail=f"User with ID {user_id} not found"
            )

        # Validate gender
        if gender not in ["Male", "Female", "Other"]:
            raise HTTPException(
                status_code=400,
                detail="Gender must be 'Male', 'Female', or 'Other'"
            )

        profile_pic_path = None

        # Process new profile picture if provided
        if profile_pic and profile_pic.filename:
            # Validate image
            await validate_image_upload(profile_pic)

            # Schedule old file deletion in background
            if existing_user.profile_pic:
                old_file_path = Path(existing_user.profile_pic)
                background_tasks.add_task(cleanup_old_file, old_file_path)

            # Save new file
            file_extension = Path(profile_pic.filename).suffix.lower()
            if not file_extension:
                file_extension = ".jpg"

            filename = f"{username}_{uuid.uuid4().hex}{file_extension}"
            file_path = UPLOAD_DIR / filename

            try:
                with file_path.open("wb") as buffer:
                    shutil.copyfileobj(profile_pic.file, buffer)
                profile_pic_path = f"uploads/{filename}"
                logger.info(f"📸 Saved new profile picture: {filename}")
            except Exception as e:
                logger.error(f"Failed to save file: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save uploaded file"
                )

        # Update user
        user_data = schemas.UserCreate(
            full_name=full_name,
            username=username,
            password=password if password else "",  # Empty string if not changing
            gender=gender,
        )

        updated_user = crud.update_user(
            db=db,
            user_id=user_id,
            user=user_data,
            profile_pic=profile_pic_path,
        )

        if not updated_user:
            raise HTTPException(
                status_code=404,
                detail=f"User with ID {user_id} not found"
            )

        logger.info(f"✅ Updated user: {username} (ID: {user_id})")
        return updated_user

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

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
        raise HTTPException(status_code=500, detail="Internal server error")

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