# 🚀 FastAPI + React + PostgreSQL User Management with AI Search

A full-stack user management system featuring **AI-powered natural language search**, built with FastAPI, React, and PostgreSQL. Search users naturally with queries like "female users with Taylor in their name" or "users starting with J" - powered by Ollama AI with intelligent caching for blazing-fast performance.

## ✨ Features

### Core Functionality
- ✅ Full CRUD operations (Create, Read, Update, Delete)
- ✅ Profile image upload and storage
- ✅ Automatic avatar generation with user initials
- ✅ Gender-based avatar color coding
- ✅ Clean, responsive table UI with Tailwind CSS

### 🤖 AI-Powered Search
- **Natural Language Queries**: Search using plain English
  - `"female users with Taylor"`
  - `"users starting with J"`
  - `"list all male"`
- **3-Tier Speed System**:
  - **Tier 1**: Exact pattern matching (instant)
  - **Tier 2**: Keyword parsing with regex (< 5ms)
  - **Tier 3**: Remote AI fallback for complex queries
- **Smart Caching**:
  - Exact cache for repeated queries
  - Fuzzy cache for similar queries
  - Results persist in memory until server restart
- **Auto Batch Sizing**: Intelligently adjusts result limits based on query type

## 🛠️ Tech Stack

### Backend
- **Python 3.10+**
- **FastAPI** - Modern async web framework
- **SQLAlchemy** - ORM
- **PostgreSQL** - Database
- **asyncpg** - Async PostgreSQL driver
- **Pydantic** - Data validation
- **httpx** - Async HTTP client
- **Uvicorn** - ASGI server

### Frontend
- **React 18**
- **Axios** - HTTP client
- **Tailwind CSS** - Styling
- **HTML5 Canvas** - Avatar generation

### AI Integration
- **Ollama** - Local AI model hosting
- **qwen3:1.7b** - Fast, efficient language model
- Custom query parsing and caching system

## 📁 Project Structure

```
FastAPI_Python_ReactTalon_PostGres/
├── 📄 main.py                    # FastAPI application entry point
├── 📄 ai.py                      # AI search logic and caching
├── 📄 database.py                # Database configuration
├── 📄 models.py                  # SQLAlchemy models
├── 📄 schemas.py                 # Pydantic schemas
├── 📄 crud.py                    # Database operations
├── 📄 requirements.txt           # Python dependencies
├── 📄 .env                       # Environment variables
├── 📂 uploads/                   # User profile images
├── 📂 frontend/
│   ├── 📂 src/
│   │   ├── 📄 App.js            # Main React component with AI search
│   │   ├── 📄 App.css           # Styles and animations
│   │   ├── 📄 index.js          # React entry point
│   │   └── 📄 index.css         # Global Tailwind styles
│   ├── 📄 package.json
│   └── 📄 tailwind.config.js
└── 📄 README.md
```

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 16+
- PostgreSQL
- Ollama (for AI search)

### 1️⃣ Backend Setup

**Clone the repository:**
```bash
git clone https://github.com/fshofiquel/FastAPI_Python_ReactTalon_PostGres.git
cd FastAPI_Python_ReactTalon_PostGres
```

**Create and activate virtual environment:**
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Configure environment variables:**

Create a `.env` file in the root directory:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/your_database
OLLAMA_BASE_URL=http://your-ollama-server:11434
OLLAMA_API_KEY=your_api_key
OLLAMA_MODEL=qwen3:1.7b
```

**Run database migrations:**
```bash
# Tables are created automatically on first run
```

**Start the backend:**
```bash
uvicorn main:app --reload
```

Backend will run at: **http://localhost:8000**

### 2️⃣ Frontend Setup

**Navigate to frontend directory:**
```bash
cd frontend
```

**Install dependencies:**
```bash
npm install
```

**Start the React app:**
```bash
npm start
```

Frontend will run at: **http://localhost:3000**

### 3️⃣ Ollama Setup (for AI Search)

**Install Ollama:**
```bash
# Visit https://ollama.com/download
# Or on Linux:
curl -fsSL https://ollama.com/install.sh | sh
```

**Pull the qwen3 model:**
```bash
ollama pull qwen3:1.7b
```

**Start Ollama server:**
```bash
ollama serve
```

## 📡 API Endpoints

### Standard CRUD
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/users/` | Get all users |
| `GET` | `/users/{id}` | Get user by ID |
| `POST` | `/users/` | Create new user |
| `PUT` | `/users/{id}` | Update user |
| `DELETE` | `/users/{id}` | Delete user |

### AI Search
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/ai/search` | Natural language search |
| `GET` | `/ai/search/count` | Get result count without fetching |
| `POST` | `/ai/test` | Test AI connection |

**AI Search Parameters:**
- `query` (required): Natural language search query
- `batch_size` (optional): Max results (auto-adjusted if not specified)
- `enable_ranking` (optional): Enable AI-based result ranking (default: false)

**Example Requests:**
```bash
# Simple search
GET /ai/search?query=female users with Taylor

# With custom batch size
GET /ai/search?query=users starting with J&batch_size=10

# With ranking enabled
GET /ai/search?query=male users&enable_ranking=true
```

## 🔍 AI Search Examples

### Pattern Matching (Instant)
```
"list all female"
"show male"
"all users"
```

### Keyword Parsing (< 5ms)
```
"female users with Taylor"
"users named Jordan"
"users starting with C"
"male users with Smith in their name"
```

### AI-Powered (Uses Remote Model)
```
"users whose names rhyme with Bailey"
"find users whose full name is longer than 12 characters"
"show me users with three-word names"
```

## 🎨 Profile Images & Avatars

### Uploaded Images
- Stored in `uploads/` directory
- Unique filenames prevent collisions
- Automatically deleted when user is removed

### Generated Avatars
When no image is uploaded, avatars are automatically generated with:
- **User initials** (first letters of name)
- **Color-coded backgrounds**:
  - 🔵 **Male**: Blue (#3B82F6)
  - 🩷 **Female**: Pink (#EC4899)
  - 🟣 **Other**: Purple (#8B5CF6)
  - ⚪ **Default**: Gray (#9CA3AF)

## 💾 Database Schema

### Users Table
| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer | Primary key (auto-increment) |
| `full_name` | String | User's full name |
| `username` | String | Unique username |
| `password` | String | Hashed password |
| `gender` | String | Male/Female/Other |
| `profile_pic` | String | Path to profile image |

## 🧠 AI Search Architecture

### 3-Tier Query Processing

```
User Query
    ↓
┌─────────────────────────┐
│   Tier 1: Exact Match   │ → Instant (0ms)
│   Pattern Dictionary    │
└─────────────────────────┘
    ↓ (if no match)
┌─────────────────────────┐
│  Tier 2: Keyword Parse  │ → Very Fast (<5ms)
│   Regex + Simple Logic  │
└─────────────────────────┘
    ↓ (if no match)
┌─────────────────────────┐
│   Tier 3: Remote AI     │ → Slower (network dependent)
│   Ollama qwen3:1.7b     │
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│   Smart Caching System  │
│   Exact + Fuzzy Match   │
└─────────────────────────┘
```

### Caching System

**Exact Cache:**
```
Query: "list all female"
→ Instant retrieval on exact match
```

**Fuzzy Cache:**
```
Query: "show me all females"
→ Normalizes to: "show all female"
→ Matches cached result instantly
```

**Cache Features:**
- In-memory Python dictionary
- Automatic normalization
- Persists until server restart
- No size limits (RAM permissive)

## 🎯 Performance Optimization

### Query Speed
- **Pattern Match**: < 1ms
- **Keyword Parse**: < 5ms
- **AI Parse (uncached)**: 5-30s (network dependent)
- **AI Parse (cached)**: < 1ms

### Smart Batch Sizing
```python
# Name searches: 50 results
"users named Taylor" → LIMIT 50

# Broad queries: 100 results  
"list all female" → LIMIT 100

# Default: 50 results
```

## 🔒 Security Notes

⚠️ **This project is for development/learning purposes:**
- Passwords stored as plain text (use bcrypt in production)
- No authentication/authorization implemented
- CORS enabled for all origins
- Not production-ready

**For production, implement:**
- Password hashing (bcrypt/argon2)
- JWT authentication
- Input validation & sanitization
- Rate limiting
- HTTPS
- Environment variable protection

## 🐛 Troubleshooting

### AI Search Not Working
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Verify model is installed
ollama list

# Test API connection
curl http://localhost:8000/ai/test?prompt=hello
```

### Database Connection Issues
```bash
# Verify PostgreSQL is running
pg_isready

# Check DATABASE_URL in .env
echo $DATABASE_URL
```

### Frontend Not Connecting
- Ensure backend is running on port 8000
- Check CORS settings in `main.py`
- Verify `API_URL` in `App.js`