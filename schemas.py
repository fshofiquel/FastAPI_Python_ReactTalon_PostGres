from pydantic import BaseModel
from typing import Optional


class UserBase(BaseModel):
    full_name: str
    username: str
    gender: str


class UserCreate(UserBase):
    password: Optional[str] = None  # allows update without password change


class User(UserBase):
    id: int
    profile_pic: Optional[str] = None

    class Config:
        from_attributes = True
