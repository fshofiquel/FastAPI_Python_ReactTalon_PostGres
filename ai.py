import os
from dotenv import load_dotenv
import httpx

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

if not all([OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL]):
    raise RuntimeError("Missing one or more Ollama environment variables")


async def chat_completion(user_input: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_input},
        ],
    }

    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=headers, json=payload)

        # Optional: keep debug until confirmed working
        print("STATUS CODE:", response.status_code)
        print("RESPONSE TEXT:", response.text)

        response.raise_for_status()
        data = response.json()

    # Depending on the model response structure:
    return data["choices"][0]["message"]["content"]

