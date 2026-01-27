"""
utils/file_handlers.py - File Upload Handling

Functions for validating and processing uploaded files:
- MIME type detection using python-magic
- File size validation
- Image dimension validation
- Profile picture saving and cleanup
"""

import shutil
import uuid
import logging
from pathlib import Path

import magic
from fastapi import UploadFile, HTTPException

from config import (
    MAX_FILE_SIZE,
    MAX_IMAGE_DIMENSION,
    ALLOWED_MIME_TYPES,
    UPLOAD_DIR,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# FILE VALIDATION HELPERS
# ==============================================================================


def _check_file_size(content: bytes) -> None:
    """
    Check file size constraints.

    Args:
        content: File content as bytes

    Raises:
        HTTPException: If file is too large or empty
    """
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024):.1f}MB. "
                   f"Your file is {file_size / (1024 * 1024):.1f}MB."
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")


def _detect_mime_type(content: bytes, fallback_type: str) -> str:
    """
    Detect MIME type using python-magic with fallback.

    Args:
        content: File content as bytes
        fallback_type: MIME type to use if detection fails

    Returns:
        str: Detected MIME type
    """
    try:
        return magic.from_buffer(content, mime=True)
    except Exception as exc:
        logger.error(f"Error detecting MIME type: {exc}")
        return fallback_type


def _check_mime_type(mime_type: str) -> None:
    """
    Validate MIME type against allowed types.

    Args:
        mime_type: MIME type to validate

    Raises:
        HTTPException: If MIME type is not allowed
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {mime_type}. "
                   f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )


def _check_image_dimensions(content: bytes) -> None:
    """
    Validate image dimensions using PIL.

    Args:
        content: Image file content as bytes

    Raises:
        HTTPException: If image dimensions exceed limits
    """
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
        logger.info(f"Image validated: {width}x{height}, {len(content)} bytes")

    except ImportError:
        logger.warning("PIL not installed, skipping dimension validation")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error validating image: {exc}")
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file")


# ==============================================================================
# PUBLIC FUNCTIONS
# ==============================================================================


async def validate_image_upload(file: UploadFile) -> None:
    """
    Validate uploaded image file for security.

    Performs comprehensive validation:
    - File size (max 5MB)
    - MIME type (images only)
    - Image dimensions (max 4096x4096)

    Args:
        file: Uploaded file

    Raises:
        HTTPException: If validation fails
    """
    content = await file.read()
    await file.seek(0)

    _check_file_size(content)
    mime_type = _detect_mime_type(content, file.content_type)
    _check_mime_type(mime_type)
    _check_image_dimensions(content)


async def save_profile_picture(file: UploadFile, username: str) -> str:
    """
    Validate and save profile picture.

    Args:
        file: Uploaded image file
        username: Username for filename prefix

    Returns:
        str: Path to saved file (e.g., 'uploads/username_uuid.jpg')

    Raises:
        HTTPException: If validation or saving fails
    """
    await validate_image_upload(file)

    file_extension = Path(file.filename).suffix.lower() or ".jpg"
    filename = f"{username}_{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Saved profile picture: {filename}")
        return f"uploads/{filename}"
    except Exception as exc:
        logger.error(f"Failed to save file: {exc}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")


def cleanup_old_file(file_path: Path) -> None:
    """
    Background task to delete old profile picture.

    This runs after the response is sent to the user,
    so it doesn't slow down the API response time.

    Args:
        file_path: Path to file to delete
    """
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted old file: {file_path.name}")
    except Exception as exc:
        logger.error(f"Failed to delete {file_path}: {exc}")
