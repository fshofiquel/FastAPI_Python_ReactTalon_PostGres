# Architecture Overview

This document describes the architecture of the AI-powered User Management API.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                    │
│                     React + TailwindCSS (port 3000)                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTP/REST
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI SERVER                                 │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │   /users/    │  │    /ai/      │  │   /health    │                   │
│  │   Router     │  │   Router     │  │   Router     │                   │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘                   │
│         │                 │                                              │
│         │    ┌────────────┴────────────┐                                │
│         │    │                         │                                │
│         ▼    ▼                         ▼                                │
│  ┌──────────────────┐         ┌──────────────────┐                      │
│  │      CRUD        │         │    AI Package    │                      │
│  │   Operations     │         │                  │                      │
│  └────────┬─────────┘         │  ┌────────────┐  │                      │
│           │                   │  │Query Parser│  │                      │
│           │                   │  │  (3-tier)  │  │                      │
│           │                   │  └─────┬──────┘  │                      │
│           │                   │        │         │                      │
│           │                   │        ▼         │                      │
│           │                   │  ┌────────────┐  │                      │
│           │                   │  │   Cache    │◄─┼───── Redis (optional)│
│           │                   │  │ (3-layer)  │  │                      │
│           │                   │  └────────────┘  │                      │
│           │                   │        │         │                      │
│           │                   │        ▼         │                      │
│           │                   │  ┌────────────┐  │                      │
│           │                   │  │  Ollama    │  │                      │
│           │                   │  │   LLM      │  │                      │
│           │                   │  └────────────┘  │                      │
│           │                   └──────────────────┘                      │
│           │                            │                                │
│           └────────────┬───────────────┘                                │
│                        │                                                │
│                        ▼                                                │
│              ┌──────────────────┐                                       │
│              │    SQLAlchemy    │                                       │
│              │   (Connection    │                                       │
│              │     Pooling)     │                                       │
│              └────────┬─────────┘                                       │
└───────────────────────┼─────────────────────────────────────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │    PostgreSQL    │
              │    Database      │
              └──────────────────┘
```

## Project Structure

```
project/
├── main.py                 # FastAPI application entry point (~180 lines)
├── config.py               # Application configuration
├── database.py             # SQLAlchemy setup and connection pooling
├── models.py               # SQLAlchemy ORM models
├── schemas.py              # Pydantic request/response schemas
├── crud.py                 # Database CRUD operations
│
├── ai/                     # AI-powered search package
│   ├── __init__.py         # Package exports
│   ├── models.py           # Pydantic models for AI search
│   ├── cache.py            # Multi-layer caching (Redis/memory/file)
│   ├── llm.py              # Ollama LLM integration
│   ├── detectors.py        # Query pattern detection functions
│   ├── query_parser.py     # Query parsing orchestration
│   └── db_queries.py       # AI search database operations
│
├── routers/                # API route handlers
│   ├── __init__.py         # Router exports
│   ├── users.py            # User CRUD endpoints
│   ├── ai_endpoints.py     # AI search endpoints
│   └── health.py           # Health check endpoints
│
├── utils/                  # Utility functions
│   ├── __init__.py         # Utility exports
│   ├── file_handlers.py    # File upload validation/processing
│   └── validators.py       # Input validation helpers
│
└── frontend/               # React frontend application
    └── src/
        ├── App.js          # Main React component
        └── ...
```

## Module Responsibilities

### Core Modules

| Module | Responsibility |
|--------|----------------|
| `main.py` | FastAPI app initialization, middleware, router mounting |
| `config.py` | Centralized configuration (environment, file limits, etc.) |
| `database.py` | SQLAlchemy engine, connection pooling, session management |
| `models.py` | ORM models (User table definition) |
| `schemas.py` | Pydantic schemas for API request/response validation |
| `crud.py` | Database CRUD operations (create, read, update, delete) |

### AI Package

| Module | Responsibility |
|--------|----------------|
| `ai/models.py` | Data models (UserRecord, UserQueryFilters, FilteredResult) |
| `ai/cache.py` | 3-layer caching (Redis, in-memory, file-based) |
| `ai/llm.py` | HTTP client, chat completion, AI ranking |
| `ai/detectors.py` | Pattern detection for gender, sorting, names, etc. |
| `ai/query_parser.py` | Query normalization, simple parsing, AI parsing |
| `ai/db_queries.py` | SQLAlchemy filters, sorting, main search function |

### Routers

| Router | Endpoints |
|--------|-----------|
| `health.py` | `GET /`, `GET /health` |
| `ai_endpoints.py` | `POST /ai/test`, `POST /ai/cache/clear`, `GET /ai/search` |
| `users.py` | `POST /users/`, `GET /users/`, `GET /users/{id}`, `PUT /users/{id}`, `DELETE /users/{id}` |

## Data Flow

### AI Search Flow

```
1. User Query: "show female users named Taylor"
                    │
                    ▼
2. Query Normalization
   - Lowercase, trim whitespace
   - Expand abbreviations (w/ → with)
   - Replace synonyms (women → female)
   - Remove filler words (please, the)
                    │
                    ▼
3. Cache Check (3 layers)
   ┌────────────────┼────────────────┐
   │                │                │
   ▼                ▼                ▼
  Redis        In-Memory           File
  (24hr TTL)   (fast, volatile)   (persistent)
   │                │                │
   └────────────────┼────────────────┘
                    │
            [Cache Hit?] ──Yes──► Return Cached Result
                    │
                   No
                    │
                    ▼
4. Simple Pattern Matching
   - Check exact patterns dict
   - Use detector functions
   - Handle common queries without AI
                    │
            [Match Found?] ──Yes──► Cache & Return
                    │
                   No
                    │
                    ▼
5. AI Parsing (Ollama LLM)
   - Send query with system prompt
   - Parse JSON response
   - Validate and sanitize fields
                    │
                    ▼
6. Database Query
   - Apply filters (gender, name, etc.)
   - Apply sorting (length, date, alpha)
   - Paginate results
                    │
                    ▼
7. Return FilteredResult
   - Results list
   - Total count
   - Applied filters description
   - Parse warnings
```

### User CRUD Flow

```
Create User:
  Frontend Form → POST /users/ → Validate → Save to DB → Return User

Read Users:
  Frontend Load → GET /users/?skip=0&limit=50 → Query DB → Return Paginated List

Update User:
  Edit Form → PUT /users/{id} → Validate → Update DB → Cleanup Old File → Return User

Delete User:
  Delete Button → DELETE /users/{id} → Remove from DB → Cleanup File → Return Success
```

## Caching Strategy

### 3-Layer Cache Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Cache Layers                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 1: Redis (if available)                               │
│  ├── Speed: ~1ms                                             │
│  ├── TTL: 24 hours                                           │
│  ├── Distributed: Yes (shared across instances)              │
│  └── Key format: "query:{normalized_query}"                  │
│                                                              │
│  Layer 2: In-Memory Dict                                     │
│  ├── Speed: ~0.01ms                                          │
│  ├── TTL: Until restart                                      │
│  ├── Distributed: No (process-local)                         │
│  └── Both exact and normalized queries stored                │
│                                                              │
│  Layer 3: File-Based JSON                                    │
│  ├── Speed: ~10ms                                            │
│  ├── TTL: Persistent                                         │
│  ├── Distributed: No (local file)                            │
│  └── File: query_cache.json                                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Query Normalization

Normalization improves cache hit rate by converting similar queries to the same form:

| Original Query | Normalized Form |
|---------------|-----------------|
| "find females" | "show female user" |
| "show me female users" | "show female user" |
| "list all the females" | "show all female" |
| "users w/ pics" | "user with picture" |
| "names beginning with J" | "name starting with j" |

## Connection Pooling

### Database Connection Pool

```
Development:
  pool_size=5, max_overflow=5, echo=True

Production:
  pool_size=20, max_overflow=10, echo=False
  statement_timeout=30s, connect_timeout=10s

Testing:
  pool_size=5, max_overflow=0, echo=True
```

### HTTP Client Pooling

The AI module uses a persistent HTTP client for Ollama API calls:

```python
# Benefits:
# - Skip TCP/TLS handshake (~100-200ms saved per request)
# - HTTP/2 multiplexing support
# - Connection keep-alive

httpx.AsyncClient(
    timeout=60s,
    max_keepalive_connections=5,
    max_connections=10,
    http2=True
)
```

## Security Considerations

1. **Query Injection Prevention**: Newlines stripped from queries
2. **File Upload Validation**: MIME type detection, size limits, dimension limits
3. **CORS Configuration**: Restrictive in production, permissive in development
4. **Password Hashing**: Handled by crud.py (bcrypt)
5. **SQL Injection**: Prevented by SQLAlchemy ORM

## Error Handling

| Error Type | HTTP Status | Response |
|------------|-------------|----------|
| Validation Error | 400 | `{"detail": "error message"}` |
| Not Found | 404 | `{"detail": "User with ID X not found"}` |
| File Too Large | 413 | `{"detail": "File too large. Maximum is 5MB"}` |
| Server Error | 500 | `{"detail": "Internal server error"}` |
| Database Error | 503 | `{"status": "unhealthy", "checks": {...}}` |
