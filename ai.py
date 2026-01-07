import os
import json
import httpx
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import BaseModel
import re

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

# Query cache: stores parsed queries to avoid repeated AI calls
QUERY_CACHE = {}


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


async def chat_completion(user_input: str, system_prompt: str = None) -> str:
    if not OLLAMA_BASE_URL or not OLLAMA_API_KEY:
        raise RuntimeError("OLLAMA_BASE_URL and OLLAMA_API_KEY must be set")

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
        "temperature": 0.0,
        "top_p": 0.95,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]


def normalize_query(query: str) -> str:
    """
    Normalize query for fuzzy cache matching.
    Makes similar queries map to the same cache key.
    """
    q = query.lower().strip()

    # Remove extra spaces
    q = ' '.join(q.split())

    # Normalize common query starters to standard form
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
    print(f"[NORMALIZE] '{query}' → '{result}'")
    return result


def simple_parse_query(user_query: str) -> Optional[UserQueryFilters]:
    query_lower = user_query.lower().strip()

    complex_words = [
        'whose', 'rhyme', 'longer', 'shorter', 'exactly', 'more', 'less',
        'odd', 'even', 'three', 'two', 'contains', 'ends', 'birthdate',
        'birthday', 'age', 'registered', 'profile', 'password', 'username'
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

    if 'named' in query_lower or 'called' in query_lower:
        match = re.search(r'(?:named|called)\s+([A-Z][a-z]+)', user_query)
        if match:
            name_substr = match.group(1)

    elif 'starts with' in query_lower or 'starting with' in query_lower:
        match = re.search(r'start(?:s|ing)?\s+with\s+([A-Z])', user_query, re.IGNORECASE)
        if match:
            name_substr = match.group(1).upper()
            starts_with_mode = True

    elif 'with' in query_lower and gender:
        match = re.search(r'with\s+([A-Z][a-z]+)', user_query)
        if match:
            name_substr = match.group(1)

    if gender or name_substr:
        result = UserQueryFilters(gender=gender, name_substr=name_substr, starts_with_mode=starts_with_mode)
        return result

    return None


async def parse_query_ai(user_query: str) -> UserQueryFilters:
    # Strip whitespace from input
    user_query = user_query.strip()
    query_lower = user_query.lower()

    print(f"[DEBUG] Original query: '{user_query}'")

    # Check exact cache first
    if user_query in QUERY_CACHE:
        print(f"=== EXACT CACHE HIT ===")
        print(f"User query: {user_query}")
        cached_result = QUERY_CACHE[user_query]
        print(f"Cached filters: {cached_result.dict()}")
        print(f"======================")
        return cached_result

    # Check fuzzy cache (normalized query)
    normalized = normalize_query(user_query)
    print(f"[DEBUG] Checking fuzzy cache for normalized key: '{normalized}'")
    print(f"[DEBUG] Current cache keys: {list(QUERY_CACHE.keys())[:5]}")  # Show first 5 keys

    if normalized in QUERY_CACHE:
        print(f"=== FUZZY CACHE HIT ===")
        print(f"User query: {user_query}")
        print(f"Normalized to: {normalized}")
        cached_result = QUERY_CACHE[normalized]
        print(f"Cached filters: {cached_result.dict()}")
        print(f"======================")
        # Cache the original query too for faster exact matches next time
        QUERY_CACHE[user_query] = cached_result
        return cached_result

    print(f"[DEBUG] No cache hit, continuing to parse...")

    simple_patterns = {
        "list all female": UserQueryFilters(gender="Female", name_substr=None),
        "show all female": UserQueryFilters(gender="Female", name_substr=None),
        "all female users": UserQueryFilters(gender="Female", name_substr=None),
        "female users": UserQueryFilters(gender="Female", name_substr=None),
        "show female": UserQueryFilters(gender="Female", name_substr=None),
        "all females": UserQueryFilters(gender="Female", name_substr=None),
        "list females": UserQueryFilters(gender="Female", name_substr=None),
        "list all male": UserQueryFilters(gender="Male", name_substr=None),
        "show all male": UserQueryFilters(gender="Male", name_substr=None),
        "all male users": UserQueryFilters(gender="Male", name_substr=None),
        "male users": UserQueryFilters(gender="Male", name_substr=None),
        "show male": UserQueryFilters(gender="Male", name_substr=None),
        "all males": UserQueryFilters(gender="Male", name_substr=None),
        "list males": UserQueryFilters(gender="Male", name_substr=None),
        "list all other": UserQueryFilters(gender="Other", name_substr=None),
        "show all other": UserQueryFilters(gender="Other", name_substr=None),
        "all other users": UserQueryFilters(gender="Other", name_substr=None),
        "other users": UserQueryFilters(gender="Other", name_substr=None),
        "show other": UserQueryFilters(gender="Other", name_substr=None),
        "users with other gender": UserQueryFilters(gender="Other", name_substr=None),
        "users that have a gender of other": UserQueryFilters(gender="Other", name_substr=None),
        "list all users that have a gender of other": UserQueryFilters(gender="Other", name_substr=None),
        "list all users": UserQueryFilters(gender=None, name_substr=None),
        "show all users": UserQueryFilters(gender=None, name_substr=None),
        "all users": UserQueryFilters(gender=None, name_substr=None),
    }

    if query_lower in simple_patterns:
        result = simple_patterns[query_lower]
        print(f"=== PATTERN MATCH ===")
        print(f"User query: {user_query}")
        print(f"Matched pattern: {query_lower}")
        print(f"Parsed filters: {result.dict()}")
        print(f"===================")
        # Cache it
        QUERY_CACHE[user_query] = result
        QUERY_CACHE[normalized] = result
        return result

    simple_result = simple_parse_query(user_query)
    if simple_result is not None:
        print(f"=== KEYWORD PARSING ===")
        print(f"User query: {user_query}")
        print(f"Parsed filters: {simple_result.dict()}")
        print(f"======================")
        # Cache it
        QUERY_CACHE[user_query] = simple_result
        QUERY_CACHE[normalized] = simple_result
        return simple_result

    print(f"=== USING REMOTE AI (may be slow) ===")
    print(f"User query: {user_query}")

    try:
        system_prompt = """You output only JSON. No text, no explanation."""

        user_prompt = f"""Query: "{user_query}"
Output JSON with keys "gender" (Male/Female/Other or null) and "name_substr" (name string or null).

Examples:
"list female" -> {{"gender":"Female","name_substr":null}}
"users named John" -> {{"gender":null,"name_substr":"John"}}
"female users with Taylor" -> {{"gender":"Female","name_substr":"Taylor"}}

JSON:"""

        print(f"Calling remote AI model ({OLLAMA_MODEL})...")
        parsed_json = await chat_completion(user_prompt, system_prompt)

        print(f"AI raw response: {parsed_json}")

        parsed_json = parsed_json.strip()

        if "```" in parsed_json:
            parsed_json = parsed_json.split("```")[1] if len(parsed_json.split("```")) > 1 else parsed_json
            parsed_json = parsed_json.replace("json", "").strip()

        for prefix in ["output:", "response:", "json:", "result:", "answer:"]:
            if parsed_json.lower().startswith(prefix):
                parsed_json = parsed_json[len(prefix):].strip()

        json_match = re.search(r'\{[^{}]*"gender"[^{}]*"name_substr"[^{}]*\}', parsed_json)
        if json_match:
            parsed_json = json_match.group(0)

        print(f"Cleaned JSON: {parsed_json}")

        parsed_dict = json.loads(parsed_json)

        if "name_substr" in parsed_dict and parsed_dict["name_substr"] is not None:
            name_val = parsed_dict["name_substr"]

            if isinstance(name_val, list):
                name_val = name_val[0] if len(name_val) > 0 else None

            if isinstance(name_val, str):
                name_val = name_val.strip().strip("'\"[]").strip()
                if name_val.lower() in ["male", "female", "other", "user", "users", "all", "null", "none"]:
                    name_val = None
                parsed_dict["name_substr"] = name_val if name_val else None
            else:
                parsed_dict["name_substr"] = None

        if "gender" in parsed_dict and parsed_dict["gender"] is not None:
            gender_val = parsed_dict["gender"]
            if isinstance(gender_val, str):
                gender_val = gender_val.strip().capitalize()
                if gender_val not in ["Male", "Female", "Other"]:
                    gender_val = None
                parsed_dict["gender"] = gender_val

        print(f"Parsed filters: {parsed_dict}")
        print(f"======================")

        result = UserQueryFilters(**parsed_dict)

        # Cache the result for future use
        QUERY_CACHE[user_query] = result
        QUERY_CACHE[normalized] = result
        print(f"Cached query for future requests")

        return result

    except httpx.ReadTimeout as e:
        print(f"AI request timed out after 10 seconds: {e}")
        print(f"Your remote AI server may be slow or unresponsive")
        print(f"Falling back to empty filter (will return all users)")
        return UserQueryFilters()
    except httpx.HTTPError as e:
        print(f"HTTP error calling AI: {e}")
        print(f"Check if your OLLAMA_BASE_URL and OLLAMA_API_KEY are correct")
        print(f"Falling back to empty filter (will return all users)")
        return UserQueryFilters()
    except json.JSONDecodeError as e:
        print(f"AI returned invalid JSON: {e}")
        print(f"AI response was: {parsed_json}")
        print(f"Falling back to empty filter (will return all users)")
        return UserQueryFilters()
    except Exception as e:
        print(f"AI parsing failed with unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print(f"Falling back to empty filter (will return all users)")
        return UserQueryFilters()


async def query_users(filters: UserQueryFilters, limit: int = 20) -> List[UserRecord]:
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

    print(f"SQL: {sql}")
    print(f"Params: {params}")
    print(f"Starts with mode: {filters.starts_with_mode}")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(sql, *params)
        print(f"Found {len(rows)} rows")
        return [UserRecord(**dict(r)) for r in rows]
    finally:
        await conn.close()


async def rank_users_ai(query: str, users: List[UserRecord]) -> List[int]:
    if not users:
        return []

    system_prompt = """You are a ranking assistant. Output ONLY a JSON array of integers."""

    user_prompt = f"""Rank these users by relevance to: "{query}"

Users:
{json.dumps([{"id": u.id, "name": u.full_name, "gender": u.gender} for u in users], indent=2)}

Return ONLY a JSON array of user IDs, ordered by relevance (most relevant first).
Example: [3, 1, 5, 2, 4]

Your response:"""

    ranking_json = await chat_completion(user_prompt, system_prompt)

    ranking_json = ranking_json.strip()

    if "```" in ranking_json:
        parts = ranking_json.split("```")
        if len(parts) >= 2:
            ranking_json = parts[1]
            if ranking_json.strip().startswith("json"):
                ranking_json = ranking_json.strip()[4:]

    ranking_json = ranking_json.strip()

    try:
        ranked = json.loads(ranking_json)
        if isinstance(ranked, list):
            return [int(x) for x in ranked if isinstance(x, (int, str)) and str(x).isdigit()]
        return []
    except Exception as e:
        print(f"Error parsing ranking: {e}")
        print(f"AI returned: {ranking_json}")
        return []


async def filter_records_ai(user_query: str, batch_size: int = 20, enable_ranking: bool = False) -> FilteredResult:
    filters = await parse_query_ai(user_query)
    db_results = await query_users(filters, limit=batch_size)
    ranked_ids = None

    if enable_ranking and len(db_results) > 1:
        try:
            print(f"Attempting to rank {len(db_results)} results...")
            ranked_ids = await rank_users_ai(user_query, db_results)
            print(f"Ranking complete: {ranked_ids}")
        except Exception as e:
            print(f"Ranking failed (non-critical): {e}")
            print("Continuing without ranking...")

    return FilteredResult(
        results=db_results,
        ranked_ids=ranked_ids
    )