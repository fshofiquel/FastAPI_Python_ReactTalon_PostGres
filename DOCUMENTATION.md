# AI-Powered User Management System Documentation

A comprehensive full-stack application featuring natural language search powered by LLM integration.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
  - [1.1 Technology Stack](#11-technology-stack)
  - [1.2 Architecture Diagram](#12-architecture-diagram)
- [2. Project Setup](#2-project-setup)
  - [2.1 Prerequisites](#21-prerequisites)
  - [2.2 Backend Setup](#22-backend-setup)
  - [2.3 Database Setup](#23-database-setup)
  - [2.4 AI/Ollama Setup](#24-aiollama-setup)
  - [2.5 Frontend Setup](#25-frontend-setup)
  - [2.6 Environment Variables](#26-environment-variables)
- [3. Project Structure](#3-project-structure)
- [4. Database Layer](#4-database-layer)
  - [4.1 Database Configuration](#41-database-configuration)
  - [4.2 User Model](#42-user-model)
  - [4.3 Connection Pooling](#43-connection-pooling)
- [5. CRUD Operations](#5-crud-operations)
  - [5.1 Password Security](#51-password-security)
  - [5.2 User Operations](#52-user-operations)
- [6. API Endpoints](#6-api-endpoints)
  - [6.1 Health Endpoints](#61-health-endpoints)
  - [6.2 User CRUD Endpoints](#62-user-crud-endpoints)
  - [6.3 AI Search Endpoints](#63-ai-search-endpoints)
- [7. AI Module - Core Architecture](#7-ai-module---core-architecture)
  - [7.1 AI-Only Query Processing](#71-ai-only-query-processing)
  - [7.2 LLM Integration](#72-llm-integration)
  - [7.3 Database Query Execution](#73-database-query-execution)
- [8. Frontend Architecture](#8-frontend-architecture)
- [9. Data Flow Examples](#9-data-flow-examples)
- [10. Security Features](#10-security-features)
- [11. Performance Optimizations](#11-performance-optimizations)

---

## 1. Project Overview

This is an **AI-Powered User Management System** that allows administrators to manage users with natural language search capabilities. Users can search using queries like "find female users with Taylor in their name" or "show me the newest users with profile pictures."

### 1.1 Technology Stack

| Layer                | Technology                                |
|----------------------|-------------------------------------------|
| **Backend**          | FastAPI (Python 3.10+)                    |
| **Database**         | PostgreSQL with SQLAlchemy ORM            |
| **AI Engine**        | Ollama LLM (local or remote)              |
| **Frontend**         | React 19 with Tailwind CSS                |
| **Password Hashing** | Argon2 (OWASP recommended)                |

### 1.2 Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                       FRONTEND (React)                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  - User List with Pagination (50/page)                   │  │
│  │  - User Form (Create/Edit with file upload)              │  │
│  │  - AI-Powered Natural Language Search Bar                │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                           ↕ HTTP (Axios)
┌─────────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ /users (CRUD)   │  │ /ai (Search)    │  │ /health         │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                           ↕                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AI Module (Direct LLM Query Processing)                 │   │
│  │  Query → AI Parse → SQL Filters → Database               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↕                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  CRUD Layer (crud.py) - Argon2 Hashing + Validation      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         ↕ SQL                              ↕ HTTP
┌─────────────────┐                ┌─────────────────────────────┐
│   PostgreSQL    │                │   Ollama LLM                │
│   Database      │                │   (Local or Remote)         │
└─────────────────┘                └─────────────────────────────┘
```

---

## 2. Project Setup

### 2.1 Prerequisites

Ensure you have the following installed:

- **Python 3.10+**
- **PostgreSQL 13+**
- **Node.js 18+** (for frontend)
- **Ollama** (for AI features) - [https://ollama.ai](https://ollama.ai) or a remote Ollama endpoint

### 2.2 Backend Setup

1. **Clone the repository and navigate to the project directory:**

```bash
cd FastAPI_Python_ReactTalon_PostGres
```

2. **Create and activate a virtual environment:**

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

3. **Install Python dependencies:**

```bash
pip install -r requirements.txt
```

Key dependencies include:
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `sqlalchemy` - ORM
- `psycopg2-binary` - PostgreSQL driver
- `passlib[argon2]` - Password hashing
- `python-multipart` - File uploads
- `httpx` - Async HTTP client for AI
- `python-magic` - MIME type detection
- `pillow` - Image validation

4. **Run the backend server:**

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with documentation at `/docs`.

### 2.3 Database Setup

1. **Create a PostgreSQL database:**

```sql
-- Connect to PostgreSQL
psql -U postgres

-- Create database
CREATE DATABASE user_management;

-- Create user (optional)
CREATE USER myuser WITH PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE user_management TO myuser;
```

2. **Tables are created automatically** when you run the application for the first time via SQLAlchemy's `create_all()`:

```python
# main.py:46
models.Base.metadata.create_all(bind=engine)
```

### 2.4 AI/Ollama Setup

1. **Install Ollama** from [https://ollama.ai](https://ollama.ai)

2. **Pull a model** (e.g., Qwen3):

```bash
ollama pull qwen3:1.7b
```

3. **Start Ollama server:**

```bash
ollama serve
```

The default endpoint is `http://localhost:11434`.

4. **Configure in `.env`:**

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_API_KEY=your_api_key_if_required
OLLAMA_MODEL=qwen3:1.7b
```

### 2.5 Frontend Setup

1. **Navigate to the frontend directory:**

```bash
cd frontend
```

2. **Install dependencies:**

```bash
npm install
```

3. **Start the development server:**

```bash
npm start
```

The React app will be available at `http://localhost:3000`.

### 2.6 Environment Variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://username:password@localhost:5432/user_management

# Environment (development, production, testing)
ENVIRONMENT=development

# AI Configuration
OLLAMA_BASE_URL=http://localhost:11434  # or your remote Ollama endpoint
OLLAMA_API_KEY=your_api_key
OLLAMA_MODEL=qwen3:1.7b  # or any compatible model

# Frontend URL (for production CORS)
FRONTEND_URL=https://yourfrontend.com
```

---

## 3. Project Structure

```
FastAPI_Python_ReactTalon_PostGres/
├── main.py                    # FastAPI entry point
├── config.py                  # Configuration settings
├── models.py                  # SQLAlchemy ORM models
├── schemas.py                 # Pydantic request/response schemas
├── database.py                # Database connection & pooling
├── crud.py                    # CRUD operations layer
│
├── routers/                   # API route handlers
│   ├── __init__.py
│   ├── users.py              # User CRUD endpoints
│   ├── ai_endpoints.py       # AI search endpoints
│   └── health.py             # Health check endpoints
│
├── ai/                        # AI/NLP module
│   ├── __init__.py           # Module exports
│   ├── llm.py                # Ollama LLM integration (persistent client, warmup)
│   ├── query_parser.py       # AI-based query parsing
│   ├── db_queries.py         # Database query execution
│   └── models.py             # Pydantic models for AI
│
├── utils/                     # Utility functions
│   ├── file_handlers.py      # File upload handling
│   └── validators.py         # Input validation
│
├── frontend/                  # React frontend
│   ├── src/
│   │   ├── App.js            # Main React component
│   │   └── App.css           # Styles
│   ├── package.json
│   └── tailwind.config.js
│
├── uploads/                   # Profile picture storage
├── .env                       # Environment variables
└── pyproject.toml             # Python dependencies (uv)
```

---

## 4. Database Layer

### 4.1 Database Configuration

The database connection is managed in `database.py` with environment-specific pooling:

```python
# database.py - Connection pooling configuration

if ENVIRONMENT == "production":
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,          # Maximum persistent connections
        max_overflow=10,       # Additional connections under load
        pool_timeout=30,       # Wait time before timeout
        pool_recycle=3600,     # Recycle connections after 1 hour
        pool_pre_ping=True,    # Validate connections before use
    )
elif ENVIRONMENT == "development":
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        echo=True,             # Log SQL queries for debugging
    )
```

**Session Management with Dependency Injection:**

```python
# database.py:181-205

def get_db():
    """
    Database session dependency for FastAPI.
    Automatically handles cleanup even on errors.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()
```

Usage in route handlers:

```python
@app.get("/users/")
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()
```

### 4.2 User Model

The `User` model in `models.py` defines the database schema with validation and indexes:

```python
# models.py - User table definition

class User(Base):
    __tablename__ = "users"

    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # Argon2 hash
    gender = Column(String(20), nullable=False)
    profile_pic = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Indexes for query optimization
    __table_args__ = (
        Index('idx_user_username', 'username', unique=True),
        Index('idx_user_gender', 'gender'),
        Index('idx_user_fullname', 'full_name'),
        Index('idx_user_gender_name', 'gender', 'full_name'),  # Composite for AI search
        Index('idx_user_created', 'created_at'),
        CheckConstraint("gender IN ('Male', 'Female', 'Other')", name='check_gender_valid'),
    )
```

**Model Validation with SQLAlchemy Validators:**

```python
# models.py - Username validation example

@validates('username')
def validate_username(self, key, username):
    """
    Validate username format:
    - 3-50 characters
    - Alphanumeric + underscore only
    """
    if not username:
        raise ValueError("Username cannot be empty")

    username = username.strip()

    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters long")

    if not re.match(r'^\w+$', username):
        raise ValueError(
            "Username can only contain letters, numbers, and underscores."
        )

    return username
```

### 4.3 Connection Pooling

The application uses SQLAlchemy's `QueuePool` for efficient connection management:

| Environment | Pool Size | Overflow | Pre-ping |
|-------------|-----------|----------|----------|
| Development | 5         | 5        | Yes      |
| Production  | 20        | 10       | Yes      |
| Testing     | 5         | 0        | Yes      |

**Monitor pool statistics:**

```python
# database.py:234-248

def get_pool_stats() -> dict:
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "total_connections": pool.size() + pool.overflow()
    }
```

---

## 5. CRUD Operations

The `crud.py` module provides a data access layer between API endpoints and the database.

### 5.1 Password Security

The application uses **Argon2** for password hashing, which is the winner of the Password Hashing Competition and recommended by OWASP:

```python
# crud.py - Password hashing configuration

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2"],  # Memory-hard, GPU-resistant
    deprecated="auto"
)

def get_password_hash(password: str) -> str:
    """Hash a password using Argon2."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with timing-safe comparison."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False
```

**Authentication with Timing Attack Prevention:**

```python
# crud.py:523-558

def authenticate_user(db: Session, username: str, password: str) -> Optional[models.User]:
    """
    Authenticate user with constant-time verification.
    """
    user = get_user_by_username(db, username)

    if not user:
        # Still hash a dummy password to prevent timing attacks
        pwd_context.hash("dummy_password_that_will_never_match")
        return None

    if not verify_password(password, user.password):
        return None

    return user
```

### 5.2 User Operations

**Create User:**

```python
# crud.py:310-384

def create_user(db: Session, user: schemas.UserCreate, profile_pic: Optional[str] = None) -> models.User:
    """Create a new user with validation and password hashing."""
    try:
        # Check username uniqueness
        if username_exists(db, user.username):
            raise ValueError(f"Username '{user.username}' is already taken")

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

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        return db_user

    except IntegrityError as e:
        db.rollback()
        if "unique constraint" in str(e).lower():
            raise ValueError("Username already exists")
        raise ValueError("Database constraint violation")
```

**Update User (Password Optional):**

```python
# crud.py:390-472

def update_user(db: Session, user_id: int, user: schemas.UserCreate, profile_pic: Optional[str] = None):
    db_user = get_user(db, user_id)
    if not db_user:
        return None

    # Check username uniqueness (excluding current user)
    if user.username != db_user.username:
        if username_exists(db, user.username, exclude_id=user_id):
            raise ValueError(f"Username '{user.username}' is already taken")

    # Update fields
    db_user.full_name = user.full_name
    db_user.username = user.username
    db_user.gender = user.gender

    if profile_pic is not None:
        db_user.profile_pic = profile_pic

    # Update password only if provided (allows profile updates without password change)
    if user.password is not None and user.password.strip():
        db_user.password = get_password_hash(user.password)

    db.commit()
    db.refresh(db_user)
    return db_user
```

---

## 6. API Endpoints

### 6.1 Health Endpoints

| Endpoint  | Method | Description                |
|-----------|--------|----------------------------|
| `/`       | GET    | API info and status        |
| `/health` | GET    | Comprehensive health check |

**Health Check Response:**

```json
{
  "status": "healthy",
  "timestamp": 1705678901,
  "checks": {
    "database": {
      "status": "healthy",
      "pool_stats": {
        "pool_size": 5,
        "checked_in": 4,
        "checked_out": 1
      }
    },
    "file_system": {
      "status": "healthy"
    }
  }
}
```

### 6.2 User CRUD Endpoints

| Endpoint      | Method | Description                               |
|---------------|--------|-------------------------------------------|
| `/users/`     | POST   | Create new user (FormData with file)      |
| `/users/`     | GET    | List users with pagination                |
| `/users/{id}` | GET    | Get single user by ID                     |
| `/users/{id}` | PUT    | Update user (FormData, password optional) |
| `/users/{id}` | DELETE | Delete user                               |

**List Users Response:**

```json
{
  "users": [
    {
      "id": 1,
      "full_name": "John Doe",
      "username": "johndoe",
      "gender": "Male",
      "profile_pic": "/uploads/abc123.jpg",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 150,
  "skip": 0,
  "limit": 50,
  "has_more": true
}
```

### 6.3 AI Search Endpoints

| Endpoint          | Method | Description             |
|-------------------|--------|-------------------------|
| `/ai/search`      | GET    | Natural language search |
| `/ai/test`        | POST   | Test AI connection      |

**AI Search Example:**

```bash
GET /ai/search?query=female+users+with+Taylor&limit=50&skip=0
```

**Response:**

```json
{
  "query": "female users with Taylor",
  "results": [
    {
      "id": 5,
      "full_name": "Taylor Swift",
      "username": "taylorswift",
      "gender": "Female",
      "profile_pic": "/uploads/taylor.jpg"
    }
  ],
  "count": 1,
  "total": 1,
  "has_more": false,
  "message": "Search completed successfully",
  "query_understood": true,
  "parse_warnings": [],
  "filters_applied": {
    "gender": "Female",
    "name_contains": "Taylor"
  }
}
```

---

## 7. AI Module - Core Architecture

The AI module is the heart of the natural language search functionality. It uses **direct AI processing** for maximum flexibility in understanding natural language queries.

### 7.1 AI-Only Query Processing

```
User Query: "find female users with Taylor"
                    ↓
┌───────────────────────────────────────────────────────────────┐
│  AI PARSING (Ollama LLM)                                      │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 1. Send query directly to Ollama LLM                    │  │
│  │ 2. AI understands context, synonyms, natural language   │  │
│  │ 3. Parse JSON response                                  │  │
│  │ 4. Validate and sanitize fields                         │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
                            ↓
                  UserQueryFilters object
                            ↓
                  Apply to Database Query
                            ↓
                         Results
```

**Advantages of AI-Only Approach:**
- Handles complex queries that pattern matching would miss
- Understands context, synonyms, and natural language nuances
- Simpler architecture with fewer moving parts
- No cache invalidation issues

**Main Entry Point - `parse_query_ai()`:**

```python
# ai/query_parser.py

async def parse_query_ai(user_query: str) -> UserQueryFilters:
    """
    Parse user query into structured filters using AI.

    Every query is sent to the Ollama LLM for processing.
    The AI understands natural language and returns structured JSON.
    """
    user_query = user_query.strip()

    # Fix common gender typos before sending to AI
    # e.g., "fmale" -> "female", "femal" -> "female"
    words = user_query.split()
    corrected_words = [_GENDER_TYPOS.get(w.lower(), w) for w in words]
    user_query = " ".join(corrected_words)

    # Build minimal user prompt (schema is in system prompt)
    user_prompt = f'"{user_query}"\nJSON:'

    # Send to AI for parsing
    ai_response = await chat_completion(user_prompt, SYSTEM_PROMPT)

    # Extract and validate JSON from response
    json_str = _extract_json_from_response(ai_response)
    parsed_dict = json.loads(json_str)

    # Sanitize and validate fields
    sanitized = _sanitize_ai_response(parsed_dict)

    return UserQueryFilters(**sanitized)
```

### 7.2 LLM Integration

The `ai/llm.py` module handles communication with the Ollama API:

**Persistent HTTP Client:**

```python
# ai/llm.py

_http_client: Optional[httpx.AsyncClient] = None

def get_http_client() -> httpx.AsyncClient:
    """
    Get or create a persistent HTTP client with connection pooling.

    Benefits:
    - Skips TCP/TLS handshake for subsequent requests
    - Saves ~100-200ms per request
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _http_client
```

**Model Warmup:**

```python
# ai/llm.py

async def warmup_model() -> bool:
    """
    Warm up the AI model by sending a simple request at startup.

    This pre-loads the model weights into memory on the Ollama server,
    avoiding the cold-start delay (model loading from disk) on the
    first real user request.

    Note: This does NOT cache prompts or reuse KV pairs - each request
    still processes the full prompt.
    """
    try:
        logger.info(f"Warming up AI model: {OLLAMA_MODEL}")
        await chat_completion("hi", "Reply with just 'ok'")
        logger.info("AI model warmup complete")
        return True
    except Exception as exc:
        logger.warning(f"AI model warmup failed: {exc}")
        return False
```

**Chat Completion with Native Ollama API:**

```python
# ai/llm.py

async def chat_completion(user_input: str, system_prompt: Optional[str] = None) -> str:
    """Send request to Ollama native API for chat completion."""

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    headers = {
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,  # Disable Qwen3 chain-of-thought reasoning
        "options": {
            "temperature": 0.0,
            "top_p": 0.95,
        },
        "keep_alive": "10m",  # Keep model in memory to avoid reload latency
    }

    client = get_http_client()
    response = await client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    content = data["message"]["content"]

    # Strip Qwen3 <think>...</think> blocks if model still emits them
    content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

    return content
```

**Key Design Decisions:**

- **Native Ollama API (`/api/chat`)**: Uses Ollama's native endpoint instead of the OpenAI-compatible
  `/v1/chat/completions`. The native API supports `think: false` to actually disable Qwen3's
  chain-of-thought reasoning at the generation level, rather than just hiding it in the response.
- **`think: false`**: Qwen3 models default to generating internal reasoning in `<think>` tags before
  responding. For structured JSON parsing tasks, this is unnecessary and adds significant latency
  (30-40+ seconds). Disabling it reduces response times to 1-10 seconds.
- **`<think>` tag stripping**: Safety net in case the model ignores the `think: false` flag.

**Important Note on `keep_alive`:**
The `keep_alive` parameter keeps the model weights loaded in memory on the Ollama server. This avoids the disk-to-memory loading time (~5-30 seconds) between requests. However, it does NOT:
- Cache prompts or responses
- Reuse KV pairs from previous requests
- Remember context between requests

Each request still processes the full prompt from scratch.

**AI Query Parsing Prompt:**

The system prompt is kept intentionally concise to optimize performance on the small 1.7B model.
Shorter prompts mean less prefill time and better attention to key rules.

```python
# ai/query_parser.py - System prompt for LLM

SYSTEM_PROMPT = """Output ONLY valid JSON. No other text.

Keys: gender, name_substr, starts_with_mode, name_length_parity, has_profile_pic, sort_by, sort_order
Defaults: null for optional fields, false for starts_with_mode, "desc" for sort_order.

gender: "Male"|"Female"|"Other"|null. ladies/women/gals=Female, guys/men/gentlemen=Male, non-binary=Other.
name_substr: extracted name or letter. starts_with_mode=true only for "starts with"/"begins with".
has_profile_pic: true if "with pic/photo", false if "without/w/o/no pic", else null.
sort_by: "name_length"=longest/shortest name, "username_length"=longest/shortest username, "name"=alphabetical, "created_at"=newest/oldest.
sort_order: "desc"=longest/newest, "asc"=shortest/oldest/alphabetical.
name_length_parity: "odd"|"even" for odd/even letter count, else null.

Examples:
"female users" -> {"gender":"Female","name_substr":null,...}
"shortest name" -> {"gender":null,...,"sort_by":"name_length","sort_order":"asc"}
"female users with longest name" -> {"gender":"Female",...,"sort_by":"name_length","sort_order":"desc"}
"""
```

**User Prompt:**

The user prompt is minimal — the schema and rules are already in the system prompt, so repeating
them per-request wastes tokens and increases latency.

```python
user_prompt = f'"{user_query}"\nJSON:'
```

**AI Response Validation:**

```python
# ai/query_parser.py

def _extract_json_from_response(response: str) -> str:
    """Extract JSON from AI response, handling markdown, prefixes, and think tags."""
    result = response.strip()

    # Strip Qwen3 <think>...</think> blocks if present
    result = re.sub(r"<think>[\s\S]*?</think>", "", result).strip()

    # Remove markdown code blocks
    if "```" in result:
        start = result.find("```")
        end = result.rfind("```")
        if start != end:
            content = result[start + 3:end]
            if content.startswith("json"):
                content = content[4:]
            result = content.strip()

    # Extract JSON object
    start_idx = result.find('{')
    end_idx = result.rfind('}')
    if start_idx != -1 and end_idx > start_idx:
        result = result[start_idx:end_idx + 1]

    return result
```

**Gender Typo Pre-Processing:**

Common misspellings are corrected in code before reaching the AI, since a 1.7B model
cannot reliably spell-check (e.g., it sees "male" inside "fmale"):

```python
# ai/query_parser.py

_GENDER_TYPOS = {
    "fmale": "female",
    "femal": "female",
    "femle": "female",
    "feamle": "female",
    "famale": "female",
    "mael": "male",
    "mlae": "male",
    "maile": "male",
}
```

### 7.3 Database Query Execution

The `ai/db_queries.py` module applies filters to SQLAlchemy queries:

**Filter Application:**

```python
# ai/db_queries.py

def _apply_filters(query, filters: UserQueryFilters, models):
    """Apply all filters to the SQLAlchemy query."""

    # Gender filter
    if filters.gender:
        query = query.filter(models.User.gender == filters.gender)

    # Name search (starts with or contains)
    if filters.name_substr:
        name_str = str(filters.name_substr)
        pattern = f"{name_str}%" if filters.starts_with_mode else f"%{name_str}%"
        query = query.filter(models.User.full_name.ilike(pattern))

    # Name length parity (odd/even number of letters)
    if filters.name_length_parity:
        name_without_spaces = func.replace(models.User.full_name, ' ', '')
        name_length = func.length(name_without_spaces)
        remainder = 1 if filters.name_length_parity == "odd" else 0
        query = query.filter(name_length % 2 == remainder)

    # Profile picture filter
    if filters.has_profile_pic is True:
        query = query.filter(models.User.profile_pic.isnot(None))
        query = query.filter(models.User.profile_pic != '')
    elif filters.has_profile_pic is False:
        query = query.filter(
            (models.User.profile_pic.is_(None)) | (models.User.profile_pic == '')
        )

    return query
```

**Sorting Application:**

```python
# ai/db_queries.py

def _apply_sorting(query, filters: UserQueryFilters, models):
    """Apply sorting to the SQLAlchemy query."""
    if not filters.sort_by:
        return query

    from sqlalchemy import desc, asc
    order_func = desc if filters.sort_order == "desc" else asc

    sort_columns = {
        "name_length": func.length(func.replace(models.User.full_name, ' ', '')),
        "username_length": func.length(models.User.username),
        "name": models.User.full_name,
        "username": models.User.username,
        "created_at": models.User.created_at,
    }

    column = sort_columns.get(filters.sort_by)
    if column is not None:
        query = query.order_by(order_func(column))

    return query
```

**Main Filter Function:**

```python
# ai/db_queries.py

async def filter_records_ai(
    db: Session,
    user_query: str,
    batch_size: int = 20,
    skip: int = 0
) -> FilteredResult:
    """
    Main entry point for AI-powered search.

    1. Parses natural language query using AI
    2. Queries database with filters and pagination
    """
    # Parse query using AI
    filters = await parse_query_ai(user_query)

    # Query database with pagination
    db_results, total_count = query_users(db, filters, limit=batch_size, skip=skip)

    return FilteredResult(
        results=db_results,
        total_count=total_count,
        query_understood=filters.query_understood,
        parse_warnings=filters.parse_warnings,
        filters_applied=build_filters_applied(filters)
    )
```

---

## 8. Frontend Architecture

The React frontend (`frontend/src/App.js`) provides a user interface for:

- **User List**: Paginated table with 50 users per page
- **CRUD Forms**: Create and edit users with file upload
- **AI Search**: Natural language search bar
- **Avatar Generation**: Canvas-based initials when no profile picture

**Key State Management:**

```javascript
// User data state
const [users, setUsers] = useState([]);
const [totalUsers, setTotalUsers] = useState(0);
const [currentPage, setCurrentPage] = useState(1);

// Search state
const [searchQuery, setSearchQuery] = useState('');
const [activeSearchQuery, setActiveSearchQuery] = useState('');
const [isSearching, setIsSearching] = useState(false);
const [searchInfo, setSearchInfo] = useState(null);

// Form state
const [formData, setFormData] = useState({
  full_name: '',
  username: '',
  password: '',
  gender: 'Male',
  profile_pic: null
});
```

**API Integration:**

```javascript
// Fetch users (normal or search)
const fetchUsers = async () => {
  const skip = (currentPage - 1) * USERS_PER_PAGE;

  let response;
  if (activeSearchQuery) {
    // AI search endpoint
    response = await axios.get(`${API_URL}/ai/search`, {
      params: { query: activeSearchQuery, skip, limit: USERS_PER_PAGE }
    });
    setUsers(response.data.results);
    setTotalUsers(response.data.total);
    setSearchInfo({
      filters_applied: response.data.filters_applied,
      parse_warnings: response.data.parse_warnings,
      query_understood: response.data.query_understood
    });
  } else {
    // Standard list endpoint
    response = await axios.get(`${API_URL}/users/`, {
      params: { skip, limit: USERS_PER_PAGE }
    });
    setUsers(response.data.users);
    setTotalUsers(response.data.total);
  }
};
```

---

## 9. Data Flow Examples

### Example 1: Creating a User

```
1. User fills form in React
   ↓
2. handleSubmit() validates file (MIME type, size)
   ↓
3. FormData with file sent to POST /users/
   ↓
4. FastAPI receives request
   ↓
5. validate_image_upload() checks:
   - MIME type (via python-magic)
   - File size (max 5MB)
   - Image dimensions (max 4096x4096)
   ↓
6. save_profile_picture() saves file with UUID name
   ↓
7. crud.create_user():
   - Checks username uniqueness
   - Hashes password with Argon2
   - Inserts to database
   ↓
8. Returns User object with ID
   ↓
9. React updates UI and shows success message
```

### Example 2: AI Search Flow

```
Query: "female users with Taylor"
   ↓
┌─────────────────────────────────────────────────────────┐
│ parse_query_ai()                                        │
├─────────────────────────────────────────────────────────┤
│ 1. Send query to Ollama LLM                             │
│ 2. AI understands: female + name containing Taylor      │
│ 3. AI returns JSON:                                     │
│    {"gender": "Female", "name_substr": "Taylor", ...}   │
│ 4. Validate and sanitize response                       │
│ 5. Return: UserQueryFilters(                            │
│      gender="Female",                                   │
│      name_substr="Taylor",                              │
│      starts_with_mode=False                             │
│    )                                                    │
└─────────────────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────────────────┐
│ Database Query (via SQLAlchemy)                         │
├─────────────────────────────────────────────────────────┤
│ SELECT * FROM users                                     │
│ WHERE gender = 'Female'                                 │
│   AND full_name ILIKE '%Taylor%'                        │
│ OFFSET 0 LIMIT 50;                                      │
└─────────────────────────────────────────────────────────┘
   ↓
Results returned with filters_applied info
```

### Example 3: Complex Query with AI

```
Query: "users with odd number of letters in their name"
   ↓
1. Send to Ollama LLM
   ↓
2. AI understands the concept of "odd number of letters"
   ↓
3. AI returns: {"name_length_parity": "odd", ...}
   ↓
4. Database query:
   SELECT * FROM users
   WHERE LENGTH(REPLACE(full_name, ' ', '')) % 2 = 1
   ↓
5. Results: Users with odd-length names (ignoring spaces)
```

---

## 10. Security Features

| Feature                        | Implementation                                   | Location                   |
|--------------------------------|--------------------------------------------------|----------------------------|
| **Password Hashing**           | Argon2 (OWASP recommended)                       | `crud.py:78-81`            |
| **Timing-Safe Verification**   | Prevents timing attacks                          | `crud.py:105-122`          |
| **SQL Injection Prevention**   | Parameterized queries via SQLAlchemy             | All database operations    |
| **Input Validation**           | Pydantic schemas + SQLAlchemy validators         | `schemas.py`, `models.py`  |
| **File Upload Security**       | MIME type whitelist, size limits, UUID filenames | `utils/file_handlers.py`   |
| **CORS Protection**            | Environment-specific origins                     | `main.py:90-114`           |
| **AI Response Sanitization**   | Strict JSON validation + field normalization     | `ai/query_parser.py`       |
| **Input Pre-Processing**       | Gender typo correction before AI processing      | `ai/query_parser.py`       |

**Example - AI Response Sanitization:**

```python
# ai/query_parser.py - Validate all AI output fields
def _sanitize_ai_response(parsed_dict: dict) -> dict:
    """Validate and sanitize all fields in parsed AI response."""
    if "gender" in parsed_dict:
        parsed_dict["gender"] = _validate_gender(parsed_dict["gender"])
    if "name_substr" in parsed_dict:
        parsed_dict["name_substr"] = _validate_name_substr(parsed_dict["name_substr"])
    if "sort_by" in parsed_dict:
        parsed_dict["sort_by"] = _validate_sort_by(parsed_dict["sort_by"])
    # ... validates all 7 fields
    return parsed_dict
```

---

## 11. Performance Optimizations

### Database Optimizations

1. **Connection Pooling**: Reuses connections instead of creating new ones
2. **Strategic Indexes**: 5 indexes on User table for common query patterns
3. **Pagination**: Limits results to prevent memory issues

### AI Optimizations

1. **Thinking Mode Disabled**: Uses native Ollama API with `think: false` to skip Qwen3's
   chain-of-thought reasoning, reducing response times from ~40s to ~1-10s
2. **Simplified Prompt**: Concise system prompt (~1,100 chars) optimized for 1.7B model attention
3. **Minimal User Prompt**: Only sends the query + `JSON:` — schema is in the system prompt
4. **Gender Typo Pre-Processing**: Deterministic code-level correction before AI, avoiding
   unreliable spell-checking by the small model
5. **Model Warmup**: Pre-loads AI model at startup to avoid cold-start delays
6. **Keep-Alive**: 10-minute keep-alive keeps model weights in memory
7. **Persistent HTTP Client**: Saves ~100-200ms per AI request by reusing connections
8. **Native Ollama API**: Uses `/api/chat` instead of `/v1/chat/completions` for direct
   control over generation parameters

### Response Time Expectations

| Component         | Local Ollama    | Remote Ollama (think:false) |
|-------------------|-----------------|-----------------|
| AI Processing     | ~500-1500ms     | ~1000-10000ms   |
| Database Query    | ~50-100ms       | ~50-100ms       |
| **Total**         | ~600-1600ms     | ~1000-10000ms   |

**Note:** Response times depend heavily on:
- Model size (smaller models like qwen3:1.7b are faster)
- Network latency (for remote endpoints)
- Whether `think: false` is properly applied (without it, expect ~30-45s per query)
- Whether model is already loaded (first request may be slower)

---

## Summary

This AI-Powered User Management System demonstrates:

1. **Modern Architecture**: Clean separation between layers (API, CRUD, AI, Database)
2. **Intelligent Search**: Direct AI processing for maximum natural language understanding
3. **Security-First**: Argon2 passwords, parameterized queries, input validation
4. **Production-Ready**: Connection pooling, health checks, comprehensive logging
5. **User-Friendly**: Natural language search, responsive UI, helpful error messages

The codebase follows professional software engineering practices with extensive documentation, comprehensive error handling, and thoughtful architectural decisions.

**AI Architecture Notes:**
- Every query is processed by the Ollama LLM for maximum flexibility
- Model warmup at startup avoids cold-start delays
- Keep-alive keeps model loaded in memory between requests
- Persistent HTTP client reuses connections for efficiency
