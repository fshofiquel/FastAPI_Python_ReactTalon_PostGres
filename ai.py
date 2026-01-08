import os
import json
import httpx
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import BaseModel
import re
import logging
from pathlib import Path

# ==============================================================================
# LOGGING SETUP
# ==============================================================================

logger = logging.getLogger(__name__)

# ==============================================================================
# ENVIRONMENT CONFIGURATION
# ==============================================================================

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

# ==============================================================================
# CACHING SETUP
# ==============================================================================

# In-memory cache (always available)
IN_MEMORY_CACHE = {}
CACHE_FILE = Path("query_cache.json")

# Try to use Redis if available (optional dependency)
USE_REDIS = False
redis_client = None

try:
    import redis
    
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB = int(os.getenv("REDIS_DB", 0))
    
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )
    
    # Test connection
    redis_client.ping()
    USE_REDIS = True
    logger.info("✅ Redis cache connected successfully")
    
except ImportError:
    logger.info("ℹ️  Redis not installed, using file-based cache")
except (redis.ConnectionError, redis.TimeoutError) as e:
    logger.warning(f"⚠️  Redis not available: {e}. Using file-based cache")
except Exception as e:
    logger.warning(f"⚠️  Redis setup failed: {e}. Using file-based cache")

# Load file-based cache on startup
def load_cache_from_file():
    """Load query cache from JSON file"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                logger.info(f"📂 Loaded {len(data)} cached queries from file")
                return data
    except Exception as e:
        logger.error(f"Failed to load cache file: {e}")
    return {}

# Initialize in-memory cache from file
IN_MEMORY_CACHE = load_cache_from_file()

def save_cache_to_file():
    """Save query cache to JSON file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            # Convert UserQueryFilters objects to dicts for JSON serialization
            serializable_cache = {}
            for key, value in IN_MEMORY_CACHE.items():
                if hasattr(value, 'dict'):
                    serializable_cache[key] = value.dict()
                else:
                    serializable_cache[key] = value
            
            json.dump(serializable_cache, f, indent=2)
            logger.info(f"💾 Saved {len(serializable_cache)} queries to cache file")
    except Exception as e:
        logger.error(f"Failed to save cache file: {e}")

# ==============================================================================
# DATABASE CONNECTION POOL
# ==============================================================================

# Global connection pool
_db_pool: Optional[asyncpg.Pool] = None

async def get_db_pool() -> asyncpg.Pool:
    """
    Get or create database connection pool (singleton pattern).
    
    Returns:
        asyncpg.Pool: Database connection pool
    """
    global _db_pool
    
    if _db_pool is None:
        try:
            _db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=5,                          # Minimum connections
                max_size=20,                         # Maximum connections
                max_queries=50000,                   # Max queries per connection
                max_inactive_connection_lifetime=300, # 5 minutes
                command_timeout=30,                  # 30 second query timeout
            )
            logger.info("✅ Database connection pool created")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
    
    return _db_pool

async def close_db_pool():
    """Close the database connection pool"""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed")

# ==============================================================================
# DATA MODELS
# ==============================================================================

class UserRecord(BaseModel):
    id: int
    full_name: str
    username: str
    gender: str

class UserQueryFilters(BaseModel):
    gender: Optional[str] = None
    name_substr: Optional[str] = None
    starts_with_mode: bool = False

class FilteredResult(BaseModel):
    results: List[UserRecord]
    ranked_ids: Optional[List[int]] = None

# ==============================================================================
# AI CHAT COMPLETION
# ==============================================================================

async def chat_completion(user_input: str, system_prompt: Optional[str] = None) -> str:
    """
    Send a request to the Ollama API for chat completion.
    
    Args:
        user_input: User's message
        system_prompt: Optional system prompt
        
    Returns:
        str: AI's response
        
    Raises:
        RuntimeError: If API configuration is missing or request fails
    """
    if not OLLAMA_BASE_URL or not OLLAMA_API_KEY:
        raise RuntimeError("OLLAMA_BASE_URL and OLLAMA_API_KEY must be set in .env")

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/v1/chat/completions"
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
        "temperature": 0.0,  # Deterministic responses for consistent caching
        "top_p": 0.95,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]

# ==============================================================================
# QUERY NORMALIZATION
# ==============================================================================

def normalize_query(query: str) -> str:
    """
    Normalize query for fuzzy cache matching.
    
    This helps similar queries map to the same cache key, improving cache hit rate.
    
    Args:
        query: Original query string
        
    Returns:
        str: Normalized query
    """
    q = query.lower().strip()

    # Remove extra spaces
    q = ' '.join(q.split())

    # Normalize common query starters
    starters = ['show me', 'find me', 'get me', 'list me', 'give me', 'show', 'find', 'get', 'list', 'search']
    for starter in starters:
        if q.startswith(starter + ' '):
            q = 'show ' + q[len(starter):].strip()
            break

    # Normalize common variations
    replacements = {
        'females': 'female',
        'males': 'male',
        'users': 'user',
        'people': 'user',
        'persons': 'user',
        'all the': 'all',
        'with the name': 'named',
        'with the': 'with',
        'in the': 'in',
        'whose name ': 'whose names ',
        'called': 'named',
    }

    for old, new in replacements.items():
        q = q.replace(old, new)

    # Remove filler words
    filler_words = ['please', 'could you', 'can you', 'would you', 'will you', 'the', 'a', 'an', 'my']
    words = q.split()
    words = [w for w in words if w not in filler_words]

    result = ' '.join(words)
    logger.debug(f"[NORMALIZE] '{query}' → '{result}'")
    return result

# ==============================================================================
# CACHE MANAGEMENT
# ==============================================================================

def get_cached_query(query: str) -> Optional[UserQueryFilters]:
    """
    Retrieve cached query result.
    
    Tries multiple cache layers:
    1. Redis (if available)
    2. In-memory cache
    3. Normalized query lookup
    
    Args:
        query: Search query
        
    Returns:
        UserQueryFilters if cached, None otherwise
    """
    # Try Redis first
    if USE_REDIS and redis_client:
        try:
            cache_key = f"query:{normalize_query(query)}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                logger.info(f"🎯 Redis cache hit for: {query}")
                filters_dict = json.loads(cached_data)
                filters = UserQueryFilters(**filters_dict)
                # Update in-memory cache for faster subsequent access
                IN_MEMORY_CACHE[query] = filters
                return filters
        except Exception as e:
            logger.error(f"Redis get error: {e}")
    
    # Try exact match in memory
    if query in IN_MEMORY_CACHE:
        logger.info(f"🎯 In-memory cache hit for: {query}")
        return IN_MEMORY_CACHE[query]
    
    # Try normalized query
    normalized = normalize_query(query)
    if normalized in IN_MEMORY_CACHE:
        logger.info(f"🎯 Fuzzy cache hit for: {query}")
        result = IN_MEMORY_CACHE[normalized]
        IN_MEMORY_CACHE[query] = result  # Cache original too
        return result
    
    logger.debug(f"❌ Cache miss for: {query}")
    return None

def cache_query(query: str, filters: UserQueryFilters) -> None:
    """
    Cache query result in all available cache layers.
    
    Args:
        query: Search query
        filters: Parsed filters to cache
    """
    # Cache in Redis
    if USE_REDIS and redis_client:
        try:
            cache_key = f"query:{normalize_query(query)}"
            redis_client.setex(
                cache_key,
                86400,  # 24 hours TTL
                json.dumps(filters.dict())
            )
            logger.debug(f"💾 Cached in Redis: {query}")
        except Exception as e:
            logger.error(f"Redis set error: {e}")
    
    # Always cache in memory
    IN_MEMORY_CACHE[query] = filters
    normalized = normalize_query(query)
    IN_MEMORY_CACHE[normalized] = filters
    
    logger.debug(f"💾 Cached in memory: {query}")
    
    # Periodically save to file (every 10th cache)
    if len(IN_MEMORY_CACHE) % 10 == 0:
        save_cache_to_file()

def get_cache_stats() -> dict:
    """Get cache statistics"""
    stats = {
        "in_memory_size": len(IN_MEMORY_CACHE),
        "redis_connected": USE_REDIS and redis_client is not None,
        "cache_file_exists": CACHE_FILE.exists()
    }
    
    if USE_REDIS and redis_client:
        try:
            info = redis_client.info('stats')
            stats["redis_hits"] = info.get('keyspace_hits', 0)
            stats["redis_misses"] = info.get('keyspace_misses', 0)
            stats["redis_keys"] = redis_client.dbsize()
        except Exception as e:
            logger.error(f"Error getting Redis stats: {e}")
    
    return stats

# ==============================================================================
# SIMPLE QUERY PARSING
# ==============================================================================

def simple_parse_query(user_query: str) -> Optional[UserQueryFilters]:
    """
    Parse query using simple keyword matching and regex.
    
    This is faster than AI parsing and handles most common queries.
    
    Args:
        user_query: User's search query
        
    Returns:
        UserQueryFilters if parsed successfully, None if query is too complex
    """
    query_lower = user_query.lower().strip()

    # Check for complex queries that need AI
    complex_words = [
        'whose', 'rhyme', 'longer', 'shorter', 'exactly', 'more', 'less',
        'odd', 'even', 'three', 'two', 'contains', 'ends', 'birthdate',
        'birthday', 'age', 'registered', 'profile', 'password'
    ]

    if any(word in query_lower for word in complex_words):
        return None

    gender = None
    if 'female' in query_lower or 'woman' in query_lower or 'women' in query_lower:
        gender = "Female"
    elif 'male' in query_lower and 'female' not in query_lower:
        gender = "Male"
    elif 'other' in query_lower:
        gender = "Other"

    name_substr = None
    starts_with_mode = False

    # Look for "named X" or "called X"
    if 'named' in query_lower or 'called' in query_lower:
        match = re.search(r'(?:named|called)\s+([A-Z][a-z]+)', user_query)
        if match:
            name_substr = match.group(1)

    # Look for "starts with X" or "starting with X"
    elif 'starts with' in query_lower or 'starting with' in query_lower:
        match = re.search(r'start(?:s|ing)?\s+with\s+([A-Z])', user_query, re.IGNORECASE)
        if match:
            name_substr = match.group(1).upper()
            starts_with_mode = True

    # Look for "with X" patterns
    elif 'with' in query_lower and gender:
        match = re.search(r'with\s+([A-Z][a-z]+)', user_query)
        if match:
            name_substr = match.group(1)

    if gender or name_substr:
        result = UserQueryFilters(gender=gender, name_substr=name_substr, starts_with_mode=starts_with_mode)
        logger.info(f"✅ Simple parse successful: {result.dict()}")
        return result

    return None

# ==============================================================================
# AI QUERY PARSING
# ==============================================================================

async def parse_query_ai(user_query: str) -> UserQueryFilters:
    """
    Parse user query into structured filters using 3-tier approach:
    1. Check cache (exact and fuzzy)
    2. Try simple pattern matching
    3. Fall back to AI parsing
    
    Args:
        user_query: Natural language search query
        
    Returns:
        UserQueryFilters: Parsed query filters
    """
    user_query = user_query.strip()
    query_lower = user_query.lower()

    logger.info(f"🔍 Parsing query: '{user_query}'")

    # ==============================================================================
    # TIER 1: CHECK CACHE
    # ==============================================================================
    
    cached_result = get_cached_query(user_query)
    if cached_result:
        return cached_result

    # ==============================================================================
    # TIER 2: PATTERN MATCHING
    # ==============================================================================
    
    # Exact pattern dictionary for instant responses
    simple_patterns = {
        "list all female": UserQueryFilters(gender="Female"),
        "show all female": UserQueryFilters(gender="Female"),
        "all female users": UserQueryFilters(gender="Female"),
        "female users": UserQueryFilters(gender="Female"),
        "show female": UserQueryFilters(gender="Female"),
        "all females": UserQueryFilters(gender="Female"),
        "list females": UserQueryFilters(gender="Female"),
        "list all male": UserQueryFilters(gender="Male"),
        "show all male": UserQueryFilters(gender="Male"),
        "all male users": UserQueryFilters(gender="Male"),
        "male users": UserQueryFilters(gender="Male"),
        "show male": UserQueryFilters(gender="Male"),
        "all males": UserQueryFilters(gender="Male"),
        "list males": UserQueryFilters(gender="Male"),
        "list all other": UserQueryFilters(gender="Other"),
        "show all other": UserQueryFilters(gender="Other"),
        "other users": UserQueryFilters(gender="Other"),
        "list all users": UserQueryFilters(),
        "show all users": UserQueryFilters(),
        "all users": UserQueryFilters(),
    }

    if query_lower in simple_patterns:
        result = simple_patterns[query_lower]
        logger.info(f"✅ Pattern match: {result.dict()}")
        cache_query(user_query, result)
        return result

    # Try simple keyword parsing
    simple_result = simple_parse_query(user_query)
    if simple_result is not None:
        cache_query(user_query, simple_result)
        return simple_result

    # ==============================================================================
    # TIER 3: AI PARSING
    # ==============================================================================
    
    logger.info(f"🤖 Using AI parser (no cache/pattern match found)")

    try:
        system_prompt = """You are a query parser that converts natural language to JSON filters.
Output ONLY valid JSON with no additional text, explanations, or markdown.

Rules:
- gender: Must be exactly "Male", "Female", "Other", or null
- name_substr: Extract any mentioned name or null
- Never include gender values in name_substr field
- If query is ambiguous, prefer null values

Examples:
Query: "list all female users"
Output: {"gender":"Female","name_substr":null}

Query: "users named John Smith"
Output: {"gender":null,"name_substr":"John Smith"}

Query: "find male users with Taylor in their name"
Output: {"gender":"Male","name_substr":"Taylor"}

Query: "show me people starting with J"
Output: {"gender":null,"name_substr":"J"}

Query: "everyone"
Output: {"gender":null,"name_substr":null}"""

        user_prompt = f"""Parse this query into JSON:

Query: "{user_query}"

Output JSON with exactly two keys:
- "gender": "Male" | "Female" | "Other" | null
- "name_substr": string | null

JSON:"""

        logger.info(f"📡 Calling AI model: {OLLAMA_MODEL}")
        parsed_json = await chat_completion(user_prompt, system_prompt)
        
        logger.debug(f"AI response: {parsed_json}")

        # Clean and extract JSON
        parsed_json = parsed_json.strip()
        
        # Remove markdown code blocks
        if "```" in parsed_json:
            match = re.search(r'```(?:json)?\s*({[^}]+})\s*```', parsed_json, re.DOTALL)
            if match:
                parsed_json = match.group(1)
        
        # Remove common prefixes
        for prefix in ["output:", "response:", "json:", "result:", "answer:"]:
            if parsed_json.lower().startswith(prefix):
                parsed_json = parsed_json[len(prefix):].strip()
        
        # Find JSON object
        json_match = re.search(r'\s*({\s*"gender"[^}]+})\s*', parsed_json, re.DOTALL)
        if json_match:
            parsed_json = json_match.group(1)
        
        # Parse JSON
        parsed_dict = json.loads(parsed_json)
        
        # Validate and clean fields
        if "gender" in parsed_dict:
            gender = parsed_dict["gender"]
            if isinstance(gender, str):
                gender = gender.strip().capitalize()
                if gender not in ["Male", "Female", "Other"]:
                    logger.warning(f"Invalid gender: {gender}, setting to null")
                    gender = None
            parsed_dict["gender"] = gender
        
        if "name_substr" in parsed_dict:
            name_val = parsed_dict["name_substr"]
            if isinstance(name_val, str):
                name_val = name_val.strip().strip("'\"[]")
                # Filter out gender values that ended up in name field
                if name_val.lower() in ["male", "female", "other", "user", "users", "all", "null", "none", ""]:
                    name_val = None
                parsed_dict["name_substr"] = name_val if name_val else None
        
        result = UserQueryFilters(**parsed_dict)
        
        logger.info(f"✅ AI parse successful: {result.dict()}")
        cache_query(user_query, result)
        
        return result

    except httpx.ReadTimeout as e:
        logger.error(f"AI request timed out: {e}")
        logger.warning("Falling back to empty filter")
        return UserQueryFilters()
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling AI: {e}")
        logger.warning("Falling back to empty filter")
        return UserQueryFilters()
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from AI: {e}")
        logger.error(f"Response was: {parsed_json}")
        logger.warning("Falling back to empty filter")
        return UserQueryFilters()
        
    except Exception as e:
        logger.error(f"Unexpected error in AI parsing: {type(e).__name__}: {e}")
        logger.warning("Falling back to empty filter")
        return UserQueryFilters()

# ==============================================================================
# DATABASE QUERIES
# ==============================================================================

async def query_users(filters: UserQueryFilters, limit: int = 20) -> List[UserRecord]:
    """
    Query users from database using connection pool.
    
    Args:
        filters: Query filters
        limit: Maximum number of results
        
    Returns:
        List of UserRecord objects
    """
    sql = "SELECT id, full_name, username, gender FROM users WHERE TRUE"
    params = []

    if filters.gender:
        params.append(filters.gender)
        sql += f" AND gender = ${len(params)}"

    if filters.name_substr:
        name_str = str(filters.name_substr)
        if filters.starts_with_mode:
            params.append(f"{name_str}%")
            sql += f" AND full_name ILIKE ${len(params)}"
        else:
            params.append(f"%{name_str}%")
            sql += f" AND full_name ILIKE ${len(params)}"

    sql += f" LIMIT {limit}"

    logger.debug(f"SQL: {sql}")
    logger.debug(f"Params: {params}")

    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            logger.info(f"✅ Found {len(rows)} users")
            return [UserRecord(**dict(r)) for r in rows]
    except asyncpg.QueryCanceledError:
        logger.error("Query canceled due to timeout")
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error querying users: {e}")
        raise

# ==============================================================================
# AI RANKING (Optional Feature)
# ==============================================================================

async def rank_users_ai(query: str, users: List[UserRecord]) -> List[int]:
    """
    Rank users by relevance using AI (optional, slower).
    
    Args:
        query: Original search query
        users: List of users to rank
        
    Returns:
        List of user IDs in order of relevance
    """
    if not users or len(users) <= 1:
        return [u.id for u in users]

    try:
        system_prompt = """You are a relevance ranker. Output ONLY a JSON array of integers."""

        user_data = [
            {"id": u.id, "name": u.full_name, "gender": u.gender, "username": u.username}
            for u in users
        ]

        user_prompt = f"""Rank these users by relevance to: "{query}"

Users:
{json.dumps(user_data, indent=2)}

Consider:
- Name similarity to query
- Gender match if mentioned
- Username relevance

Output ONLY a JSON array of user IDs, most relevant first.
Example: [3, 1, 5, 2, 4]

Your response:"""

        ranking_json = await chat_completion(user_prompt, system_prompt)
        ranking_json = ranking_json.strip()
        
        # Extract JSON array
        match = re.search(r'\[\s*(?:\d+\s*,\s*)*\d+\s*\]', ranking_json)
        if match:
            ranking_json = match.group(0)
        
        ranked = json.loads(ranking_json)
        if isinstance(ranked, list):
            return [int(x) for x in ranked if isinstance(x, (int, str)) and str(x).isdigit()]
        
        # Fallback to original order
        return [u.id for u in users]
        
    except Exception as e:
        logger.error(f"Ranking error: {e}")
        return [u.id for u in users]

# ==============================================================================
# MAIN FILTER FUNCTION
# ==============================================================================

async def filter_records_ai(
    user_query: str,
    batch_size: int = 20,
    enable_ranking: bool = False
) -> FilteredResult:
    """
    Main function to filter users based on natural language query.
    
    Args:
        user_query: Natural language search query
        batch_size: Maximum number of results
        enable_ranking: Whether to use AI ranking (slower)
        
    Returns:
        FilteredResult with users and optional ranking
    """
    # Parse query
    filters = await parse_query_ai(user_query)
    
    # Query database
    db_results = await query_users(filters, limit=batch_size)
    
    ranked_ids = None

    # Optional AI ranking
    if enable_ranking and len(db_results) > 1:
        try:
            logger.info(f"🎯 Ranking {len(db_results)} results...")
            ranked_ids = await rank_users_ai(user_query, db_results)
            logger.info(f"✅ Ranking complete")
        except Exception as e:
            logger.error(f"Ranking failed: {e}")
            logger.info("Continuing without ranking...")

    return FilteredResult(
        results=db_results,
        ranked_ids=ranked_ids
    )

# ==============================================================================
# CLEANUP
# ==============================================================================

def cleanup_caches():
    """Save caches and cleanup on shutdown"""
    logger.info("💾 Saving cache to file...")
    save_cache_to_file()
    logger.info("✅ Cache saved successfully")

# Save cache on module import (will run on first use)
import atexit
atexit.register(cleanup_caches)
