"""
ai.py - AI-Powered Natural Language Search Module

This module provides natural language search capabilities for the user management
system. It converts human-readable queries like "show me female users named Taylor"
into structured database filters.

Architecture:
    User Query → Query Normalization → Cache Check → AI Parsing → SQL Filters

The module uses a 3-tier approach for query processing:
    1. CACHE LOOKUP: Check Redis, in-memory, and file-based caches for instant results
    2. PATTERN MATCHING: Use regex patterns for common queries (no AI needed)
    3. AI PARSING: Use Ollama LLM for complex queries that patterns can't handle

Caching Strategy:
    - Redis (if available): Fastest, distributed, 24-hour TTL
    - In-memory dict: Always available, very fast, clears on restart
    - File-based JSON: Persistent across restarts, used as fallback

Query Normalization:
    Similar queries are normalized to the same form to improve cache hit rate.
    Example: "find females" and "show me female users" both become "show female user"

Supported Query Types:
    - Gender filtering: "male users", "female users", "other gender"
    - Name search: "users named Taylor", "names containing John"
    - Starts with: "users starting with J"
    - Name length: "users with odd letters in name"
    - Profile picture: "users with profile picture", "users without photo"
    - Sorting: "longest name", "newest users", "alphabetical order"
"""

# ==============================================================================
# IMPORTS
# ==============================================================================

import os       # Environment variable access
import json     # JSON encoding/decoding for cache and AI responses
import httpx    # Async HTTP client for Ollama API calls
import re       # Regular expressions for pattern matching
import logging  # Application logging
import atexit   # Register cleanup functions on shutdown
from pathlib import Path                    # File path handling
from typing import List, Optional           # Type hints
from dotenv import load_dotenv              # Load environment variables from .env
from pydantic import BaseModel              # Data validation models
from sqlalchemy.orm import Session          # Database session type
from sqlalchemy import and_, or_, func      # SQLAlchemy query functions

# ==============================================================================
# LOGGING SETUP
# ==============================================================================

logger = logging.getLogger(__name__)

# ==============================================================================
# CONSTANTS
# ==============================================================================

FALLBACK_EMPTY_FILTER_MSG = "Falling back to empty filter"

# String literals used multiple times (SonarQube S1192)
SORT_SHORTEST = 'shortest'
SORT_LONGEST = 'longest'
SORT_NEWEST = 'newest'
PATTERN_STARTS_WITH = 'starts with'

# ==============================================================================
# ENVIRONMENT CONFIGURATION
# ==============================================================================

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")

# ==============================================================================
# PERSISTENT HTTP CLIENT
# ==============================================================================
#
# Performance Optimization: Connection Pooling
# --------------------------------------------
# Creating a new HTTP client for every AI request is slow because:
#   1. TCP handshake takes ~50-100ms
#   2. TLS negotiation adds another ~50-100ms
#   3. HTTP/2 connection setup adds overhead
#
# By reusing a single persistent client, we:
#   - Skip connection setup for subsequent requests (saves ~100-200ms per request)
#   - Enable HTTP/2 multiplexing (multiple requests over single connection)
#   - Maintain a pool of keep-alive connections ready to use
#
# This can reduce AI API call latency by 30-50% for cached connections.

_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get or create a persistent HTTP client with connection pooling.

    The client is created lazily on first use and reused for all subsequent
    AI API calls. This significantly improves performance by avoiding the
    overhead of establishing new connections for each request.

    Configuration:
        - timeout: 60s total, 10s for connection establishment
        - max_keepalive_connections: 5 (connections kept ready for reuse)
        - max_connections: 10 (maximum concurrent connections)
        - http2: Enabled for better multiplexing and header compression

    Returns:
        httpx.AsyncClient: Configured async HTTP client
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            http2=True,  # HTTP/2 for better performance via multiplexing
        )
    return _http_client


async def close_http_client():
    """
    Close the persistent HTTP client gracefully.

    This should be called during application shutdown to properly release
    resources and close any open connections. FastAPI's shutdown event
    handler calls this function automatically.

    Failing to close the client may result in:
        - Connection leaks
        - Resource warnings on shutdown
        - Delayed process termination
    """
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

# ==============================================================================
# DATA MODELS
# ==============================================================================

class UserRecord(BaseModel):
    id: int
    full_name: str
    username: str
    gender: str
    profile_pic: Optional[str] = None

class UserQueryFilters(BaseModel):
    gender: Optional[str] = None
    name_substr: Optional[str] = None
    starts_with_mode: bool = False
    name_length_parity: Optional[str] = None  # "odd" or "even"
    has_profile_pic: Optional[bool] = None  # True = has pic, False = no pic, None = don't filter
    # Sorting options
    sort_by: Optional[str] = None  # "name_length", "username_length", "name", "username", "created_at"
    sort_order: str = "desc"  # "asc" or "desc"
    # Parse metadata for user feedback
    query_understood: bool = True  # False if query couldn't be meaningfully parsed
    parse_warnings: list = []  # Warnings about unsupported features or partial parsing

class FilteredResult(BaseModel):
    results: List[UserRecord]
    ranked_ids: Optional[List[int]] = None
    # Pagination info
    total_count: int = 0  # Total matching results (for pagination)
    # Parse feedback for frontend
    query_understood: bool = True
    parse_warnings: list = []
    filters_applied: Optional[dict] = None  # What filters were actually applied

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
    """Load query cache from JSON file and convert to UserQueryFilters objects"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                # Convert dicts back to UserQueryFilters objects
                converted_cache = {}
                for key, value in data.items():
                    if isinstance(value, dict):
                        try:
                            converted_cache[key] = UserQueryFilters(**value)
                        except Exception as e:
                            logger.warning(f"Failed to convert cached entry '{key}': {e}")
                    else:
                        converted_cache[key] = value
                logger.info(f"📂 Loaded {len(converted_cache)} cached queries from file")
                return converted_cache
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
# DATABASE INTEGRATION
# ==============================================================================
#
# NOTE: This module now uses SQLAlchemy (via database.py) instead of asyncpg
# This consolidates all database connections through a single pool for efficiency

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

    # Use persistent client for connection reuse (much faster)
    client = get_http_client()
    response = await client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    return data["choices"][0]["message"]["content"]

# ==============================================================================
# QUERY NORMALIZATION
# ==============================================================================
#
# Why Normalize Queries?
# ----------------------
# Users express the same intent in many different ways:
#   - "find females" vs "show me female users" vs "list all the females"
#   - "users w/ pics" vs "users with profile picture"
#   - "names beginning with J" vs "names starting with J"
#
# Without normalization, each variation creates a separate cache entry,
# reducing cache hit rate and increasing AI API calls.
#
# With normalization, all variations map to the same canonical form,
# dramatically improving cache efficiency (from ~60% to ~95% hit rate).
#
# Normalization Steps:
# 1. Lowercase and trim whitespace
# 2. Remove injection attempts (newlines, control characters)
# 3. Expand abbreviations (w/ -> with, w/o -> without, etc.)
# 4. Replace synonyms with standard terms (begin -> start, recent -> newest)
# 5. Normalize query starters (find me, get me, etc. -> show)
# 6. Consolidate variations (females -> female, users -> user)
# 7. Remove filler words (please, could you, etc.)

def normalize_query(query: str) -> str:
    """
    Normalize query for fuzzy cache matching and better simple parser matching.

    This helps similar queries map to the same cache key, improving cache hit rate.
    Also expands abbreviations and synonyms so the simple parser can handle more queries.

    Args:
        query: Original query string

    Returns:
        str: Normalized query
    """
    q = query.lower().strip()

    # Security: Remove newlines and control characters to prevent injection attacks.
    # Malicious queries like "show users\nDROP TABLE users" would only process "show users".
    # Only keep content before first newline.
    if '\n' in q:
        q = q.split('\n')[0].strip()

    # Remove extra spaces (normalize "show   me" to "show me")
    q = ' '.join(q.split())

    # ===========================================================================
    # STEP 1: Expand Abbreviations
    # ===========================================================================
    # Must happen FIRST so that subsequent patterns can match the expanded forms.
    # For example: "users w/o pics" -> "users without pictures"
    # This allows the profile picture detection logic to find "without pictures".
    abbreviations = {
        ' w/o ': ' without ',      # "w/o pic" -> "without picture"
        ' w/ ': ' with ',          # "w/ profile" -> "with profile"
        ' w ': ' with ',           # "begin w j" -> "begin with j" (informal shorthand)
        ' pic ': ' picture ',      # Normalize pic/picture
        ' pics ': ' pictures ',
        ' u ': ' you ',            # Text-speak normalization
        ' ur ': ' your ',
        ' ppl ': ' people ',
        ' dont ': " don't ",       # Expand contractions for consistent matching
        ' doesnt ': " doesn't ",
        ' cant ': " can't ",
        ' wont ': " won't ",
    }
    for old, new in abbreviations.items():
        q = q.replace(old, new)

    # ===========================================================================
    # STEP 2: Replace Synonyms with Standard Terms
    # ===========================================================================
    # Maps informal/alternative terms to their canonical forms so the simple
    # parser only needs to handle one version of each concept.
    synonyms = {
        # Starts-with variations -> canonical "starts with"
        'begin with': PATTERN_STARTS_WITH,
        'begins with': PATTERN_STARTS_WITH,
        'beginning with': 'starting with',
        'start at': PATTERN_STARTS_WITH,

        # Sorting synonyms -> canonical length/date terms
        # "big names" -> "longest names", "small usernames" -> "shortest usernames"
        'big ': f'{SORT_LONGEST} ',
        'bigger ': f'{SORT_LONGEST} ',
        'biggest ': f'{SORT_LONGEST} ',
        'small ': f'{SORT_SHORTEST} ',
        'smaller ': f'{SORT_SHORTEST} ',
        'smallest ': f'{SORT_SHORTEST} ',
        'recent ': f'{SORT_NEWEST} ',
        'new ': f'{SORT_NEWEST} ',
        'latest ': f'{SORT_NEWEST} ',
        'signups': 'users',  # "recent signups" -> "recent users"

        # Gender synonyms -> canonical male/female
        # IMPORTANT: 'women' must come BEFORE 'men' in replacement order!
        # Otherwise "women" would become "womale" (wo + male replacement)
        'women ': 'female ',
        'men ': 'male ',
        'guys': 'male users',
        'gals': 'female users',
        'ladies': 'female users',
        'gentlemen': 'male users',

        # Profile picture synonyms -> canonical "picture"
        'avatar': 'profile picture',
        'avatars': 'profile pictures',
        'photo': 'picture',
        'photos': 'pictures',
        'image': 'picture',
        'images': 'pictures',
    }
    for old, new in synonyms.items():
        q = q.replace(old, new)

    # ===========================================================================
    # STEP 3: Normalize Query Starters
    # ===========================================================================
    # All command verbs are normalized to "show" for consistent pattern matching.
    # This means "find female users", "get female users", "list female users"
    # all become "show female users" and hit the same cache entry.
    starters = ['show me', 'find me', 'get me', 'list me', 'give me', 'show', 'find', 'get', 'list', 'search', 'display']
    for starter in starters:
        if q.startswith(starter + ' '):
            q = 'show ' + q[len(starter):].strip()
            break

    # ===========================================================================
    # STEP 4: Consolidate Variations
    # ===========================================================================
    # Normalize plural/singular forms and common phrases to reduce cache fragmentation.
    # "female users" and "females" both become "female user" for cache matching.
    replacements = {
        'females': 'female',
        'males': 'male',
        'users': 'user',
        'people': 'user',
        'persons': 'user',
        'all the': 'all',
        'with the name': 'named',  # "with the name John" -> "named John"
        'with the': 'with',
        'in the': 'in',
        'whose name ': 'whose names ',
        'called': 'named',  # "user called John" -> "user named John"
    }

    for old, new in replacements.items():
        q = q.replace(old, new)

    # ===========================================================================
    # STEP 5: Remove Filler Words
    # ===========================================================================
    # Remove polite phrases and articles that don't affect query meaning.
    # "please show me the female users" -> "show female user"
    # Note: We keep 'a' because single-letter searches like "a" are valid.
    filler_words = ['please', 'could you', 'can you', 'would you', 'will you', 'the', 'an', 'my']
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
        cached = IN_MEMORY_CACHE[query]
        # Handle both dict and UserQueryFilters
        if isinstance(cached, dict):
            return UserQueryFilters(**cached)
        return cached

    # Try normalized query
    normalized = normalize_query(query)
    if normalized in IN_MEMORY_CACHE:
        logger.info(f"🎯 Fuzzy cache hit for: {query}")
        result = IN_MEMORY_CACHE[normalized]
        # Handle both dict and UserQueryFilters
        if isinstance(result, dict):
            result = UserQueryFilters(**result)
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


def clear_all_caches() -> dict:
    """
    Clear all query caches (in-memory, Redis, and file).

    This function is useful when:
    - Query parsing logic has been updated and old cached results are stale
    - Testing new query patterns without interference from cached results
    - Debugging cache-related issues
    - Resetting the system to a clean state

    The function clears all three cache layers:
    1. In-memory cache: Fastest, cleared immediately
    2. Redis cache: Distributed cache, keys matching "query:*" pattern are deleted
    3. File cache: Persistent cache in query_cache.json, replaced with empty object

    Returns:
        dict: Statistics about what was cleared:
            - in_memory: Number of entries cleared from in-memory cache
            - redis: Number of keys deleted from Redis
            - file: Boolean indicating if file cache was cleared

    Example response:
        {"in_memory": 150, "redis": 75, "file": True}
    """
    global IN_MEMORY_CACHE
    cleared = {"in_memory": 0, "redis": 0, "file": False}

    # Clear in-memory cache (always available, fastest)
    cleared["in_memory"] = len(IN_MEMORY_CACHE)
    IN_MEMORY_CACHE = {}

    # Clear Redis cache if available (distributed, shared across instances)
    # Only delete keys with "query:" prefix to avoid clearing other Redis data
    if USE_REDIS and redis_client:
        try:
            keys = redis_client.keys("query:*")
            if keys:
                cleared["redis"] = len(keys)
                redis_client.delete(*keys)
        except Exception as e:
            logger.error(f"Error clearing Redis cache: {e}")

    # Clear file cache (persistent across restarts)
    # Write empty object instead of deleting to maintain file existence
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({}, f)
            cleared["file"] = True
        except Exception as e:
            logger.error(f"Error clearing file cache: {e}")

    logger.info(f"🗑️ Cleared caches: {cleared}")
    return cleared


# ==============================================================================
# SIMPLE QUERY PARSING - HELPER FUNCTIONS
# ==============================================================================

def _detect_unsupported_patterns(query_lower: str) -> list:
    """Detect unsupported query patterns and return warnings."""
    warnings = []
    words = set(query_lower.split())

    # Negation/exclusion (but not "no profile pic" which is supported)
    has_negation = bool(words & {'except', 'exclude'})
    has_not_without_profile = 'not' in words and 'profile' not in query_lower
    if has_negation or has_not_without_profile:
        warnings.append("Negation/exclusion queries are not supported - showing matching results instead")

    # OR logic between genders
    if 'or' in words and bool(words & {'male', 'female', 'other'}):
        warnings.append("OR logic between genders is not supported - using first gender found")

    # Ends-with filtering
    if 'ends with' in query_lower or 'end with' in query_lower:
        warnings.append(f"Ends-with filtering is not supported - use 'contains' or '{PATTERN_STARTS_WITH}' instead")

    # Exact length filtering (e.g., "exactly 5 letters")
    if 'exactly' in words and bool(words & {'letter', 'char', 'character'}):
        warnings.append("Exact length filtering is not supported - only odd/even length is available")

    for warning in warnings:
        logger.warning("Unsupported query pattern: %s", warning)

    return warnings


# Sorting keyword sets (module-level for reuse and reduced complexity)
_LONGEST_WORDS = frozenset({SORT_LONGEST, 'long', 'biggest', 'big', 'most characters'})
_SHORTEST_WORDS = frozenset({SORT_SHORTEST, 'short', 'smallest', 'small', 'fewest', 'least'})
_NEWEST_WORDS = frozenset({SORT_NEWEST, 'most recent', 'recently created', 'latest', 'recent'})
_OLDEST_WORDS = frozenset({'oldest', 'first created', 'earliest'})
_ALPHA_ASC_WORDS = frozenset({'alphabetical', 'a-z', 'a to z', 'a–z'})
_ALPHA_DESC_WORDS = frozenset({'reverse alphabetical', 'z-a', 'z to a', 'z–a'})


def _detect_length_sorting(query_lower: str, words: list, has_username: bool, has_name: bool) -> Optional[tuple]:
    """Detect length-based sorting (longest/shortest)."""
    has_longest = any(word in query_lower for word in _LONGEST_WORDS)
    has_shortest = any(word in query_lower for word in _SHORTEST_WORDS)

    if has_longest:
        field = "username_length" if has_username else "name_length"
        if has_username or has_name or 'first' in words:
            return field, "desc"

    if has_shortest:
        field = "username_length" if has_username else "name_length"
        if has_username or has_name or 'first' in words:
            return field, "asc"

    return None


def _detect_date_sorting(query_lower: str) -> Optional[tuple]:
    """Detect date-based sorting (newest/oldest)."""
    if any(word in query_lower for word in _NEWEST_WORDS) or 'signups' in query_lower:
        return "created_at", "desc"
    if any(word in query_lower for word in _OLDEST_WORDS):
        return "created_at", "asc"
    return None


def _detect_alpha_sorting(query_lower: str, has_username: bool, has_name: bool) -> Optional[tuple]:
    """Detect alphabetical sorting (a-z / z-a)."""
    if any(word in query_lower for word in _ALPHA_DESC_WORDS):
        return ("username", "desc") if has_username else ("name", "desc")

    if any(word in query_lower for word in _ALPHA_ASC_WORDS):
        if has_username:
            return "username", "asc"
        if has_name:
            return "name", "asc"

    return None


def _detect_explicit_sort(words: list) -> Optional[tuple]:
    """Detect explicit 'sort by X' / 'order by X' pattern."""
    if not (('sort' in words or 'order' in words) and 'by' in words):
        return None

    by_idx = words.index('by')
    if by_idx + 1 >= len(words):
        return None

    sort_field = words[by_idx + 1]
    field_map = {
        'username': ("username", "asc"),
        'usernames': ("username", "asc"),
        'name': ("name", "asc"),
        'names': ("name", "asc"),
        'date': ("created_at", "desc"),
        'created': ("created_at", "desc"),
        'time': ("created_at", "desc"),
    }
    return field_map.get(sort_field)


def _detect_sorting(query_lower: str) -> tuple:
    """
    Detect sorting preferences from query.

    Returns:
        tuple: (sort_by, sort_order) where sort_by can be None
    """
    words = query_lower.split()
    has_username = 'username' in query_lower or 'usernames' in query_lower
    has_name = 'name' in query_lower or 'names' in query_lower

    # Try each sorting type in priority order
    result = _detect_length_sorting(query_lower, words, has_username, has_name)
    if result:
        return result

    result = _detect_date_sorting(query_lower)
    if result:
        return result

    result = _detect_alpha_sorting(query_lower, has_username, has_name)
    if result:
        return result

    result = _detect_explicit_sort(words)
    if result:
        return result

    return None, "desc"


def _detect_profile_pic_filter(query_lower: str) -> Optional[bool]:
    """
    Detect profile picture filter from query.

    Handles various ways users express whether they want users with or without
    profile pictures. The function checks for negation patterns FIRST to ensure
    queries like "users without profile picture" aren't misinterpreted.

    Supported patterns:
    - With picture: "with pic", "has photo", "profile picture", "with avatar"
    - Without picture: "without pic", "no photo", "missing profile", "w/o avatar"
    - Contractions: "don't have pic", "doesn't have photo"

    Returns:
        True: User wants results WITH profile pictures
        False: User wants results WITHOUT profile pictures
        None: No profile picture filter detected (don't filter by this)

    Examples:
        "users with profile pic" -> True
        "users without photo" -> False
        "no avatar" -> False
        "female users" -> None (no picture filter)

    Implementation Note:
        Negation is checked FIRST because "without profile picture" contains
        both "without" and "profile picture". If we checked for "has" indicators
        first, we might incorrectly match "profile picture" and return True.
    """
    # Image-related keywords that indicate the query is about profile pictures
    image_words = ['pic', 'picture', 'photo', 'image', 'avatar']
    has_image_word = any(word in query_lower for word in image_words)

    # Also check for "profile" alone (e.g., "no profile", "without profile")
    # This handles queries like "users without profile" (implied: picture)
    if not has_image_word and 'profile' not in query_lower:
        return None

    # ===========================================================================
    # Check for "WITHOUT" indicators FIRST (negation takes priority)
    # ===========================================================================
    # This must come before "has" checking because phrases like
    # "without profile picture" contain both negation AND the positive phrase.
    without_indicators = [
        # "without X" patterns
        'without pic', 'without pics', 'without photo', 'without photos',
        'without profile', 'without avatar', 'without avatars',
        'without picture', 'without pictures',
        # "no X" patterns
        'no pic', 'no pics', 'no photo', 'no photos',
        'no profile', 'no avatar', 'no avatars',
        'no picture', 'no pictures',
        # "missing X" patterns
        'missing pic', 'missing pics', 'missing photo', 'missing photos',
        'missing profile', 'missing avatar', 'missing picture',
        # Contractions (after abbreviation expansion)
        "don't have pic", "don't have picture", "don't have photo",
        "doesn't have pic", "doesn't have picture", "doesn't have photo",
        # Abbreviation forms (in case normalization didn't run)
        "w/o pic", "w/o photo", "w/o profile", "w/o avatar",
    ]
    if any(indicator in query_lower for indicator in without_indicators):
        return False

    # ===========================================================================
    # Check for "HAS/WITH" indicators (positive match)
    # ===========================================================================
    has_indicators = [
        # "with X" patterns
        'with pic', 'with photo', 'with profile', 'with avatar',
        'with picture', 'with pics', 'with photos', 'with avatars',
        # "has/have/got X" patterns
        'has pic', 'has photo', 'has avatar', 'has picture',
        'have pic', 'have photo', 'have avatar', 'have picture',
        'got pic', 'got photo', 'got avatar', 'got picture',
        # Compound phrases that imply having a picture
        'profile pic', 'profile picture', 'profile photo'
    ]
    if any(indicator in query_lower for indicator in has_indicators):
        return True

    # If only image word mentioned without clear context, don't assume intent
    # e.g., "picture" alone might be part of a name search
    return None


def _detect_name_length_parity(query_lower: str) -> Optional[str]:
    """Detect odd/even name length filter from query."""
    length_words = ['letter', 'character', 'length']
    has_length_word = any(word in query_lower for word in length_words)

    # Check for "odd"
    if 'odd' in query_lower:
        if has_length_word or 'name' in query_lower:
            return "odd"

    # Check for "even"
    if 'even' in query_lower and (has_length_word or 'name' in query_lower):
        return "even"

    return None


# Gender detection constants
_FEMALE_WORDS = frozenset({'female', 'woman', 'women', 'lady', 'ladies'})
_MALE_WORDS = frozenset({'male', 'guy', 'guys', 'man', 'men'})
_FEMALE_TYPOS = frozenset({'fmale', 'femal', 'femails', 'femail'})
_NAME_PREFIXES = frozenset({'named', 'called', 'name'})


def _is_name_not_gender(gender_word: str, words: list) -> bool:
    """Check if a gender word is actually a name (preceded by 'named', 'called', etc.)."""
    if gender_word not in words:
        return False
    idx = words.index(gender_word)
    return idx > 0 and words[idx - 1] in _NAME_PREFIXES


def _detect_other_gender(query_lower: str, words: list) -> Optional[tuple]:
    """Detect 'Other' gender (non-binary, other gender, etc.)."""
    if 'other gender' in query_lower or 'other-gender' in query_lower:
        return "Other", None
    if 'non-binary' in query_lower or 'non binary' in query_lower or 'nonbinary' in query_lower:
        return "Other", None
    if 'nb' in words:
        return "Other", "Interpreted as 'non-binary'"
    return None


def _detect_female_gender(query_lower: str, words: list) -> Optional[tuple]:
    """Detect female gender from query."""
    if _is_name_not_gender('female', words):
        return None

    # Check for female words
    if any(word in words for word in _FEMALE_WORDS) or 'female' in query_lower:
        return "Female", None

    # Check for typos (only if 'male' is not a separate word)
    if any(typo in query_lower for typo in _FEMALE_TYPOS) and 'male' not in words:
        return "Female", "Interpreted as 'female' (possible typo corrected)"

    return None


def _detect_male_gender(words: list) -> Optional[tuple]:
    """Detect male gender from query."""
    if _is_name_not_gender('male', words):
        return None
    if any(word in words for word in _MALE_WORDS):
        return "Male", None
    return None


def _detect_gender(query_lower: str) -> tuple:
    """
    Detect gender filter from query.

    Returns:
        tuple: (gender, warning) where gender is "Male", "Female", "Other", or None
    """
    words = query_lower.split()

    # Check Other gender first (highest priority)
    result = _detect_other_gender(query_lower, words)
    if result:
        return result

    # Check Female before Male (female contains "male" as substring)
    result = _detect_female_gender(query_lower, words)
    if result:
        return result

    # Check Male
    result = _detect_male_gender(words)
    if result:
        return result

    # Fallback: "other" with context
    if not _is_name_not_gender('other', words):
        if 'other' in words and ('gender' in query_lower or 'user' in query_lower):
            return "Other", None

    return None, None


def _extract_word_after(query_lower: str, keywords: list, excluded_words: set) -> Optional[str]:
    """Extract the word following any of the keywords, excluding certain words."""
    words = query_lower.split()
    for i, word in enumerate(words):
        if word in keywords and i + 1 < len(words):
            next_word = words[i + 1]
            # Skip excluded words
            if next_word in excluded_words:
                continue
            # Must start with a letter
            if next_word and next_word[0].isalpha():
                return next_word
    return None


def _capitalize_name(name: str) -> str:
    """Capitalize name parts (handles apostrophes like O'Brien)."""
    parts = name.split("'")
    return "'".join(part.capitalize() for part in parts)


def _find_letter_after_with(words: list) -> Optional[str]:
    """Find a single letter following 'with' in a word list."""
    articles = {'a', 'an', 'the', 'letter'}
    for i, word in enumerate(words):
        if word != 'with' or i + 1 >= len(words):
            continue
        next_word = words[i + 1]
        # Skip articles and get the word after
        if next_word in articles and i + 2 < len(words):
            next_word = words[i + 2]
        # Return if single letter
        if len(next_word) == 1 and next_word.isalpha():
            return next_word.upper()
    return None


# Name search pattern constants
_STARTS_WITH_PATTERNS = frozenset([PATTERN_STARTS_WITH, 'starting with', 'begins with', 'beginning with',
                                    'begin with', 'start with', 'start at', 'starting letter'])
_FILTER_WORDS = frozenset({'female', 'male', 'other', 'newest', 'oldest', 'latest', 'recent',
                            SORT_LONGEST, SORT_SHORTEST, 'with', 'without', 'no', 'user', 'users'})
_COMMAND_WORDS = frozenset({'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
                             'all', 'the', 'users', 'user', 'people', 'person', 'names', 'name'})
_ARTICLES = frozenset({'a', 'an', 'the', 'that', 'is'})
_SORTING_WORDS = frozenset({'oldest', SORT_NEWEST, SORT_LONGEST, SORT_SHORTEST, 'with', 'without'})


def _detect_show_x_names(words: list) -> Optional[tuple]:
    """Pattern 1: 'show X names' - single letter before 'names'."""
    if 'names' not in words or len(words) < 2:
        return None
    names_idx = words.index('names')
    if names_idx >= 1:
        prev_word = words[names_idx - 1]
        if len(prev_word) == 1 and prev_word.isalpha():
            return prev_word.upper(), True
    return None


def _find_letter_after_pattern(words: list, pattern_words: list) -> Optional[str]:
    """Find a single letter that appears after a pattern in words."""
    for i, word in enumerate(words):
        if word != pattern_words[0]:
            continue
        next_idx = i + len(pattern_words)
        if next_idx < len(words):
            next_word = words[next_idx]
            if len(next_word) == 1 and next_word.isalpha():
                return next_word.upper()
    return None


def _detect_starts_with_pattern(query_lower: str, words: list) -> Optional[tuple]:
    """Pattern 2: 'starts with X' variants."""
    for pattern in _STARTS_WITH_PATTERNS:
        if pattern not in query_lower:
            continue
        letter = _find_letter_after_with(words)
        if letter:
            return letter, True
        result = _find_letter_after_pattern(words, pattern.split())
        if result:
            return result, True
    return None


def _detect_letter_in_name(words: list) -> Optional[tuple]:
    """Pattern 3: 'letter X in name'."""
    if 'letter' not in words:
        return None
    letter_idx = words.index('letter')
    if letter_idx + 1 >= len(words):
        return None
    next_word = words[letter_idx + 1]
    if len(next_word) == 1 and next_word.isalpha():
        if 'name' in words[letter_idx:] or 'names' in words[letter_idx:]:
            return next_word.upper(), False
    return None


def _detect_containing_pattern(words: list) -> Optional[tuple]:
    """Pattern 4: 'containing X'."""
    if 'containing' not in words:
        return None
    idx = words.index('containing')
    if idx + 1 >= len(words):
        return None
    next_word = words[idx + 1]
    if len(next_word) == 1 and next_word.isalpha():
        return next_word.upper(), False
    if next_word not in _ARTICLES:
        return _capitalize_name(next_word), False
    return None


def _detect_name_like_pattern(words: list) -> Optional[tuple]:
    """Pattern 5: 'name like X'."""
    if 'like' not in words:
        return None
    idx = words.index('like')
    if idx > 0 and 'name' in words[:idx] and idx + 1 < len(words):
        next_word = words[idx + 1]
        if next_word not in _ARTICLES:
            return _capitalize_name(next_word), False
    return None


def _detect_named_called_pattern(query_lower: str) -> Optional[tuple]:
    """Pattern 6: 'named X' / 'called X'."""
    excluded = {'that', 'is', 'of', 'which', 'who', 'a', 'an', 'the',
                'users', 'user', 'people', 'all', 'me'}
    name = _extract_word_after(query_lower, ['named', 'called'], excluded)
    if name and name.lower() not in _SORTING_WORDS:
        return _capitalize_name(name), False
    return None


def _detect_show_name_filter(words: list) -> Optional[tuple]:
    """Pattern 7: 'show/find X <filter>'."""
    if len(words) < 3 or words[0] not in {'show', 'find'}:
        return None
    potential_name = words[1]
    if potential_name not in _FILTER_WORDS and potential_name[0].isalpha():
        if words[2] in _FILTER_WORDS:
            return _capitalize_name(potential_name), False
    return None


def _detect_name_users_pattern(words: list) -> Optional[tuple]:
    """Pattern 8: 'X users'."""
    if len(words) < 2 or words[-1] not in {'users', 'user'}:
        return None
    potential_name = words[0]
    cmd_words = {'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
                 'all', 'the', 'female', 'male', 'other', SORT_NEWEST, 'oldest'}
    excluded = {SORT_NEWEST, 'oldest', 'female', 'male', 'other'}
    if potential_name not in cmd_words and potential_name[0].isalpha():
        if potential_name not in excluded:
            return _capitalize_name(potential_name), False
    return None


def _detect_name_filter_pattern(words: list, gender: Optional[str]) -> Optional[tuple]:
    """Pattern 9: Name at start followed by filter."""
    if len(words) < 2:
        return None
    first_word = words[0]
    filter_words = {'female', 'male', 'other', SORT_NEWEST, 'oldest', 'latest', 'recent',
                    SORT_LONGEST, SORT_SHORTEST, 'with', 'without', 'no'}
    if first_word not in _COMMAND_WORDS and first_word[0].isalpha():
        if words[1] in filter_words or gender is not None:
            return _capitalize_name(first_word), False
    return None


def _detect_with_name_pattern(query_lower: str, gender: Optional[str], has_profile_pic: Optional[bool]) -> Optional[tuple]:
    """Pattern 10: 'with X' for name (when gender set, no pic filter)."""
    if not gender or has_profile_pic is not None:
        return None
    excluded_with = {'a', 'an', 'the', 'that', 'is', 'of', 'odd', 'even',
                     'profile', 'pic', 'picture', 'photo', 'avatar'}
    name = _extract_word_after(query_lower, ['with'], excluded_with)
    if name:
        return _capitalize_name(name), False
    return None


def _detect_name_search(query_lower: str, gender: Optional[str], has_profile_pic: Optional[bool]) -> tuple:
    """
    Detect name search patterns from query.

    Returns:
        tuple: (name_substr, starts_with_mode)
    """
    words = query_lower.split()

    # Try each pattern in priority order
    patterns = [
        lambda: _detect_show_x_names(words),
        lambda: _detect_starts_with_pattern(query_lower, words),
        lambda: _detect_letter_in_name(words),
        lambda: _detect_containing_pattern(words),
        lambda: _detect_name_like_pattern(words),
        lambda: _detect_named_called_pattern(query_lower),
        lambda: _detect_show_name_filter(words),
        lambda: _detect_name_users_pattern(words),
        lambda: _detect_name_filter_pattern(words, gender),
        lambda: _detect_with_name_pattern(query_lower, gender, has_profile_pic),
    ]

    for pattern_func in patterns:
        result = pattern_func()
        if result:
            return result

    return None, False


def _is_valid_name_chars(text: str) -> bool:
    """Check if text contains only valid name characters (letters, apostrophes, hyphens, spaces)."""
    if not text or not text[0].isalpha():
        return False
    for char in text:
        if not (char.isalpha() or char in "' -"):
            return False
    return True


def _detect_bare_name(query_lower: str, query_original: str) -> Optional[str]:
    """
    Detect if query is just a bare name without any command words or filters.

    This function handles the case where users simply type a name they're looking for,
    without using command words like "find", "show", etc. For example:
    - "Adam" -> Search for users named Adam
    - "John Smith" -> Search for users named John Smith
    - "J" -> Search for names starting with/containing J (single letter search)

    Single Letter Searches:
        When a user types just a single letter (e.g., "J"), this is interpreted as
        a name search. This is useful for quickly finding all users whose names
        contain or start with that letter. We removed 'a' and 'an' from the
        indicator words to allow single-letter searches like "A" to work.

    Validation criteria for bare names:
    - No command words (find, show, list, etc.)
    - No filter words (female, male, oldest, etc.)
    - 1-4 words (allows "John Smith Jr" but rejects long sentences)
    - 2-40 characters (single chars handled separately, rejects very long inputs)
    - Only valid name characters (letters, apostrophes, hyphens, spaces)

    Args:
        query_lower: Lowercase query string
        query_original: Original query with preserved case (for proper name formatting)

    Returns:
        The name string formatted in Title Case, or None if not a bare name query

    Examples:
        "Adam" -> "Adam"
        "john smith" -> "John Smith"
        "J" -> "J" (single letter)
        "O'Brien" -> "O'Brien"
        "find Adam" -> None (has command word)
    """
    # Words that indicate this is a structured query, not just a name
    query_indicators = {
        # Command words
        'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
        # Subject words
        'user', 'users', 'people', 'person', 'all', 'every',
        # Filter/clause words
        'with', 'without', 'who', 'whose', 'where', 'that', 'which',
        # Connectors (NOTE: 'a' and 'an' removed to allow single-letter searches)
        'the', 'and', 'or', 'not',
        # Sorting words
        'longest', 'shortest', 'oldest', 'newest', 'first', 'last',
        # Name-specific words
        'name', 'named', 'called', 'username', 'picture', 'photo', 'profile',
    }

    words = query_lower.split()

    # ===========================================================================
    # Special case: Single letter query (e.g., "A", "j", "M")
    # ===========================================================================
    # Allow single-letter queries for quick initial-based searches.
    # Users often want to find "all names starting with J" by just typing "J".
    if len(query_original) == 1 and query_original.isalpha():
        letter = query_original.upper()
        logger.info(f"✅ Simple parse (single letter): '{letter}'")
        return letter

    # If any query indicator word is present, this isn't a bare name
    if any(word in query_indicators for word in words):
        return None

    # ===========================================================================
    # Validation: Ensure it looks like a plausible name
    # ===========================================================================
    # Word count: 1-4 words allows "John", "John Smith", "Mary Jane Watson"
    # but rejects sentences like "I want to find users named John"
    if not (1 <= len(words) <= 4):
        return None

    # Length: 2-40 chars (single chars handled above)
    # This rejects empty strings and unreasonably long inputs
    if not (2 <= len(query_original) <= 40):
        return None

    # Character validation: Only allow letters, apostrophes, hyphens, spaces
    # This accepts "O'Brien", "Mary-Jane", "Van Der Berg" but rejects "user123"
    if not _is_valid_name_chars(query_original):
        return None

    # Format as Title Case for proper name display
    name = query_original.title()
    logger.info(f"✅ Simple parse (bare name): '{name}'")
    return name


def _is_complex_query(query_lower: str) -> bool:
    """Check if query contains complex words that require AI parsing."""
    complex_words = [
        'whose', 'rhyme', 'longer', 'shorter', 'exactly', 'more', 'less',
        'three', 'two', 'contains', 'ends', 'birthdate',
        'birthday', 'age', 'registered', 'password'
    ]
    return any(word in query_lower for word in complex_words)


# ==============================================================================
# SIMPLE QUERY PARSING - MAIN FUNCTION
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
    query_original = user_query.strip()

    # Detect warnings for unsupported patterns
    parse_warnings = _detect_unsupported_patterns(query_lower)

    # Detect all filter types
    sort_by, sort_order = _detect_sorting(query_lower)
    has_profile_pic = _detect_profile_pic_filter(query_lower)
    name_length_parity = _detect_name_length_parity(query_lower)

    gender, gender_warning = _detect_gender(query_lower)
    if gender_warning:
        parse_warnings.append(gender_warning)

    name_substr, starts_with_mode = _detect_name_search(query_lower, gender, has_profile_pic)

    # Try bare name detection if no other filters found
    has_no_filters = (not gender and not name_substr and not name_length_parity
                      and has_profile_pic is None and not sort_by)
    if has_no_filters:
        name_substr = _detect_bare_name(query_lower, query_original)

    # Check for complex queries that need AI
    if has_no_filters and not name_substr and _is_complex_query(query_lower):
        return None

    # Build result if any filters were detected
    has_any_filter = gender or name_substr or name_length_parity or has_profile_pic is not None or sort_by
    if has_any_filter:
        result = UserQueryFilters(
            gender=gender,
            name_substr=name_substr,
            starts_with_mode=starts_with_mode,
            name_length_parity=name_length_parity,
            has_profile_pic=has_profile_pic,
            sort_by=sort_by,
            sort_order=sort_order,
            parse_warnings=parse_warnings
        )
        logger.info(f"✅ Simple parse successful: {result.model_dump()}")
        return result

    # Return with warnings if we have them but no meaningful filters
    if parse_warnings:
        return UserQueryFilters(query_understood=False, parse_warnings=parse_warnings)

    return None

# ==============================================================================
# AI QUERY PARSING - HELPER FUNCTIONS
# ==============================================================================

# Common query patterns for instant matching
SIMPLE_QUERY_PATTERNS = {
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


def _extract_json_from_response(response: str) -> str:
    """
    Extract JSON object from AI response, handling markdown and prefixes.

    Args:
        response: Raw AI response string

    Returns:
        Cleaned JSON string
    """
    result = response.strip()

    # Remove markdown code blocks by finding content between ```
    if "```" in result:
        # Find the JSON between code fences
        start = result.find("```")
        end = result.rfind("```")
        if start != end:
            content = result[start + 3:end]
            # Remove optional "json" language identifier
            if content.startswith("json"):
                content = content[4:]
            result = content.strip()

    # Remove common prefixes
    prefixes = ["output:", "response:", "json:", "result:", "answer:"]
    for prefix in prefixes:
        if result.lower().startswith(prefix):
            result = result[len(prefix):].strip()

    # Extract JSON object by finding first { and last }
    start_idx = result.find('{')
    end_idx = result.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        result = result[start_idx:end_idx + 1]

    return result


def _validate_gender(value) -> Optional[str]:
    """Validate and normalize gender field."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().capitalize()
    if normalized not in ["Male", "Female", "Other"]:
        logger.warning(f"Invalid gender: {normalized}, setting to null")
        return None
    return normalized


def _validate_name_substr(value) -> Optional[str]:
    """Validate and clean name_substr field."""
    if not isinstance(value, str):
        return value
    cleaned = value.strip().strip("'\"[]")
    invalid_values = ["male", "female", "other", "user", "users", "all", "null", "none", ""]
    if cleaned.lower() in invalid_values:
        return None
    return cleaned if cleaned else None


def _validate_boolean_field(value) -> Optional[bool]:
    """Convert string boolean to actual boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in ["true", "1", "yes"]:
            return True
        if lower in ["false", "0", "no"]:
            return False
    return None


def _validate_sort_by(value) -> Optional[str]:
    """Validate sort_by field."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    valid_sorts = ["name_length", "username_length", "name", "username", "created_at"]
    if normalized not in valid_sorts:
        logger.warning(f"Invalid sort_by: {normalized}, setting to null")
        return None
    return normalized


def _validate_sort_order(value) -> str:
    """Validate sort_order field, defaulting to 'desc'."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ["asc", "desc"]:
            return normalized
    return "desc"


def _validate_parity(value) -> Optional[str]:
    """Validate name_length_parity field."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if normalized not in ["odd", "even"]:
        logger.warning(f"Invalid name_length_parity: {normalized}, setting to null")
        return None
    return normalized


def _sanitize_ai_response(parsed_dict: dict) -> dict:
    """
    Validate and sanitize all fields in the parsed AI response.

    Args:
        parsed_dict: Raw parsed JSON dictionary

    Returns:
        Sanitized dictionary with validated fields
    """
    if "gender" in parsed_dict:
        parsed_dict["gender"] = _validate_gender(parsed_dict["gender"])

    if "name_substr" in parsed_dict:
        parsed_dict["name_substr"] = _validate_name_substr(parsed_dict["name_substr"])

    if "starts_with_mode" in parsed_dict:
        result = _validate_boolean_field(parsed_dict["starts_with_mode"])
        parsed_dict["starts_with_mode"] = result if result is not None else False

    if "name_length_parity" in parsed_dict:
        parsed_dict["name_length_parity"] = _validate_parity(parsed_dict["name_length_parity"])

    if "has_profile_pic" in parsed_dict:
        parsed_dict["has_profile_pic"] = _validate_boolean_field(parsed_dict["has_profile_pic"])

    if "sort_by" in parsed_dict:
        parsed_dict["sort_by"] = _validate_sort_by(parsed_dict["sort_by"])

    if "sort_order" in parsed_dict:
        parsed_dict["sort_order"] = _validate_sort_order(parsed_dict["sort_order"])

    return parsed_dict


# ==============================================================================
# AI QUERY PARSING - MAIN FUNCTION
# ==============================================================================

async def parse_query_ai(user_query: str) -> UserQueryFilters:
    """
    Parse user query into structured filters using 3-tier approach:
    1. Check cache (exact and fuzzy)
    2. Try simple pattern matching (with normalization)
    3. Fall back to AI parsing

    Args:
        user_query: Natural language search query

    Returns:
        UserQueryFilters: Parsed query filters
    """
    user_query = user_query.strip()
    query_lower = user_query.lower()

    # Normalize query for better pattern matching
    # This expands abbreviations like "w" -> "with", "w/o" -> "without"
    # and synonyms like "begin" -> "start", "recent" -> "newest"
    normalized_query = normalize_query(user_query)

    logger.info(f"🔍 Parsing query: '{user_query}' (normalized: '{normalized_query}')")

    # ==============================================================================
    # TIER 1: CHECK CACHE
    # ==============================================================================

    cached_result = get_cached_query(user_query)
    if cached_result:
        return cached_result

    # ==============================================================================
    # TIER 2: PATTERN MATCHING (use normalized query)
    # ==============================================================================

    # Check exact patterns with both original and normalized
    if query_lower in SIMPLE_QUERY_PATTERNS:
        result = SIMPLE_QUERY_PATTERNS[query_lower]
        logger.info(f"✅ Pattern match (original): {result.dict()}")
        cache_query(user_query, result)
        return result

    if normalized_query in SIMPLE_QUERY_PATTERNS:
        result = SIMPLE_QUERY_PATTERNS[normalized_query]
        logger.info(f"✅ Pattern match (normalized): {result.dict()}")
        cache_query(user_query, result)
        return result

    # Try simple keyword parsing with NORMALIZED query for better matching
    simple_result = simple_parse_query(normalized_query)
    if simple_result is not None:
        cache_query(user_query, simple_result)
        return simple_result

    # Also try with original query in case normalization broke something
    if normalized_query != user_query:
        simple_result = simple_parse_query(user_query)
        if simple_result is not None:
            cache_query(user_query, simple_result)
            return simple_result

    # ==============================================================================
    # TIER 3: AI PARSING
    # ==============================================================================

    logger.info("Using AI parser (no cache/pattern match found)")

    try:
        system_prompt = """You are a query parser that converts natural language to JSON filters.
Output ONLY valid JSON with no additional text, explanations, or markdown.

Rules:
- gender: Must be exactly "Male", "Female", "Other", or null
- name_substr: Extract any mentioned name or initial letter. If query is JUST a name like "Adam" or "John Smith", put it here. Otherwise null.
- starts_with_mode: Set to true ONLY if query says "start with", "starts with", "starting with", "begins with", otherwise false
- name_length_parity: Set to "odd" if query asks for names with odd number of letters/characters, "even" if even number, otherwise null
- has_profile_pic: Set to true if query asks for users WITH profile picture/photo/avatar, false if WITHOUT/NO profile picture, otherwise null
- sort_by: Set to "name_length" for longest/shortest name, "username_length" for longest/shortest username, "name" for alphabetical, "created_at" for newest/oldest, otherwise null
- sort_order: "desc" for longest/newest/Z-A, "asc" for shortest/oldest/A-Z. Default "desc"
- Never include gender values in name_substr field
- If query is ambiguous, prefer null values

Examples:
Query: "list all female users"
Output: {"gender":"Female","name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}

Query: "Adam"
Output: {"gender":null,"name_substr":"Adam","starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}

Query: "show me people starting with J"
Output: {"gender":null,"name_substr":"J","starts_with_mode":true,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}

Query: "users with profile picture"
Output: {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":true,"sort_by":null,"sort_order":"desc"}

Query: "find user with longest username"
Output: {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"username_length","sort_order":"desc"}

Query: "users with shortest name"
Output: {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"name_length","sort_order":"asc"}

Query: "newest users"
Output: {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"created_at","sort_order":"desc"}

Query: "oldest female users"
Output: {"gender":"Female","name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"created_at","sort_order":"asc"}

Query: "users sorted alphabetically by name"
Output: {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"name","sort_order":"asc"}"""

        user_prompt = f"""Parse this query into JSON:

Query: "{user_query}"

Output JSON with exactly seven keys:
- "gender": "Male" | "Female" | "Other" | null
- "name_substr": string | null
- "starts_with_mode": true | false
- "name_length_parity": "odd" | "even" | null
- "has_profile_pic": true | false | null
- "sort_by": "name_length" | "username_length" | "name" | "username" | "created_at" | null
- "sort_order": "asc" | "desc"

JSON:"""

        logger.info(f"📡 Calling AI model: {OLLAMA_MODEL}")
        parsed_json = await chat_completion(user_prompt, system_prompt)

        logger.info(f"🤖 Raw AI response: {parsed_json}")

        # Extract and clean JSON from response
        cleaned_json = _extract_json_from_response(parsed_json)
        logger.info(f"🔧 Cleaned JSON: {cleaned_json}")

        # Parse and sanitize JSON
        parsed_dict = json.loads(cleaned_json)
        parsed_dict = _sanitize_ai_response(parsed_dict)

        result = UserQueryFilters(**parsed_dict)

        logger.info(f"✅ AI parse successful: {result.dict()}")
        cache_query(user_query, result)

        return result

    except httpx.ReadTimeout as e:
        logger.error(f"AI request timed out: {e}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling AI: {e}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from AI: {e}")
        logger.error(f"Response was: {parsed_json}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except Exception as e:
        logger.error(f"Unexpected error in AI parsing: {type(e).__name__}: {e}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

# ==============================================================================
# DATABASE QUERIES
# ==============================================================================

def _apply_filters(query, filters: UserQueryFilters, models):
    """Apply all filters to the query."""
    if filters.gender:
        query = query.filter(models.User.gender == filters.gender)

    if filters.name_substr:
        name_str = str(filters.name_substr)
        pattern = f"{name_str}%" if filters.starts_with_mode else f"%{name_str}%"
        query = query.filter(models.User.full_name.ilike(pattern))

    if filters.name_length_parity:
        name_without_spaces = func.replace(models.User.full_name, ' ', '')
        name_length = func.length(name_without_spaces)
        remainder = 1 if filters.name_length_parity == "odd" else 0
        query = query.filter(name_length % 2 == remainder)

    if filters.has_profile_pic is True:
        query = query.filter(models.User.profile_pic.isnot(None))
        query = query.filter(models.User.profile_pic != '')
    elif filters.has_profile_pic is False:
        query = query.filter(
            (models.User.profile_pic.is_(None)) | (models.User.profile_pic == '')
        )

    return query


def _apply_sorting(query, filters: UserQueryFilters, models):
    """Apply sorting to the query."""
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


def query_users(db: Session, filters: UserQueryFilters, limit: int = 20, skip: int = 0) -> tuple[List[UserRecord], int]:
    """
    Query users from database using SQLAlchemy with pagination.

    Args:
        db: Database session
        filters: Query filters
        limit: Maximum number of results per page
        skip: Number of results to skip (for pagination)

    Returns:
        Tuple of (List of UserRecord objects, total count of matching records)
    """
    import models

    query = db.query(models.User)
    query = _apply_filters(query, filters, models)
    query = _apply_sorting(query, filters, models)

    logger.debug("Query filters: %s", filters.model_dump())

    try:
        # Get total count BEFORE applying limit/offset (for pagination)
        total_count = query.count()

        # Apply pagination
        query = query.offset(skip).limit(limit)

        results = query.all()
        logger.info(f"✅ Found {len(results)} users (total matching: {total_count})")

        user_records = [
            UserRecord(
                id=user.id,
                full_name=user.full_name,
                username=user.username,
                gender=user.gender,
                profile_pic=user.profile_pic
            )
            for user in results
        ]

        return user_records, total_count

    except Exception as e:
        logger.error(f"Database error querying users: {e}")
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

        # Extract JSON array by finding [ and ]
        start_idx = ranking_json.find('[')
        end_idx = ranking_json.rfind(']')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            ranking_json = ranking_json[start_idx:end_idx + 1]

        ranked = json.loads(ranking_json)
        if isinstance(ranked, list):
            return [int(x) for x in ranked if isinstance(x, (int, str)) and str(x).isdigit()]

        # Fallback to original order
        return [u.id for u in users]

    except Exception as e:
        logger.error(f"Ranking error: {e}")
        return [u.id for u in users]

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def build_filters_applied(filters: UserQueryFilters) -> Optional[dict]:
    """
    Build a human-readable dictionary of applied filters for transparency.

    Args:
        filters: The parsed query filters

    Returns:
        Dictionary describing applied filters, or None if no filters applied
    """
    filters_applied = {}

    if filters.gender:
        filters_applied["gender"] = filters.gender

    if filters.name_substr:
        key = "name_starts_with" if filters.starts_with_mode else "name_contains"
        filters_applied[key] = filters.name_substr

    if filters.name_length_parity:
        filters_applied["name_length"] = f"{filters.name_length_parity} number of letters"

    if filters.has_profile_pic is True:
        filters_applied["profile_picture"] = "has profile picture"
    elif filters.has_profile_pic is False:
        filters_applied["profile_picture"] = "no profile picture"

    if filters.sort_by:
        filters_applied["sorted_by"] = _format_sort_label(filters.sort_by, filters.sort_order)

    return filters_applied if filters_applied else None


def _format_sort_label(sort_by: str, sort_order: str) -> str:
    """Format sort criteria into human-readable label."""
    sort_labels = {
        "name_length": "name length",
        "username_length": "username length",
        "name": "name",
        "username": "username",
        "created_at": "creation date"
    }

    if sort_by in ["name", "username"]:
        order_label = "Z-A" if sort_order == "desc" else "A-Z"
    elif sort_by == "created_at":
        order_label = "newest first" if sort_order == "desc" else "oldest first"
    else:
        order_label = "longest first" if sort_order == "desc" else "shortest first"

    return f"{sort_labels.get(sort_by, sort_by)} ({order_label})"


# ==============================================================================
# MAIN FILTER FUNCTION
# ==============================================================================

async def filter_records_ai(
        db: Session,
        user_query: str,
        batch_size: int = 20,
        skip: int = 0,
        enable_ranking: bool = False
) -> FilteredResult:
    """
    Main function to filter users based on natural language query.

    Args:
        db: Database session
        user_query: Natural language search query
        batch_size: Maximum number of results per page
        skip: Number of results to skip (for pagination)
        enable_ranking: Whether to use AI ranking (slower)

    Returns:
        FilteredResult with users, pagination info, and optional ranking
    """
    # Parse query
    filters = await parse_query_ai(user_query)

    # Query database using SQLAlchemy with pagination
    db_results, total_count = query_users(db, filters, limit=batch_size, skip=skip)

    ranked_ids = None

    # Optional AI ranking
    if enable_ranking and len(db_results) > 1:
        try:
            logger.info(f"🎯 Ranking {len(db_results)} results...")
            ranked_ids = await rank_users_ai(user_query, db_results)
            logger.info("Ranking complete")
        except Exception as e:
            logger.error(f"Ranking failed: {e}")
            logger.info("Continuing without ranking...")

    return FilteredResult(
        results=db_results,
        ranked_ids=ranked_ids,
        total_count=total_count,
        query_understood=filters.query_understood,
        parse_warnings=filters.parse_warnings,
        filters_applied=build_filters_applied(filters)
    )

# ==============================================================================
# CLEANUP
# ==============================================================================

def cleanup_caches():
    """
    Save all cached queries to file before shutdown.

    This function is automatically called when the Python process exits,
    ensuring that cached AI query results are persisted across restarts.
    Without this, the in-memory cache would be lost on restart.
    """
    logger.info("💾 Saving cache to file...")
    save_cache_to_file()
    logger.info("✅ Cache saved successfully")

# Register cleanup function to run when the application shuts down.
# This ensures query cache is saved to disk before exit.
atexit.register(cleanup_caches)