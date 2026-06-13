import os
import logging
from typing import Awaitable, Callable, Optional, TypeVar

import anthropic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger(__name__)

# Ordered fallback chains per provider. Every LLM call tries these models in order,
# moving to the next one on capacity errors (429 rate limit / RESOURCE_EXHAUSTED,
# overloaded, transient 5xx). First entry is the preferred model.
PROVIDER_MODELS = {
    "claude": [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
    ],
    "gemini": [
        # Flash-first: pro-class thinking models can't emit a full HTML page inside the
        # 300s timeout (observed: render ReadTimeouts on gemini-3.1-pro-preview), and
        # every validated page so far came from 2.5-flash.
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
    ],
}

# Hard caps on any single LLM HTTP request. Without one, a wedged API call hangs the
# whole pipeline indefinitely (observed: an extraction call stuck for 50+ minutes).
GEMINI_TIMEOUT_MS = 300_000

# Explicit timeout for Anthropic requests. Doubles as the opt-out of the SDK's
# "streaming is required for operations that may take longer than 10 minutes" guard:
# with the default timeout, non-streaming calls whose max_tokens projects past 10
# minutes are refused client-side; an explicit timeout disables that check while
# still hard-capping a wedged request.
ANTHROPIC_TIMEOUT_S = 300.0


def anthropic_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        timeout=ANTHROPIC_TIMEOUT_S,
    )

T = TypeVar("T")

# 429: rate limit / RESOURCE_EXHAUSTED; 529: Anthropic overloaded; the rest are
# transient capacity/availability failures worth trying on a different model.
_CAPACITY_STATUS_CODES = {408, 429, 500, 502, 503, 529}


def _is_capacity_error(e: Exception) -> bool:
    if isinstance(e, anthropic.APIStatusError):
        return e.status_code in _CAPACITY_STATUS_CODES
    if isinstance(e, anthropic.APIConnectionError):  # includes timeouts
        return True
    if isinstance(e, genai_errors.APIError):
        return e.code in _CAPACITY_STATUS_CODES
    return False


# Extra wrap-around attempts after a full pass over the chain: the fallback index is
# taken modulo the chain length, so the last model's fallback is the first one (whose
# transient capacity error may have cleared by then).
EXTRA_WRAP_ATTEMPTS = 1


async def call_with_fallback(provider: str, call: Callable[[str], Awaitable[T]]) -> T:
    """Run `call(model)` against the provider's model chain.

    On a capacity error the next model in PROVIDER_MODELS[provider] is tried, wrapping
    modulo the chain length (the last model falls back to the first) for up to
    EXTRA_WRAP_ATTEMPTS additional tries; any other error (bad request, auth, schema)
    propagates immediately. If every attempt is exhausted, the last capacity error is raised.
    """
    models = PROVIDER_MODELS[provider]
    attempts = len(models) + EXTRA_WRAP_ATTEMPTS
    last_error: Optional[Exception] = None
    for i in range(attempts):
        model = models[i % len(models)]
        try:
            result = await call(model)
            if i > 0:
                logger.info("%s: succeeded on fallback model %s (attempt %d)", provider, model, i + 1)
            return result
        except Exception as e:
            if not _is_capacity_error(e):
                raise
            last_error = e
            if i + 1 < attempts:
                logger.warning(
                    "%s model %s unavailable (%s); falling back to %s",
                    provider, model, e, models[(i + 1) % len(models)],
                )
            else:
                logger.error("%s: all %d attempts exhausted; last error: %s", provider, attempts, e)
    raise last_error


def gemini_client() -> genai.Client:
    return genai.Client(
        api_key=os.getenv("GOOGLE_API_KEY"),
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )
