from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
import uuid
from ai import chat_completion, filter_records_ai
import models, schemas, crud
from database import engine, get_db
from math import ceil

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.post("/ai/test")
async def test_ai(
        prompt: str = Query(..., description="Prompt sent to the AI")
):
    response = await chat_completion(prompt)
    return {
        "input": prompt,
        "output": response
    }

@app.get("/ai/search")
async def ai_search_users(
        query: str = Query(..., description="Natural language search query"),
        batch_size: int = Query(None, description="Maximum number of results (auto if not specified)"),
        enable_ranking: bool = Query(False, description="Enable AI-based result ranking (slower)")
):
    """
    AI-powered search/filter for users based on natural language query.
    Uses AI to parse the query and fetch matching users from database.

    Args:
        query: Natural language search query (e.g., "Female users with Taylor in their name")
        batch_size: Maximum number of results to return (defaults to smart sizing)
        enable_ranking: Whether to use AI ranking (disabled by default for better performance)
    """
    # Smart batch sizing if not specified
    if batch_size is None:
        query_lower = query.lower()
        # Specific name searches usually return fewer results
        if any(word in query_lower for word in ['named', 'name', 'called', 'with', 'has']):
            batch_size = 50  # Medium limit for name searches
        # Broad queries like "list all" might return many results
        elif any(word in query_lower for word in ['all', 'list', 'show', 'every']):
            batch_size = 100  # Higher limit for broad searches
        else:
            batch_size = 50  # Default moderate limit

    # Use the AI to parse query and fetch users directly from database
    result = await filter_records_ai(query, batch_size, enable_ranking)

    return {
        "query": query,
        "results": [user.dict() for user in result.results],
        "ranked_ids": result.ranked_ids,
        "count": len(result.results),
        "total_possible": batch_size,
        "truncated": len(result.results) >= batch_size,  # True if there might be more results
        "message": "Search completed successfully" if len(result.results) > 0 else "No users found matching your search criteria"
    }


@app.get("/ai/search/count")
async def ai_search_count(
        query: str = Query(..., description="Natural language search query")
):
    """
    Get the total count of matching users without fetching all records.
    Useful for showing "X results found" before loading them all.
    """
    from ai import parse_query_ai
    import asyncpg

    # Parse the query
    filters = await parse_query_ai(query)

    # Build count query
    sql = "SELECT COUNT(*) FROM users WHERE TRUE"
    params = []

    if filters.gender:
        params.append(filters.gender)
        sql += f" AND gender = ${len(params)}"

    if filters.name_substr:
        params.append(f"%{filters.name_substr}%")
        sql += f" AND full_name ILIKE ${len(params)}"

    # Get count from database
    DATABASE_URL = os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        count = await conn.fetchval(sql, *params)
        return {
            "query": query,
            "total_count": count,
            "filters": filters.dict()
        }
    finally:
        await conn.close()



# --------------------
# CORS Configuration
# --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------
# Uploads directory
# --------------------
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
def read_root():
    return {"message": "User Management API is running"}


# --------------------
# Create User
# --------------------
@app.post("/users/", response_model=schemas.User)
async def create_user(
        full_name: str = Form(...),
        username: str = Form(...),
        password: str = Form(...),
        gender: str = Form(...),
        profile_pic: UploadFile = File(None),
        db: Session = Depends(get_db),
):
    profile_pic_path = None

    if profile_pic:
        filename = f"{username}_{uuid.uuid4().hex}_{profile_pic.filename}"
        file_path = UPLOAD_DIR / filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(profile_pic.file, buffer)

        profile_pic_path = f"uploads/{filename}"

    user_data = schemas.UserCreate(
        full_name=full_name,
        username=username,
        password=password,
        gender=gender,
    )

    return crud.create_user(db=db, user=user_data, profile_pic=profile_pic_path)


# --------------------
# Read Users
# --------------------
@app.get("/users/", response_model=list[schemas.User])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_users(db, skip=skip, limit=limit)


@app.get("/users/{user_id}", response_model=schemas.User)
def read_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# --------------------
# Update User (delete old image if new one uploaded)
# --------------------
@app.put("/users/{user_id}", response_model=schemas.User)
async def update_user(
        user_id: int,
        full_name: str = Form(...),
        username: str = Form(...),
        password: str = Form(None),
        gender: str = Form(...),
        profile_pic: UploadFile = File(None),
        db: Session = Depends(get_db),
):
    # Get existing user from DB
    existing_user = crud.get_user(db, user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_pic_path = None

    if profile_pic:
        # Delete old profile picture if it exists
        if existing_user.profile_pic:
            old_file_path = Path(existing_user.profile_pic)
            if old_file_path.exists():
                old_file_path.unlink()

        # Save new profile picture
        filename = f"{username}_{uuid.uuid4().hex}_{profile_pic.filename}"
        file_path = UPLOAD_DIR / filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(profile_pic.file, buffer)

        profile_pic_path = f"uploads/{filename}"

    user_data = schemas.UserCreate(
        full_name=full_name,
        username=username,
        password=password,
        gender=gender,
    )

    updated_user = crud.update_user(
        db=db,
        user_id=user_id,
        user=user_data,
        profile_pic=profile_pic_path,
    )

    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user


# --------------------
# Delete User (delete image too)
# --------------------
@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete profile picture file if exists
    if user.profile_pic:
        file_path = Path(user.profile_pic)
        if file_path.exists():
            file_path.unlink()

    deleted_user = crud.delete_user(db, user_id)
    if not deleted_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User and profile image deleted successfully"}