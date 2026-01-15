"""
utils/validators.py - Input Validation Helpers

Functions for validating user input data:
- Gender validation
- Other input validation as needed
"""

from fastapi import HTTPException

from config import VALID_GENDERS


def validate_gender(gender: str) -> None:
    """
    Validate gender value against allowed options.

    Args:
        gender: Gender value to validate

    Raises:
        HTTPException: If gender is not valid
    """
    if gender not in VALID_GENDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Gender must be one of: {', '.join(VALID_GENDERS)}"
        )
