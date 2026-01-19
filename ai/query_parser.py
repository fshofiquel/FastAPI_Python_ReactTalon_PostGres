"""
ai/query_parser.py - Query Parsing Orchestration

This module handles the main query parsing logic using a 3-tier approach:
1. CACHE LOOKUP: Check for cached results first
2. PATTERN MATCHING: Use simple keyword/regex patterns
3. AI PARSING: Fall back to LLM for complex queries

Query Normalization:
    Similar queries are normalized to the same form to improve cache hit rate.
    Example: "find females" and "show me female users" both become "show female user"
"""

import json
import logging
from typing import Optional

import httpx

from ai.models import UserQueryFilters
from ai.cache import get_cached_query, cache_query
from ai.llm import chat_completion, OLLAMA_MODEL
from ai.detectors import (
    PATTERN_STARTS_WITH,
    detect_unsupported_patterns,
    detect_sorting,
    detect_profile_pic_filter,
    detect_name_length_parity,
    detect_gender,
    detect_name_search,
    detect_bare_name,
    is_complex_query,
    SORT_SHORTEST,
    SORT_LONGEST,
    SORT_NEWEST,
)

logger = logging.getLogger(__name__)

# Constant for fallback message
FALLBACK_EMPTY_FILTER_MSG = "Falling back to empty filter"

# ==============================================================================
# QUERY NORMALIZATION
# ==============================================================================


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

    # Security: Remove newlines to prevent injection
    if '\n' in q:
        q = q.split('\n')[0].strip()

    # Remove extra spaces
    q = ' '.join(q.split())

    # Step 1: Expand Abbreviations
    abbreviations = {
        ' w/o ': ' without ',
        ' w/ ': ' with ',
        ' w ': ' with ',
        ' pic ': ' picture ',
        ' pics ': ' pictures ',
        ' u ': ' you ',
        ' ur ': ' your ',
        ' ppl ': ' people ',
        ' dont ': " don't ",
        ' doesnt ': " doesn't ",
        ' cant ': " can't ",
        ' wont ': " won't ",
    }
    for old, new in abbreviations.items():
        q = q.replace(old, new)

    # Step 2: Replace Synonyms
    synonyms = {
        'begin with': PATTERN_STARTS_WITH,
        'begins with': PATTERN_STARTS_WITH,
        'beginning with': 'starting with',
        'start at': PATTERN_STARTS_WITH,
        'big ': f'{SORT_LONGEST} ',
        'bigger ': f'{SORT_LONGEST} ',
        'biggest ': f'{SORT_LONGEST} ',
        'small ': f'{SORT_SHORTEST} ',
        'smaller ': f'{SORT_SHORTEST} ',
        'smallest ': f'{SORT_SHORTEST} ',
        'recent ': f'{SORT_NEWEST} ',
        'new ': f'{SORT_NEWEST} ',
        'latest ': f'{SORT_NEWEST} ',
        'signups': 'users',
        'women ': 'female ',
        'men ': 'male ',
        'guys': 'male users',
        'gals': 'female users',
        'ladies': 'female users',
        'gentlemen': 'male users',
        'non-binary': 'other gender',
        'nonbinary': 'other gender',
        'nb ': 'other gender ',
        'avatar': 'profile picture',
        'avatars': 'profile pictures',
        'photo': 'picture',
        'photos': 'pictures',
        'image': 'picture',
        'images': 'pictures',
    }
    for old, new in synonyms.items():
        q = q.replace(old, new)

    # Step 3: Normalize Query Starters
    starters = [
        'show me', 'find me', 'get me', 'list me', 'give me',
        'show', 'find', 'get', 'list', 'search', 'display'
    ]
    for starter in starters:
        if q.startswith(starter + ' '):
            q = 'show ' + q[len(starter):].strip()
            break

    # Step 4: Consolidate Variations
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

    # Step 5: Remove Filler Words
    filler_words = ['please', 'could you', 'can you', 'would you', 'will you', 'the', 'an', 'my']
    words = q.split()
    words = [w for w in words if w not in filler_words]

    result = ' '.join(words)
    logger.debug(f"[NORMALIZE] '{query}' -> '{result}'")
    return result


# ==============================================================================
# SIMPLE PATTERN MATCHING
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
    parse_warnings = detect_unsupported_patterns(query_lower)

    # Detect all filter types
    sort_by, sort_order = detect_sorting(query_lower)
    has_profile_pic = detect_profile_pic_filter(query_lower)
    name_length_parity = detect_name_length_parity(query_lower)

    gender, gender_warning = detect_gender(query_lower)
    if gender_warning:
        parse_warnings.append(gender_warning)

    name_substr, starts_with_mode = detect_name_search(query_lower, gender, has_profile_pic)

    # Try bare name detection if no other filters found
    has_no_filters = (
        not gender and not name_substr and not name_length_parity
        and has_profile_pic is None and not sort_by
    )
    if has_no_filters:
        name_substr = detect_bare_name(query_lower, query_original)

    # Check for complex queries that need AI
    if has_no_filters and not name_substr and is_complex_query(query_lower):
        return None

    # Build result if any filters were detected
    has_any_filter = (
        gender or name_substr or name_length_parity
        or has_profile_pic is not None or sort_by
    )
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
        logger.info(f"Simple parse successful: {result.model_dump()}")
        return result

    # Return with warnings if we have them but no meaningful filters
    if parse_warnings:
        return UserQueryFilters(query_understood=False, parse_warnings=parse_warnings)

    return None


# ==============================================================================
# AI RESPONSE VALIDATION
# ==============================================================================


def _extract_json_from_response(response: str) -> str:
    """Extract JSON object from AI response, handling markdown and prefixes."""
    result = response.strip()

    # Remove markdown code blocks
    if "```" in result:
        start = result.find("```")
        end = result.rfind("```")
        if start != end:
            content = result[start + 3:end]
            if content.startswith("json"):
                content = content[4:]
            result = content.strip()

    # Remove common prefixes
    prefixes = ["output:", "response:", "json:", "result:", "answer:"]
    for prefix in prefixes:
        if result.lower().startswith(prefix):
            result = result[len(prefix):].strip()

    # Extract JSON object
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
    # Filter out words that are not actual names
    invalid_values = {
        # Gender words
        "male", "female", "other", "fmale", "femal", "non-binary", "nonbinary",
        # Command/filter words
        "user", "users", "all", "null", "none", "",
        # Sorting words
        "newest", "oldest", "longest", "shortest", "alphabetical", "sorted",
        "recent", "latest", "first", "last",
        # Profile words
        "profile", "picture", "photo", "avatar", "pic",
        # Misc
        "with", "without", "ends", "order",
    }
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
    """Validate and sanitize all fields in the parsed AI response."""
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
# MAIN AI PARSING FUNCTION
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
    normalized_query = normalize_query(user_query)

    logger.info(f"Parsing query: '{user_query}' (normalized: '{normalized_query}')")

    # ==============================================================================
    # TIER 1: CHECK CACHE
    # ==============================================================================

    cached_result = get_cached_query(user_query, normalize_query)
    if cached_result:
        return cached_result

    # ==============================================================================
    # TIER 2: PATTERN MATCHING
    # ==============================================================================

    # Check exact patterns
    if query_lower in SIMPLE_QUERY_PATTERNS:
        result = SIMPLE_QUERY_PATTERNS[query_lower]
        logger.info(f"Pattern match (original): {result.dict()}")
        cache_query(user_query, result, normalize_query)
        return result

    if normalized_query in SIMPLE_QUERY_PATTERNS:
        result = SIMPLE_QUERY_PATTERNS[normalized_query]
        logger.info(f"Pattern match (normalized): {result.dict()}")
        cache_query(user_query, result, normalize_query)
        return result

    # Try simple keyword parsing with normalized query
    simple_result = simple_parse_query(normalized_query)
    if simple_result is not None:
        cache_query(user_query, simple_result, normalize_query)
        return simple_result

    # Also try with original query
    if normalized_query != user_query:
        simple_result = simple_parse_query(user_query)
        if simple_result is not None:
            cache_query(user_query, simple_result, normalize_query)
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

        logger.info(f"Calling AI model: {OLLAMA_MODEL}")
        parsed_json = await chat_completion(user_prompt, system_prompt)

        logger.info(f"Raw AI response: {parsed_json}")

        # Extract and clean JSON
        cleaned_json = _extract_json_from_response(parsed_json)
        logger.info(f"Cleaned JSON: {cleaned_json}")

        # Parse and sanitize
        parsed_dict = json.loads(cleaned_json)
        parsed_dict = _sanitize_ai_response(parsed_dict)

        result = UserQueryFilters(**parsed_dict)

        logger.info(f"AI parse successful: {result.dict()}")
        cache_query(user_query, result, normalize_query)

        return result

    except httpx.ReadTimeout as exc:
        logger.error(f"AI request timed out: {exc}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except httpx.HTTPError as exc:
        logger.error(f"HTTP error calling AI: {exc}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except json.JSONDecodeError as exc:
        logger.error(f"Invalid JSON from AI: {exc}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()

    except Exception as exc:
        logger.error(f"Unexpected error in AI parsing: {type(exc).__name__}: {exc}")
        logger.warning(FALLBACK_EMPTY_FILTER_MSG)
        return UserQueryFilters()
