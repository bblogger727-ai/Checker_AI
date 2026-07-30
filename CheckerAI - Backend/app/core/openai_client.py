"""
OpenAI Client

Initializes the OpenAI client using environment variables.
Deferred validation: the ValueError is only raised when the client
is actually *used*, not at import time — so the server starts even
if the key is absent (catalog, health, etc. still work fine).
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Lazy-initialised client – validated at first use
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client, OPENAI_API_KEY
    if _client is not None:
        return _client
    # Re-read in case it was injected after import
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY not found in environment variables. "
            "Please create a .env file with your API key."
        )
    _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


class _LazyClient:
    """Proxy that forwards attribute access to the real OpenAI client."""
    def __getattr__(self, name):
        return getattr(_get_client(), name)


# Drop-in replacement: existing code does `client.chat.completions.create(...)` etc.
client = _LazyClient()
