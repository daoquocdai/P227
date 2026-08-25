from google import genai

from src.config import get_settings


def get_llm() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)
