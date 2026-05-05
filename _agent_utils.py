"""_agent_utils.py — OpenAI client singleton, HTTP client injection, and reply text post-processing."""

import re

import httpx
import openai

from config import OPENAI_API_KEY

# Reused for every call — no need to recreate on each request.
client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

# Shared HTTP client injected by main.py lifespan.
_http_client: httpx.AsyncClient | None = None


_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalise_menu_numbers(text: str) -> str:
    """Normalise list markers to Western numerals before sending a reply."""
    text = text.translate(_ARABIC_INDIC)
    lines = text.split("\n")
    counter = 1
    result = []
    for line in lines:
        if re.match(r"^[A-Za-z][.)]\s", line):
            line = re.sub(r"^[A-Za-z]([.)]\s)", str(counter) + r"\1", line)
            counter += 1
        else:
            if not re.match(r"^\d+[.)]\s", line):
                counter = 1
        result.append(line)
    return "\n".join(result)


def set_http_client(http_client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = http_client


def get_http_client() -> httpx.AsyncClient | None:
    return _http_client
