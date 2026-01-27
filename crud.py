"""
crud.py - Database CRUD Operations

This module provides Create, Read, Update, Delete operations for the User model.
It acts as a data access layer between the API endpoints and the database.

Why Use a CRUD Module?
    - Separates database logic from route handlers
    - Centralizes error handling and logging
    - Makes it easy to test database operations
    - Provides consistent patterns for all models

Operations Provided:
    CREATE:
        - create_user(): Create new user with password hashing

    READ:
        - get_user(): Get user by ID
        - get_user_by_username(): Get user by username (case-insensitive)
        - get_users(): Get paginated list of users
        - get_users_by_gender(): Get users filtered by gender
        - search_users_by_name(): Search users by name pattern
        - get_user_count(): Get total user count
        - username_exists(): Check if username is taken

    UPDATE:
        - update_user(): Update user fields (password optional)

    DELETE:
        - delete_user(): Delete single user
        - bulk_delete_users(): Delete multiple users efficiently

    AUTHENTICATION:
        - authenticate_user(): Verify username/password (for future login)
        - verify_password(): Check password against hash
        - get_password_hash(): Hash a plain text password

Password Security:
    This module uses Argon2 for password hashing, which is:
    - Winner of the Password Hashing Competition
    - Memory-hard (resistant to GPU/ASIC attacks)
    - Time-configurable (can increase difficulty over time)
    - Timing-safe verification (resistant to timing attacks)

Error Handling:
    All functions include comprehensive error handling:
    - ValueError: Validation errors (returned to user)
    - IntegrityError: Database constraint violations
    - SQLAlchemyError: General database errors
    - All errors are logged with relevant context
"""

from sqlalchemy.orm import Session  # Database session type
from sqlalchemy.exc import IntegrityError, SQLAlchemyError  # Database exceptions
from sqlalchemy import func  # SQL functions (lower, count)
from passlib.context import CryptContext  # Password hashing
from typing import List, Optional  # Type hints
import models  # SQLAlchemy models
import schemas  # Pydantic schemas
import logging  # Application logging

# ==============================================================================
# LOGGING SETUP
# ==============================================================================

logger = logging.getLogger(__name__)

# ==============================================================================
# CONSTANTS
# ==============================================================================

DATABASE_ERROR_MSG = "Database error occurred"

# ==============================================================================
# PASSWORD HASHING CONFIGURATION
# ==============================================================================

pwd_context = CryptContext(
    schemes=["argon2"],  # Argon2 is the winner of the Password Hashing Competition
    deprecated="auto"
)


# ==============================================================================
# PASSWORD FUNCTIONS
# ==============================================================================

def get_password_hash(password: str) -> str:
    """
    Hash a password using Argon2.
    
    Argon2 is recommended by OWASP for password hashing because it's:
    - Memory-hard (resistant to GPU attacks)
    - Configurable (can increase difficulty over time)
    - Side-channel resistant
    
    Args:
        password: Plain text password to hash
        
    Returns:
        str: Hashed password (~90 characters)
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    This function is timing-safe to prevent timing attacks.
    
    Args:
        plain_password: The plain text password to verify
        hashed_password: The hashed password to check against
        
    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets minimum security requirements.
    
    Requirements:
    - At least 8 characters
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one digit
    
    Args:
        password: Password to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"

    return True, ""


# ==============================================================================
# USER LOOKUP FUNCTIONS
# ==============================================================================

def get_user(db: Session, user_id: int) -> Optional[models.User]:
    """
    Get a user by ID.
    
    Args:
        db: Database session
        user_id: User ID to search for
        
    Returns:
        User object if found, None otherwise
    """
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    """
    Get a user by username (case-insensitive).
    
    Args:
        db: Database session
        username: Username to search for
        
    Returns:
        User object if found, None otherwise
    """
    return (
        db.query(models.User)
        .filter(func.lower(models.User.username) == username.lower())
        .first()
    )


def username_exists(db: Session, username: str, exclude_id: Optional[int] = None) -> bool:
    """
    Check if a username already exists in the database.
    
    This is useful for validating uniqueness before attempting to insert,
    which gives better error messages to users.
    
    Args:
        db: Database session
        username: Username to check
        exclude_id: Optional user ID to exclude (useful for updates)
        
    Returns:
        bool: True if username exists, False otherwise
    """
    query = db.query(models.User).filter(
        func.lower(models.User.username) == username.lower()
    )

    if exclude_id is not None:
        query = query.filter(models.User.id != exclude_id)

    return query.first() is not None


# ==============================================================================
# USER RETRIEVAL FUNCTIONS
# ==============================================================================

def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[models.User]:
    """
    Get a list of users with pagination.
    
    Args:
        db: Database session
        skip: Number of records to skip (for pagination)
        limit: Maximum number of records to return
        
    Returns:
        List of User objects
    """
    return db.query(models.User).offset(skip).limit(limit).all()


def get_users_by_gender(
        db: Session,
        gender: str,
        skip: int = 0,
        limit: int = 100
) -> List[models.User]:
    """
    Get all users of a specific gender.
    
    Args:
        db: Database session
        gender: Gender to filter by (Male, Female, or Other)
        skip: Number of records to skip
        limit: Maximum number of records to return
        
    Returns:
        List of User objects matching the gender
    """
    return (
        db.query(models.User)
        .filter(models.User.gender == gender)
        .offset(skip)
        .limit(limit)
        .all()
    )


def search_users_by_name(
        db: Session,
        name_pattern: str,
        skip: int = 0,
        limit: int = 100
) -> List[models.User]:
    """
    Search users by name pattern (case-insensitive).
    
    Args:
        db: Database session
        name_pattern: Pattern to search for (supports wildcards via ILIKE)
        skip: Number of records to skip
        limit: Maximum number of records to return
        
    Returns:
        List of User objects with matching names
    """
    return (
        db.query(models.User)
        .filter(models.User.full_name.ilike(f"%{name_pattern}%"))
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_user_count(db: Session, gender: Optional[str] = None) -> int:
    """
    Get total count of users, optionally filtered by gender.
    
    Args:
        db: Database session
        gender: Optional gender filter
        
    Returns:
        int: Total count of users
    """
    query = db.query(models.User)

    if gender:
        query = query.filter(models.User.gender == gender)

    return query.count()


# ==============================================================================
# USER CREATION
# ==============================================================================

def create_user(
        db: Session,
        user: schemas.UserCreate,
        profile_pic: Optional[str] = None
) -> models.User:
    """
    Create a new user with proper error handling and validation.
    
    Args:
        db: Database session
        user: User data from request (Pydantic model)
        profile_pic: Optional path to profile picture
        
    Returns:
        models.User: Created user object
        
    Raises:
        ValueError: If username already exists or validation fails
        RuntimeError: If database error occurs
    """
    try:
        # Check if username already exists
        if username_exists(db, user.username):
            raise ValueError(f"Username '{user.username}' is already taken")

        # Validate password strength (optional but recommended)
        # Uncomment if you want to enforce strong passwords
        # is_valid, error_msg = validate_password_strength(user.password)
        # if not is_valid:
        #     raise ValueError(error_msg)

        # Hash password
        hashed_password = get_password_hash(user.password)

        # Create user object
        db_user = models.User(
            full_name=user.full_name,
            username=user.username,
            password=hashed_password,
            gender=user.gender,
            profile_pic=profile_pic,
        )

        # Add to database
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        logger.info(f"Created user: {db_user.username} (ID: {db_user.id})")
        return db_user

    except ValueError:
        # Re-raise validation errors
        db.rollback()
        raise

    except IntegrityError as e:
        db.rollback()
        logger.error(f"Integrity error creating user: {e}")

        # Check if it's a username uniqueness error
        if "unique constraint" in str(e).lower() and "username" in str(e).lower():
            raise ValueError("Username already exists")

        raise ValueError("Database constraint violation")

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating user: {e}")
        raise RuntimeError(DATABASE_ERROR_MSG)

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error creating user: {e}")
        raise


# ==============================================================================
# USER UPDATE
# ==============================================================================

def update_user(
        db: Session,
        user_id: int,
        user: schemas.UserCreate,
        profile_pic: Optional[str] = None,
) -> Optional[models.User]:
    """
    Update an existing user with proper error handling.
    
    Args:
        db: Database session
        user_id: ID of user to update
        user: Updated user data (Pydantic model)
        profile_pic: Optional new profile picture path
        
    Returns:
        models.User: Updated user object, or None if user not found
        
    Raises:
        ValueError: If username already exists or validation fails
        RuntimeError: If database error occurs
    """
    try:
        # Get existing user
        db_user = get_user(db, user_id)
        if not db_user:
            logger.warning(f"Update failed: User {user_id} not found")
            return None

        # Check username uniqueness (excluding current user)
        if user.username != db_user.username:
            if username_exists(db, user.username, exclude_id=user_id):
                raise ValueError(f"Username '{user.username}' is already taken")

        # Update fields
        db_user.full_name = user.full_name
        db_user.username = user.username
        db_user.gender = user.gender

        # Update profile picture if provided
        if profile_pic is not None:
            db_user.profile_pic = profile_pic

        # Update password only if explicitly provided and not empty
        # This allows users to update profile without changing password
        if user.password is not None and user.password.strip():
            # Optional: Validate password strength
            # is_valid, error_msg = validate_password_strength(user.password)
            # if not is_valid:
            #     raise ValueError(error_msg)

            db_user.password = get_password_hash(user.password)
            logger.info(f"Password updated for user {user_id}")

        # Commit changes
        db.commit()
        db.refresh(db_user)

        logger.info(f"Updated user: {db_user.username} (ID: {db_user.id})")
        return db_user

    except ValueError:
        db.rollback()
        raise

    except IntegrityError as e:
        db.rollback()
        logger.error(f"Integrity error updating user {user_id}: {e}")

        if "unique constraint" in str(e).lower() and "username" in str(e).lower():
            raise ValueError("Username already exists")

        raise ValueError("Database constraint violation")

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating user {user_id}: {e}")
        raise RuntimeError(DATABASE_ERROR_MSG)

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error updating user {user_id}: {e}")
        raise


# ==============================================================================
# USER DELETION
# ==============================================================================

def delete_user(db: Session, user_id: int) -> Optional[models.User]:
    """
    Delete a user from the database.
    
    Args:
        db: Database session
        user_id: ID of user to delete
        
    Returns:
        models.User: Deleted user object, or None if user not found
        
    Raises:
        RuntimeError: If database error occurs
    """
    try:
        # Get user
        db_user = get_user(db, user_id)
        if not db_user:
            logger.warning(f"Delete failed: User {user_id} not found")
            return None

        # Store user info for logging
        username = db_user.username

        # Delete user
        db.delete(db_user)
        db.commit()

        logger.info(f"Deleted user: {username} (ID: {user_id})")
        return db_user

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting user {user_id}: {e}")
        raise RuntimeError(DATABASE_ERROR_MSG)

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error deleting user {user_id}: {e}")
        raise


# ==============================================================================
# AUTHENTICATION (for future use)
# ==============================================================================

def authenticate_user(
        db: Session,
        username: str,
        password: str
) -> Optional[models.User]:
    """
    Authenticate a user by username and password.
    
    This function uses constant-time password verification to prevent
    timing attacks that could reveal valid usernames.
    
    Args:
        db: Database session
        username: Username to authenticate
        password: Plain text password to verify
        
    Returns:
        User object if authentication successful, None otherwise
    """
    # Get user by username
    user = get_user_by_username(db, username)

    if not user:
        # Still verify a dummy password to prevent timing attacks
        # This ensures the response time is similar whether the user exists or not
        pwd_context.hash("dummy_password_that_will_never_match")
        logger.warning(f"Authentication failed: Username '{username}' not found")
        return None

    # Verify password
    if not verify_password(password, user.password):
        logger.warning(f"Authentication failed: Invalid password for user '{username}'")
        return None

    logger.info(f"User authenticated: {username}")
    return user


# ==============================================================================
# BULK OPERATIONS
# ==============================================================================

def bulk_delete_users(db: Session, user_ids: List[int]) -> int:
    """
    Delete multiple users at once.
    
    This is more efficient than deleting users one by one.
    
    Args:
        db: Database session
        user_ids: List of user IDs to delete
        
    Returns:
        int: Number of users deleted
        
    Raises:
        RuntimeError: If database error occurs
    """
    try:
        deleted_count = (
            db.query(models.User)
            .filter(models.User.id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        db.commit()

        logger.info(f"Bulk deleted {deleted_count} users")
        return deleted_count

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Error in bulk delete: {e}")
        raise RuntimeError("Database error occurred during bulk delete")

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error in bulk delete: {e}")
        raise
