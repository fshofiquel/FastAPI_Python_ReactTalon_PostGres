"""
ai/llm.py - LLM Integration for AI-Powered Search

This module handles all communication with the Ollama LLM API:
- Persistent HTTP client with connection pooling
- Chat completion for query parsing
- Optional AI-based result ranking

Performance Optimization:
    The module uses a persistent HTTP client to avoid TCP/TLS handshake
    overhead on each request, reducing latency by 30-50%.
"""

import os
import json
import logging
from typing import Optional, List

import httpx
from dotenv import load_dotenv

from ai.models import UserRecord

logger = logging.getLogger(__name__)

# ==============================================================================
# ENVIRONMENT CONFIGURATION
# ==============================================================================

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

# ==============================================================================
# PERSISTENT HTTP CLIENT
# ==============================================================================
#
# Creating a new HTTP client for every AI request is slow because:
#   1. TCP handshake takes ~50-100ms
#   2. TLS negotiation adds another ~50-100ms
#   3. HTTP/2 connection setup adds overhead
#
# By reusing a single persistent client, we skip connection setup
# for subsequent requests, saving ~100-200ms per request.

_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get or create a persistent HTTP client with connection pooling.

    The client is created lazily on first use and reused for all
    subsequent AI API calls.

    Configuration:
        - timeout: 60s total, 10s for connection
        - max_keepalive_connections: 5
        - max_connections: 10
        - http2: Enabled for better multiplexing

    Returns:
        httpx.AsyncClient: Configured async HTTP client
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            http2=True,
        )
    return _http_client


async def close_http_client() -> None:
    """
    Close the persistent HTTP client gracefully.

    Should be called during application shutdown to release resources
    and close open connections.
    """
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ==============================================================================
# CHAT COMPLETION
# ==============================================================================


async def chat_completion(user_input: str, system_prompt: Optional[str] = None) -> str:
    """
    Send a request to the Ollama API for chat completion.

    Args:
        user_input: User's message
        system_prompt: Optional system prompt for context

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
        "temperature": 0.0,  # Deterministic responses for caching
        "top_p": 0.95,
    }

    client = get_http_client()
    response = await client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    return data["choices"][0]["message"]["content"]


# ==============================================================================
# AI RANKING (Optional Feature)
# ==============================================================================


async def rank_users_ai(query: str, users: List[UserRecord]) -> List[int]:
    """
    Rank users by relevance using AI (optional, slower).

    This function uses the LLM to rank search results by relevance
    to the original query. It's optional and can be enabled via
    the enable_ranking parameter in search endpoints.

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
        start_idx = ranking_json.find('[')
        end_idx = ranking_json.rfind(']')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            ranking_json = ranking_json[start_idx:end_idx + 1]

        ranked = json.loads(ranking_json)
        if isinstance(ranked, list):
            return [int(x) for x in ranked if isinstance(x, (int, str)) and str(x).isdigit()]

        return [u.id for u in users]

    except Exception as exc:
        logger.error(f"Ranking error: {exc}")
        return [u.id for u in users]
