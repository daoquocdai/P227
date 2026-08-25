"""Manual Gemini connectivity smoke test; this file is not collected by pytest."""

import os

from dotenv import load_dotenv
from google import genai


def main() -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set")
    model = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")
    response = genai.Client(api_key=api_key).models.generate_content(
        model=model,
        contents="Chỉ trả lời chính xác: GEMINI_OK",
    )
    if (response.text or "").strip() != "GEMINI_OK":
        raise SystemExit(f"Unexpected Gemini response: {response.text!r}")
    print("GEMINI_OK")


if __name__ == "__main__":
    main()
