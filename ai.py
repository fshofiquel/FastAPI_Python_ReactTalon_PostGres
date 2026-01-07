import os
import json
import httpx
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import BaseModel

load_dotenv()

# ---------- Ollama AI Settings ----------
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

# ---------- Database URL ----------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

# ---------- Pydantic Models ----------
class UserRecord(BaseModel):
    id: int
    full_name: str
    username: str
    gender: str

class UserQueryFilters(BaseModel):
    gender: Optional[str] = None  # Can be: Male, Female, or Other
    name_substr: Optional[str] = None

class FilteredResult(BaseModel):
    results: List[UserRecord]
    ranked_ids: Optional[List[int]] = None


# ---------- AI Helper ----------
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
        "temperature": 0.0,  # Qwen3 works best at 0 for structured outputs
        "top_p": 0.95,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:  # Increased to 60s for ranking
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]


# ---------- AI-driven Query Parsing ----------
async def parse_query_ai(user_query: str) -> UserQueryFilters:
    query_lower = user_query.lower().strip()

    # Simple keyword-based fallback for common patterns (faster and more reliable)
    simple_patterns = {
        # Gender-only queries - Female
        "list all female": UserQueryFilters(gender="Female", name_substr=None),
        "show all female": UserQueryFilters(gender="Female", name_substr=None),
        "all female users": UserQueryFilters(gender="Female", name_substr=None),
        "female users": UserQueryFilters(gender="Female", name_substr=None),
        "show female": UserQueryFilters(gender="Female", name_substr=None),
        "all females": UserQueryFilters(gender="Female", name_substr=None),
        "list females": UserQueryFilters(gender="Female", name_substr=None),

        # Gender-only queries - Male
        "list all male": UserQueryFilters(gender="Male", name_substr=None),
        "show all male": UserQueryFilters(gender="Male", name_substr=None),
        "all male users": UserQueryFilters(gender="Male", name_substr=None),
        "male users": UserQueryFilters(gender="Male", name_substr=None),
        "show male": UserQueryFilters(gender="Male", name_substr=None),
        "all males": UserQueryFilters(gender="Male", name_substr=None),
        "list males": UserQueryFilters(gender="Male", name_substr=None),

        # Gender-only queries - Other
        "list all other": UserQueryFilters(gender="Other", name_substr=None),
        "show all other": UserQueryFilters(gender="Other", name_substr=None),
        "all other users": UserQueryFilters(gender="Other", name_substr=None),
        "other users": UserQueryFilters(gender="Other", name_substr=None),
        "show other": UserQueryFilters(gender="Other", name_substr=None),
        "users with other gender": UserQueryFilters(gender="Other", name_substr=None),
        "users that have a gender of other": UserQueryFilters(gender="Other", name_substr=None),
        "list all users that have a gender of other": UserQueryFilters(gender="Other", name_substr=None),

        # All users
        "list all users": UserQueryFilters(gender=None, name_substr=None),
        "show all users": UserQueryFilters(gender=None, name_substr=None),
        "all users": UserQueryFilters(gender=None, name_substr=None),
    }

    # Check if query matches any simple pattern
    if query_lower in simple_patterns:
        result = simple_patterns[query_lower]
        print(f"=== PATTERN MATCH ===")
        print(f"User query: {user_query}")
        print(f"Matched pattern: {query_lower}")
        print(f"Parsed filters: {result.dict()}")
        print(f"===================")
        return result

    # Use AI for more complex queries - Optimized for Qwen3
    system_prompt = """You are a database query parser that outputs only valid JSON.
Never include explanations, markdown, or any text outside the JSON object."""

    user_prompt = f"""Convert this search query into a JSON object with exactly two keys: "gender" and "name_substr"

RULES:
1. "gender": Set to "Male", "Female", or "Other" if the query filters by gender, otherwise set to null
2. "name_substr": Set to a person's name ONLY if the query mentions searching for a specific name
   - Examples of names: "Taylor", "John", "Smith", "Sarah"
   - NOT names: "male", "female", "other", "user", "users", "all", "list", "show"
   - Set to null if no specific person's name is mentioned

EXAMPLES:
Query: "List all female"
Response: {{"gender": "Female", "name_substr": null}}

Query: "Female users with Taylor in their name"
Response: {{"gender": "Female", "name_substr": "Taylor"}}

Query: "Users named John"
Response: {{"gender": null, "name_substr": "John"}}

Query: "Show males"
Response: {{"gender": "Male", "name_substr": null}}

Query: "Users with other gender"
Response: {{"gender": "Other", "name_substr": null}}

Query: "List all users that have a gender of other"
Response: {{"gender": "Other", "name_substr": null}}

Query: "Find Smith"
Response: {{"gender": null, "name_substr": "Smith"}}

NOW PARSE THIS QUERY:
Query: "{user_query}"
Response:"""

    parsed_json = await chat_completion(user_prompt, system_prompt)

    print(f"=== AI QUERY PARSING ===")
    print(f"User query: {user_query}")
    print(f"AI raw response: {parsed_json}")

    # Clean up response - handle various formats
    parsed_json = parsed_json.strip()

    # Remove markdown code blocks
    if "```" in parsed_json:
        # Extract content between first and last ```
        parts = parsed_json.split("```")
        if len(parts) >= 2:
            parsed_json = parts[1]
            # Remove 'json' language marker if present
            if parsed_json.strip().startswith("json"):
                parsed_json = parsed_json.strip()[4:]

    # Remove any "Output:" or "Response:" prefix that some models add
    if parsed_json.lower().startswith(("output:", "response:")):
        parsed_json = parsed_json.split(":", 1)[1]

    parsed_json = parsed_json.strip()

    try:
        parsed_dict = json.loads(parsed_json)

        # Normalize the name_substr value
        if "name_substr" in parsed_dict and parsed_dict["name_substr"] is not None:
            name_val = parsed_dict["name_substr"]

            # If AI returned a list, extract the first element
            if isinstance(name_val, list):
                name_val = name_val[0] if len(name_val) > 0 else None

            # Clean the string value
            if isinstance(name_val, str):
                name_val = name_val.strip().strip("'\"[]").strip()

                # Validate: don't use gender words as names
                if name_val.lower() in ["male", "female", "user", "users", "all"]:
                    name_val = None

                parsed_dict["name_substr"] = name_val if name_val else None
            else:
                parsed_dict["name_substr"] = None

        # Normalize gender
        if "gender" in parsed_dict and parsed_dict["gender"] is not None:
            gender_val = parsed_dict["gender"]
            if isinstance(gender_val, str):
                gender_val = gender_val.strip().capitalize()
                # Only accept valid genders
                if gender_val not in ["Male", "Female", "Other"]:
                    gender_val = None
                parsed_dict["gender"] = gender_val

        print(f"Parsed filters: {parsed_dict}")
        print(f"======================")
        return UserQueryFilters(**parsed_dict)

    except Exception as e:
        print(f"Error parsing AI response: {e}")
        print(f"AI returned: {parsed_json}")
        # Fallback: return empty filters
        return UserQueryFilters()


# ---------- Database Query ----------
async def query_users(filters: UserQueryFilters, limit: int = 20) -> List[UserRecord]:
    sql = "SELECT id, full_name, username, gender FROM users WHERE TRUE"
    params = []

    if filters.gender:
        params.append(filters.gender)
        sql += f" AND gender = ${len(params)}"

    if filters.name_substr:
        name_str = str(filters.name_substr)
        params.append(f"%{name_str}%")
        sql += f" AND full_name ILIKE ${len(params)}"

    sql += f" LIMIT {limit}"

    print(f"SQL: {sql}")
    print(f"Params: {params}")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(sql, *params)
        print(f"Found {len(rows)} rows")
        return [UserRecord(**dict(r)) for r in rows]
    finally:
        await conn.close()


# ---------- AI Ranking ----------
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

    # Clean response
    ranking_json = ranking_json.strip()

    # Remove markdown
    if "```" in ranking_json:
        parts = ranking_json.split("```")
        if len(parts) >= 2:
            ranking_json = parts[1]
            if ranking_json.strip().startswith("json"):
                ranking_json = ranking_json.strip()[4:]

    ranking_json = ranking_json.strip()

    try:
        ranked = json.loads(ranking_json)
        # Ensure it's a list of integers
        if isinstance(ranked, list):
            return [int(x) for x in ranked if isinstance(x, (int, str)) and str(x).isdigit()]
        return []
    except Exception as e:
        print(f"Error parsing ranking: {e}")
        print(f"AI returned: {ranking_json}")
        return []


# ---------- Main Filter Function ----------
async def filter_records_ai(user_query: str, batch_size: int = 20, enable_ranking: bool = False) -> FilteredResult:
    """
    Main function to filter records using AI.

    Args:
        user_query: Natural language search query
        batch_size: Maximum number of results to return
        enable_ranking: Whether to use AI ranking (disabled by default for performance)
    """
    # Parse query
    filters = await parse_query_ai(user_query)

    # Fetch users from DB
    db_results = await query_users(filters, limit=batch_size)

    # AI ranking is optional and disabled by default for performance
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