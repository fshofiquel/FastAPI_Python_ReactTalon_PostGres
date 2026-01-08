from sqlalchemy import Column, Integer, String, DateTime, Index, event, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import validates
from database import Base
import re

# ==============================================================================
# USER MODEL
# ==============================================================================

class User(Base):
    """
    User model representing application users.
    
    This model includes:
    - Basic user information (name, username, password, gender)
    - Profile picture support
    - Automatic timestamps (created_at, updated_at)
    - Input validation
    - Optimized indexes for common queries
    
    Attributes:
        id (int): Primary key, auto-incrementing
        full_name (str): User's full name (2-255 characters)
        username (str): Unique username (3-50 characters, alphanumeric + underscore)
        password (str): Hashed password (Argon2 hash, ~90 characters)
        gender (str): User gender - must be 'Male', 'Female', or 'Other'
        profile_pic (str): Optional path to profile picture file
        created_at (datetime): Timestamp when user was created
        updated_at (datetime): Timestamp when user was last updated
    """
    
    __tablename__ = "users"

    # ==============================================================================
    # COLUMNS
    # ==============================================================================
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # User information with length constraints
    full_name = Column(
        String(255),
        nullable=False,
        comment="User's full name"
    )
    
    username = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique username for login"
    )
    
    password = Column(
        String(255),
        nullable=False,
        comment="Hashed password (Argon2)"
    )
    
    gender = Column(
        String(20),
        nullable=False,
        comment="User gender: Male, Female, or Other"
    )
    
    profile_pic = Column(
        String(500),
        nullable=True,
        comment="Path to profile picture file"
    )
    
    # Timestamps - automatically managed
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp when user was created"
    )
    
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Timestamp when user was last updated"
    )
    
    # ==============================================================================
    # INDEXES AND CONSTRAINTS
    # ==============================================================================
    
    __table_args__ = (
        # Indexes for query optimization
        Index('idx_user_username', 'username', unique=True),
        Index('idx_user_gender', 'gender'),
        Index('idx_user_fullname', 'full_name'),
        Index('idx_user_gender_name', 'gender', 'full_name'),  # Composite index for AI search
        Index('idx_user_created', 'created_at'),
        
        # Check constraint for gender values
        CheckConstraint(
            "gender IN ('Male', 'Female', 'Other')",
            name='check_gender_valid'
        ),
    )
    
    # ==============================================================================
    # VALIDATION
    # ==============================================================================
    
    @validates('username')
    def validate_username(self, key, username):
        """
        Validate username format and length.
        
        Rules:
        - Must be 3-50 characters
        - Can only contain letters, numbers, and underscores
        - No spaces or special characters
        
        Args:
            key: Column name (automatically passed)
            username: Username value to validate
            
        Returns:
            str: Validated username
            
        Raises:
            ValueError: If username doesn't meet requirements
        """
        if not username:
            raise ValueError("Username cannot be empty")
        
        username = username.strip()
        
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters long")
        
        if len(username) > 50:
            raise ValueError("Username must be at most 50 characters long")
        
        # Check for valid characters (alphanumeric + underscore only)
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise ValueError(
                "Username can only contain letters, numbers, and underscores. "
                "No spaces or special characters allowed."
            )
        
        return username
    
    @validates('gender')
    def validate_gender(self, key, gender):
        """
        Validate gender value.
        
        Args:
            key: Column name (automatically passed)
            gender: Gender value to validate
            
        Returns:
            str: Validated gender
            
        Raises:
            ValueError: If gender is not one of the allowed values
        """
        valid_genders = ['Male', 'Female', 'Other']
        
        if not gender:
            raise ValueError("Gender is required")
        
        gender = gender.strip()
        
        if gender not in valid_genders:
            raise ValueError(
                f"Gender must be one of: {', '.join(valid_genders)}. "
                f"Got: '{gender}'"
            )
        
        return gender
    
    @validates('full_name')
    def validate_full_name(self, key, full_name):
        """
        Validate full name.
        
        Args:
            key: Column name (automatically passed)
            full_name: Full name to validate
            
        Returns:
            str: Validated and trimmed full name
            
        Raises:
            ValueError: If name doesn't meet requirements
        """
        if not full_name:
            raise ValueError("Full name cannot be empty")
        
        full_name = full_name.strip()
        
        if len(full_name) < 2:
            raise ValueError("Full name must be at least 2 characters long")
        
        if len(full_name) > 255:
            raise ValueError("Full name must be at most 255 characters long")
        
        return full_name
    
    @validates('password')
    def validate_password(self, key, password):
        """
        Validate password field.
        
        Note: This validates the HASHED password, not the plain text.
        Plain text validation should happen before hashing in the CRUD layer.
        
        Args:
            key: Column name (automatically passed)
            password: Hashed password to validate
            
        Returns:
            str: Validated password hash
            
        Raises:
            ValueError: If password hash is empty
        """
        if not password:
            raise ValueError("Password hash cannot be empty")
        
        return password
    
    # ==============================================================================
    # METHODS
    # ==============================================================================
    
    def __repr__(self):
        """String representation for debugging"""
        return (
            f"<User(id={self.id}, username='{self.username}', "
            f"gender='{self.gender}', created={self.created_at})>"
        )
    
    def to_dict(self, include_timestamps=True):
        """
        Convert model to dictionary for JSON serialization.
        
        Args:
            include_timestamps: Whether to include created_at and updated_at
            
        Returns:
            dict: User data as dictionary
        """
        data = {
            "id": self.id,
            "full_name": self.full_name,
            "username": self.username,
            "gender": self.gender,
            "profile_pic": self.profile_pic,
        }
        
        if include_timestamps:
            data["created_at"] = self.created_at.isoformat() if self.created_at else None
            data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        
        return data

# ==============================================================================
# EVENT LISTENERS
# ==============================================================================

@event.listens_for(User, 'before_update')
def receive_before_update(mapper, connection, target):
    """
    Automatically update the updated_at timestamp before any update.
    
    This ensures updated_at is always current even if onupdate doesn't trigger.
    """
    target.updated_at = func.now()

@event.listens_for(User, 'before_insert')
def receive_before_insert(mapper, connection, target):
    """
    Normalize data before insert.
    
    This ensures consistent data format:
    - Trims whitespace from strings
    - Standardizes username to lowercase (optional)
    """
    # Trim whitespace
    if target.full_name:
        target.full_name = target.full_name.strip()
    if target.username:
        target.username = target.username.strip()
    
    # Optional: Convert username to lowercase for case-insensitive uniqueness
    # Uncomment if you want usernames to be case-insensitive
    # if target.username:
    #     target.username = target.username.lower()

# ==============================================================================
# HELPER COMMENT
# ==============================================================================

"""
MIGRATION NOTES:

If you have existing data in your database, you'll need to add the new columns
with a migration. Here's how to do it manually:

1. Connect to your PostgreSQL database:
   psql -U your_username -d your_database_name

2. Add the new columns:
   ALTER TABLE users 
   ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
   ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL;

3. Update existing columns to add length constraints:
   ALTER TABLE users 
   ALTER COLUMN username TYPE VARCHAR(50),
   ALTER COLUMN full_name TYPE VARCHAR(255),
   ALTER COLUMN password TYPE VARCHAR(255),
   ALTER COLUMN gender TYPE VARCHAR(20),
   ALTER COLUMN profile_pic TYPE VARCHAR(500);

4. Add check constraint for gender:
   ALTER TABLE users 
   ADD CONSTRAINT check_gender_valid CHECK (gender IN ('Male', 'Female', 'Other'));

Or use Alembic for automatic migrations:
   alembic revision --autogenerate -m "Add timestamps and constraints"
   alembic upgrade head
"""
