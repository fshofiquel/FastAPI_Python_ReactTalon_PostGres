from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
import re

# ==============================================================================
# USER SCHEMAS
# ==============================================================================

class UserBase(BaseModel):
    """
    Base user schema with common fields.
    Used as a parent for other user schemas.
    """
    full_name: str = Field(..., min_length=2, max_length=255, description="User's full name")
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    gender: str = Field(..., description="User gender: Male, Female, or Other")
    
    @validator('username')
    def validate_username(cls, v):
        """Validate username format"""
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username can only contain letters, numbers, and underscores')
        return v.strip()
    
    @validator('gender')
    def validate_gender(cls, v):
        """Validate gender value"""
        valid_genders = ['Male', 'Female', 'Other']
        if v not in valid_genders:
            raise ValueError(f'Gender must be one of: {", ".join(valid_genders)}')
        return v
    
    @validator('full_name')
    def validate_full_name(cls, v):
        """Validate and clean full name"""
        return v.strip()


class UserCreate(UserBase):
    """
    Schema for creating a new user.
    Includes password field which is not in the base schema.
    """
    password: str = Field(..., min_length=8, description="User password (minimum 8 characters)")
    
    @validator('password')
    def validate_password(cls, v):
        """
        Validate password strength.
        
        Optional: Uncomment these checks for stronger password requirements
        """
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        
        # Uncomment for stronger password requirements:
        # if not any(c.isupper() for c in v):
        #     raise ValueError('Password must contain at least one uppercase letter')
        # if not any(c.islower() for c in v):
        #     raise ValueError('Password must contain at least one lowercase letter')
        # if not any(c.isdigit() for c in v):
        #     raise ValueError('Password must contain at least one number')
        
        return v


class UserUpdate(UserBase):
    """
    Schema for updating an existing user.
    All fields are optional to allow partial updates.
    """
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8)
    gender: Optional[str] = None


class User(UserBase):
    """
    Complete user schema with all fields including database-generated ones.
    Used for API responses.
    """
    id: int = Field(..., description="User ID (auto-generated)")
    profile_pic: Optional[str] = Field(None, description="Path to profile picture file")
    created_at: Optional[datetime] = Field(None, description="Timestamp when user was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when user was last updated")
    
    class Config:
        """Pydantic configuration"""
        from_attributes = True  # Allows conversion from SQLAlchemy models
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class UserInDB(User):
    """
    User schema including password hash.
    Used internally, never exposed in API responses.
    """
    password: str = Field(..., description="Hashed password")


# ==============================================================================
# API RESPONSE SCHEMAS
# ==============================================================================

class UserList(BaseModel):
    """
    Schema for paginated user list response.
    """
    users: list[User]
    total: int
    skip: int
    limit: int


class MessageResponse(BaseModel):
    """
    Generic message response schema.
    """
    message: str


class ErrorResponse(BaseModel):
    """
    Error response schema.
    """
    detail: str


class DeleteResponse(BaseModel):
    """
    Response schema for delete operations.
    """
    message: str
    user_id: int
    username: str


# ==============================================================================
# AI SEARCH SCHEMAS
# ==============================================================================

class SearchQuery(BaseModel):
    """
    Schema for AI search request.
    """
    query: str = Field(..., min_length=1, max_length=500, description="Natural language search query")
    batch_size: Optional[int] = Field(None, ge=1, le=200, description="Maximum number of results")
    enable_ranking: bool = Field(False, description="Enable AI-based result ranking")


class SearchResult(BaseModel):
    """
    Schema for AI search response.
    """
    query: str
    results: list[User]
    count: int
    total_possible: int
    truncated: bool
    ranked_ids: Optional[list[int]] = None
    message: str


# ==============================================================================
# HEALTH CHECK SCHEMA
# ==============================================================================

class HealthCheck(BaseModel):
    """
    Schema for health check response.
    """
    status: str = Field(..., description="Overall health status (healthy/unhealthy)")
    timestamp: float = Field(..., description="Unix timestamp of health check")
    checks: dict = Field(..., description="Individual component health checks")


# ==============================================================================
# EXAMPLES FOR API DOCUMENTATION
# ==============================================================================

# Example user for API docs
EXAMPLE_USER = {
    "id": 1,
    "full_name": "John Doe",
    "username": "johndoe",
    "gender": "Male",
    "profile_pic": "uploads/johndoe_abc123_photo.jpg",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
}

# Example user creation request
EXAMPLE_USER_CREATE = {
    "full_name": "John Doe",
    "username": "johndoe",
    "password": "SecurePass123!",
    "gender": "Male"
}

# Example search query
EXAMPLE_SEARCH_QUERY = {
    "query": "female users with Taylor in their name",
    "batch_size": 50,
    "enable_ranking": False
}

# Example search result
EXAMPLE_SEARCH_RESULT = {
    "query": "female users with Taylor",
    "results": [EXAMPLE_USER],
    "count": 1,
    "total_possible": 50,
    "truncated": False,
    "ranked_ids": None,
    "message": "Search completed successfully"
}
