"""
ai/query_parser.py - AI-Only Query Parsing

This module handles query parsing using AI (LLM) exclusively.
All queries are sent to the Ollama LLM for parsing into structured filters.
"""

import json
import logging
import re
from typing import Optional

import httpx

from ai.models import UserQueryFilters
from ai.llm import chat_completion, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# Constant for fallback message
FALLBACK_EMPTY_FILTER_MSG = "Falling back to empty filter"


# ==============================================================================
# AI RESPONSE VALIDATION
# ==============================================================================


def _extract_json_from_response(response: str) -> str:
    """Extract JSON object from AI response, handling markdown and prefixes."""
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
        return None
    normalized = value.strip().capitalize()
    if normalized not in ["Male", "Female", "Other"]:
        logger.warning(f"Invalid gender: {normalized}, setting to null")
        return None
    return normalized


def _validate_name_substr(value) -> Optional[str]:
    """Validate and clean name_substr field."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("'\"[]")
    # Filter out words that are not actual names
    invalid_values = {
        "male", "female", "other", "fmale", "femal", "non-binary", "nonbinary",
        "user", "users", "all", "null", "none", "",
        "newest", "oldest", "longest", "shortest", "alphabetical", "sorted",
        "recent", "latest", "first", "last",
        "profile", "picture", "photo", "avatar", "pic",
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
        return None
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
        return None
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
# SYSTEM PROMPT FOR AI
# ==============================================================================

SYSTEM_PROMPT = """Parse natural language to JSON. Output ONLY JSON, no text.

SORT ORDER RULES (CRITICAL):
- longest/newest = "desc"
- shortest/oldest/alphabetical = "asc"

GENDER: Male|Female|Other|null. ladies/women/gals=Female, guys/men/gentlemen=Male, non-binary=Other, fmale/femal=Female
NAME: Extract name/letter to name_substr. starts_with_mode=true if "start(s) with"/"begins with"
PROFILE: has_profile_pic=true if "with pic/photo", false if "without/w/o/no pic"
SORT: name_length for longest/shortest name, username_length for username, name for alphabetical, created_at for newest/oldest
PARITY: name_length_parity="odd"|"even" for odd/even letters

Examples:
"female users" -> {"gender":"Female","name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}
"Adam" -> {"gender":null,"name_substr":"Adam","starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}
"starting with J" -> {"gender":null,"name_substr":"J","starts_with_mode":true,"name_length_parity":null,"has_profile_pic":null,"sort_by":null,"sort_order":"desc"}
"longest username" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"username_length","sort_order":"desc"}
"shortest name" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"name_length","sort_order":"asc"}
"newest users" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"created_at","sort_order":"desc"}
"oldest users" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"created_at","sort_order":"asc"}
"alphabetical" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":null,"sort_by":"name","sort_order":"asc"}
"w/ pics" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":true,"sort_by":null,"sort_order":"desc"}
"w/o avatar" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":null,"has_profile_pic":false,"sort_by":null,"sort_order":"desc"}
"odd letters" -> {"gender":null,"name_substr":null,"starts_with_mode":false,"name_length_parity":"odd","has_profile_pic":null,"sort_by":null,"sort_order":"desc"}"""


# ==============================================================================
# MAIN AI PARSING FUNCTION
# ==============================================================================


async def parse_query_ai(user_query: str) -> UserQueryFilters:
    """
    Parse user query into structured filters using AI.

    All queries are sent directly to the LLM for parsing.

    Args:
        user_query: Natural language search query

    Returns:
        UserQueryFilters: Parsed query filters
    """
    user_query = user_query.strip()

    # Handle empty query
    if not user_query:
        logger.warning("Empty query received")
        return UserQueryFilters()

    logger.info(f"Parsing query with AI: '{user_query}'")

    try:
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
        parsed_json = await chat_completion(user_prompt, SYSTEM_PROMPT)

        logger.info(f"Raw AI response: {parsed_json}")

        # Extract and clean JSON
        cleaned_json = _extract_json_from_response(parsed_json)
        logger.info(f"Cleaned JSON: {cleaned_json}")

        # Parse and sanitize
        parsed_dict = json.loads(cleaned_json)
        parsed_dict = _sanitize_ai_response(parsed_dict)

        result = UserQueryFilters(**parsed_dict)

        logger.info(f"AI parse successful: {result.dict()}")

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
