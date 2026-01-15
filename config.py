"""
config.py - Application Configuration

Centralized configuration for the FastAPI application including:
- Environment settings
- File upload constraints
- Validation constants
- Logging configuration
"""

import os
import logging
from pathlib import Path

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# ==============================================================================
# ENVIRONMENT SETTINGS
# ==============================================================================

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# ==============================================================================
# FILE UPLOAD CONFIGURATION
# ==============================================================================

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

# ==============================================================================
# VALIDATION CONSTANTS
# ==============================================================================

VALID_GENDERS = ["Male", "Female", "Other"]

# ==============================================================================
# ERROR MESSAGES
# ==============================================================================

INTERNAL_SERVER_MSG_ERROR = "Internal server error"
