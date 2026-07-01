"""Multi-key, multi-model Gemini wrapper for the free tier.

Free tier quotas are tight and per (key, model):
    gemini-3.5-flash:      5 RPM, 250K TPM,  20 RPD
    gemini-3.1-flash-lite: 15 RPM, 250K TPM, 500 RPD

The ticker only needs one generation a day, so exhaustion should be rare -
but this tries every configured key on the higher-quality model first, then
falls back to every key on the higher-limit model, so one bad key or a
transient quota hit doesn't take down ticker generation entirely.
"""

from google import genai
from google.genai import errors

MODELS_BY_PREFERENCE = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]


def generate_text(api_keys: list[str], prompt: str) -> str:
    if not api_keys:
        raise RuntimeError("No Gemini API keys configured")

    last_error: Exception | None = None
    for model in MODELS_BY_PREFERENCE:
        for api_key in api_keys:
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(model=model, contents=prompt)
            except errors.APIError as exc:
                last_error = exc
                continue
            if response.text:
                return response.text
            last_error = RuntimeError(f"{model} returned an empty response")

    raise RuntimeError("All Gemini keys/models exhausted") from last_error
