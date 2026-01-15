"""
ai/cache.py - Multi-Layer Caching System for AI Queries

This module provides a 3-tier caching system for AI query results:
1. Redis (if available): Fastest, distributed, 24-hour TTL
2. In-memory dict: Always available, very fast, clears on restart
3. File-based JSON: Persistent across restarts, used as fallback

The caching dramatically improves response time by avoiding
repeated AI API calls for identical or similar queries.
"""

import os
import json
import logging
import atexit
from pathlib import Path
from typing import Optional

from ai.models import UserQueryFilters

logger = logging.getLogger(__name__)

# ==============================================================================
# CACHE STORAGE
# ==============================================================================

IN_MEMORY_CACHE = {}
CACHE_FILE = Path("query_cache.json")

# ==============================================================================
# REDIS SETUP (Optional)
# ==============================================================================

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
    logger.info("Redis cache connected successfully")

except ImportError:
    logger.info("Redis not installed, using file-based cache")
except Exception as exc:
    logger.warning(f"Redis not available: {exc}. Using file-based cache")

# ==============================================================================
# FILE CACHE OPERATIONS
# ==============================================================================


def load_cache_from_file() -> dict:
    """
    Load query cache from JSON file and convert to UserQueryFilters objects.

    Returns:
        dict: Cache dictionary with query strings as keys
    """
    global IN_MEMORY_CACHE
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                converted_cache = {}
                for key, value in data.items():
                    if isinstance(value, dict):
                        try:
                            converted_cache[key] = UserQueryFilters(**value)
                        except Exception as exc:
                            logger.warning(f"Failed to convert cached entry '{key}': {exc}")
                    else:
                        converted_cache[key] = value
                logger.info(f"Loaded {len(converted_cache)} cached queries from file")
                return converted_cache
    except Exception as exc:
        logger.error(f"Failed to load cache file: {exc}")
    return {}


def save_cache_to_file() -> None:
    """Save query cache to JSON file."""
    try:
        with open(CACHE_FILE, 'w') as f:
            serializable_cache = {}
            for key, value in IN_MEMORY_CACHE.items():
                if hasattr(value, 'dict'):
                    serializable_cache[key] = value.dict()
                else:
                    serializable_cache[key] = value

            json.dump(serializable_cache, f, indent=2)
            logger.info(f"Saved {len(serializable_cache)} queries to cache file")
    except Exception as exc:
        logger.error(f"Failed to save cache file: {exc}")


# Initialize in-memory cache from file on module load
IN_MEMORY_CACHE = load_cache_from_file()

# ==============================================================================
# CACHE OPERATIONS
# ==============================================================================


def get_cached_query(query: str, normalize_func=None) -> Optional[UserQueryFilters]:
    """
    Retrieve cached query result from all cache layers.

    Tries caches in order: Redis -> In-memory exact -> In-memory normalized

    Args:
        query: Search query string
        normalize_func: Optional function to normalize queries for fuzzy matching

    Returns:
        UserQueryFilters if cached, None otherwise
    """
    # Try Redis first
    if USE_REDIS and redis_client:
        try:
            normalized = normalize_func(query) if normalize_func else query
            cache_key = f"query:{normalized}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                logger.info(f"Redis cache hit for: {query}")
                filters_dict = json.loads(cached_data)
                filters = UserQueryFilters(**filters_dict)
                IN_MEMORY_CACHE[query] = filters
                return filters
        except Exception as exc:
            logger.error(f"Redis get error: {exc}")

    # Try exact match in memory
    if query in IN_MEMORY_CACHE:
        logger.info(f"In-memory cache hit for: {query}")
        cached = IN_MEMORY_CACHE[query]
        if isinstance(cached, dict):
            return UserQueryFilters(**cached)
        return cached

    # Try normalized query if normalize function provided
    if normalize_func:
        normalized = normalize_func(query)
        if normalized in IN_MEMORY_CACHE:
            logger.info(f"Fuzzy cache hit for: {query}")
            result = IN_MEMORY_CACHE[normalized]
            if isinstance(result, dict):
                result = UserQueryFilters(**result)
            IN_MEMORY_CACHE[query] = result
            return result

    logger.debug(f"Cache miss for: {query}")
    return None


def cache_query(query: str, filters: UserQueryFilters, normalize_func=None) -> None:
    """
    Cache query result in all available cache layers.

    Args:
        query: Search query string
        filters: Parsed filters to cache
        normalize_func: Optional function to normalize queries
    """
    normalized = normalize_func(query) if normalize_func else query

    # Cache in Redis
    if USE_REDIS and redis_client:
        try:
            cache_key = f"query:{normalized}"
            redis_client.setex(
                cache_key,
                86400,  # 24 hours TTL
                json.dumps(filters.dict())
            )
            logger.debug(f"Cached in Redis: {query}")
        except Exception as exc:
            logger.error(f"Redis set error: {exc}")

    # Always cache in memory
    IN_MEMORY_CACHE[query] = filters
    IN_MEMORY_CACHE[normalized] = filters

    logger.debug(f"Cached in memory: {query}")

    # Periodically save to file (every 10th cache)
    if len(IN_MEMORY_CACHE) % 10 == 0:
        save_cache_to_file()


def get_cache_stats() -> dict:
    """
    Get cache statistics for monitoring.

    Returns:
        dict: Statistics including cache sizes and Redis info
    """
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
        except Exception as exc:
            logger.error(f"Error getting Redis stats: {exc}")

    return stats


def clear_all_caches() -> dict:
    """
    Clear all query caches (in-memory, Redis, and file).

    This function is useful when:
    - Query parsing logic has been updated
    - Testing new query patterns
    - Debugging cache-related issues
    - Resetting the system to a clean state

    Returns:
        dict: Statistics about what was cleared
    """
    global IN_MEMORY_CACHE
    cleared = {"in_memory": 0, "redis": 0, "file": False}

    # Clear in-memory cache
    cleared["in_memory"] = len(IN_MEMORY_CACHE)
    IN_MEMORY_CACHE = {}

    # Clear Redis cache if available
    if USE_REDIS and redis_client:
        try:
            keys = redis_client.keys("query:*")
            if keys:
                cleared["redis"] = len(keys)
                redis_client.delete(*keys)
        except Exception as exc:
            logger.error(f"Error clearing Redis cache: {exc}")

    # Clear file cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump({}, f)
            cleared["file"] = True
        except Exception as exc:
            logger.error(f"Error clearing file cache: {exc}")

    logger.info(f"Cleared caches: {cleared}")
    return cleared


def cleanup_caches() -> None:
    """
    Save all cached queries to file before shutdown.

    This is automatically called when the Python process exits.
    """
    logger.info("Saving cache to file...")
    save_cache_to_file()
    logger.info("Cache saved successfully")


# Register cleanup function for graceful shutdown
atexit.register(cleanup_caches)
