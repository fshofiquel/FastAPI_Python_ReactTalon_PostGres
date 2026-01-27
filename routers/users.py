"""
routers/users.py - User CRUD Endpoints

Endpoints for user management:
- POST /users/: Create a new user
- GET /users/: Get all users with pagination
- GET /users/{user_id}: Get user by ID
- PUT /users/{user_id}: Update user
- DELETE /users/{user_id}: Delete user
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError  # Database constraint violation handling

import models
import schemas
import crud
from database import get_db
from config import INTERNAL_SERVER_MSG_ERROR
from utils.file_handlers import save_profile_picture, cleanup_old_file
from utils.validators import validate_gender

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "/",
    response_model=schemas.User,
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
        validate_gender(gender)

        # Process profile picture if provided
        profile_pic_path = None
        if profile_pic and profile_pic.filename:
            profile_pic_path = await save_profile_picture(profile_pic, username)

        # Create user
        user_data = schemas.UserCreate(
            full_name=full_name,
            username=username,
            password=password,
            gender=gender,
        )
        created_user = crud.create_user(db=db, user=user_data, profile_pic=profile_pic_path)
        logger.info(f"Created user: {username} (ID: {created_user.id})")

        return created_user

    except HTTPException:
        raise
    except IntegrityError as exc:
        logger.error(f"Database constraint violation when creating user '{username}': {exc}")
        raise HTTPException(
            status_code=400,
            detail="Username already exists or a database constraint was violated. Please try with a different username."
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error creating user: {exc}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)


@router.get(
    "/",
    summary="Get all users with pagination",
    description="Retrieve a paginated list of users"
)
def read_users(
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(50, ge=1, le=200, description="Maximum number of records to return"),
        db: Session = Depends(get_db)
):
    """Get all users with pagination"""
    total = db.query(models.User).count()
    users_query = db.query(models.User).offset(skip).limit(limit)
    users = users_query.all()

    logger.info(f"Retrieved {len(users)} users (skip={skip}, limit={limit}, total={total})")

    return {
        "users": [schemas.User.model_validate(user) for user in users],
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_more": (skip + len(users)) < total
    }


@router.get(
    "/{user_id}",
    response_model=schemas.User,
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


@router.put(
    "/{user_id}",
    response_model=schemas.User,
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

        validate_gender(gender)

        # Process new profile picture if provided
        profile_pic_path = None
        if profile_pic and profile_pic.filename:
            # Schedule old file deletion in background
            if existing_user.profile_pic:
                background_tasks.add_task(cleanup_old_file, Path(existing_user.profile_pic))
            profile_pic_path = await save_profile_picture(profile_pic, username)

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

        logger.info(f"Updated user: {username} (ID: {user_id})")
        return updated_user

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error updating user: {exc}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)


@router.delete(
    "/{user_id}",
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

        logger.info(f"Deleted user: {deleted_user.username} (ID: {user_id})")
        return {
            "message": "User and profile image deleted successfully",
            "user_id": user_id,
            "username": deleted_user.username
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error deleting user: {exc}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_MSG_ERROR)
