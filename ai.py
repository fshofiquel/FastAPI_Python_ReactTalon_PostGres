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
        warnings.append("Ends-with filtering is not supported - use 'contains' or 'starts with' instead")

    # Exact length filtering (e.g., "exactly 5 letters")
    if 'exactly' in words and bool(words & {'letter', 'char', 'character'}):
        warnings.append("Exact length filtering is not supported - only odd/even length is available")

    for warning in warnings:
        logger.warning("Unsupported query pattern: %s", warning)

    return warnings


def _detect_sorting(query_lower: str) -> tuple:
    """
    Detect sorting preferences from query.

    Returns:
        tuple: (sort_by, sort_order) where sort_by can be None
    """
    # Keywords for detecting sort preferences
    longest_words = {'longest', 'most characters'}
    shortest_words = {'shortest', 'fewest', 'least'}
    newest_words = {'newest', 'most recent', 'recently created', 'latest'}
    oldest_words = {'oldest', 'first created', 'earliest'}
    alpha_asc_words = {'alphabetical', 'a-z', 'a to z'}
    alpha_desc_words = {'reverse alphabetical', 'z-a', 'z to a'}

    has_name = 'name' in query_lower
    has_username = 'username' in query_lower

    # Check for length-based sorting
    has_longest = any(word in query_lower for word in longest_words)
    has_shortest = any(word in query_lower for word in shortest_words)

    if has_longest:
        if has_username:
            return "username_length", "desc"
        if has_name:
            return "name_length", "desc"

    if has_shortest:
        if has_username:
            return "username_length", "asc"
        if has_name:
            return "name_length", "asc"

    # Check for date-based sorting
    if any(word in query_lower for word in newest_words):
        return "created_at", "desc"
    if any(word in query_lower for word in oldest_words):
        return "created_at", "asc"

    # Check for alphabetical sorting
    if any(word in query_lower for word in alpha_desc_words):
        return "name", "desc"
    if any(word in query_lower for word in alpha_asc_words) and has_name:
        return "name", "asc"

    return None, "desc"


def _detect_profile_pic_filter(query_lower: str) -> Optional[bool]:
    """Detect profile picture filter from query."""
    # Image-related keywords
    image_words = ['pic', 'picture', 'photo', 'image', 'avatar']
    has_image_word = any(word in query_lower for word in image_words)

    if not has_image_word:
        return None

    # Check for "has/with" indicators
    has_indicators = ['with pic', 'with photo', 'with profile', 'has pic', 'has photo',
                      'have pic', 'have photo', 'got pic', 'got photo', 'profile pic']
    if any(indicator in query_lower for indicator in has_indicators):
        return True

    # Check for "without/no" indicators
    without_indicators = ['without pic', 'without photo', 'without profile', 'no pic',
                          'no photo', 'no profile', 'missing pic', 'missing photo']
    if any(indicator in query_lower for indicator in without_indicators):
        return False

    # Default: if "profile picture" mentioned, assume "has"
    if 'profile' in query_lower:
        return True

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
    if 'even' in query_lower:
        if has_length_word or 'name' in query_lower:
            return "even"

    return None


def _detect_gender(query_lower: str) -> tuple:
    """
    Detect gender filter from query.

    Returns:
        tuple: (gender, warning) where warning may be None
    """
    words = query_lower.split()

    # Female detection (check first to avoid "female" matching "male")
    if 'female' in query_lower or 'woman' in words or 'women' in words:
        return "Female", None

    # Female typo detection (fmale, femal, femails)
    female_typos = ['fmale', 'femal', 'femails', 'femail']
    if any(typo in query_lower for typo in female_typos) and 'male' not in words:
        return "Female", "Interpreted as 'female' (possible typo corrected)"

    # Male detection (exact word match to avoid matching "female")
    if 'male' in words:
        return "Male", None

    # Other gender detection
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


def _detect_name_search(query_lower: str, gender: Optional[str], has_profile_pic: Optional[bool]) -> tuple:
    """
    Detect name search patterns from query.

    Returns:
        tuple: (name_substr, starts_with_mode)
    """
    # "starts with X" pattern
    if 'starts with' in query_lower or 'starting with' in query_lower:
        letter = _find_letter_after_with(query_lower.split())
        if letter:
            return letter, True

    # "named X" pattern
    excluded = {'that', 'is', 'of', 'which', 'who', 'a', 'an', 'the'}
    name = _extract_word_after(query_lower, ['named', 'called', 'name', 'names'], excluded)
    if name:
        return _capitalize_name(name), False

    # "with X" pattern (but not profile picture related)
    if gender and not has_profile_pic:
        excluded_with = {'a', 'an', 'the', 'that', 'is', 'of', 'odd', 'even',
                         'profile', 'pic', 'picture', 'photo'}
        name = _extract_word_after(query_lower, ['with'], excluded_with)
        if name:
            return _capitalize_name(name), False

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
    """Detect if query is just a bare name (e.g., 'Adam' or 'John Smith')."""
    query_indicators = {
        'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
        'user', 'users', 'people', 'person', 'all', 'every',
        'with', 'without', 'who', 'whose', 'where', 'that', 'which',
        'the', 'a', 'an', 'and', 'or', 'not',
        'longest', 'shortest', 'oldest', 'newest', 'first', 'last',
        'name', 'named', 'called', 'username', 'picture', 'photo', 'profile',
    }

    words = query_lower.split()

    # Check for query indicator words
    if any(word in query_indicators for word in words):
        return None

    # Validate: 1-4 words, 2-40 chars, only name characters
    if not (1 <= len(words) <= 4):
        return None
    if not (2 <= len(query_original) <= 40):
        return None
    if not _is_valid_name_chars(query_original):
        return None

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
    has_no_filters = not gender and not name_substr and not name_length_parity and has_profile_pic is None
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

    if query_lower in SIMPLE_QUERY_PATTERNS:
        result = SIMPLE_QUERY_PATTERNS[query_lower]
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