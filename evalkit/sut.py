"""Layer 1 - the system under test.

One LLM call against the front desk prompt + FAQ. No tools, no multi-turn: the
personas are single-shot enquiries. Retries cover transport failures only - a
refusal or an unhelpful answer is a *result*, not an error.
"""
from __future__ import annotations

import asyncio
import random
import time

import anthropic

from . import config as C
from .schema import FatalRunError, Scenario, SutResult

# Wrong key, wrong model, malformed request: every unit would fail the same way.
FATAL = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.BadRequestError,
)
RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)


def _request_kwargs(scenario: Scenario, user_message: str) -> dict:
    kwargs = {
        "model": scenario.model,
        "max_tokens": scenario.max_tokens,
        # Stable prefix (prompt + FAQ) is identical across every unit of a
        # scenario, so it caches; the persona message goes after it.
        "system": [{"type": "text", "text": scenario.system,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_message}],
    }
    if scenario.thinking:
        kwargs["thinking"] = {"type": scenario.thinking}
    return kwargs


def _backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after
    return C.BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, 0.5)


async def call_sut(
    client: anthropic.AsyncAnthropic,
    scenario: Scenario,
    user_message: str,
    *,
    max_attempts: int = C.MAX_ATTEMPTS,
) -> SutResult:
    kwargs = _request_kwargs(scenario, user_message)
    last_error: dict[str, str] | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = await client.messages.create(**kwargs)
        except FATAL as e:
            raise FatalRunError(f"{type(e).__name__}: {e}") from e
        except RETRYABLE as e:
            last_error = {"type": type(e).__name__, "message": str(e), "retryable": "true"}
            if attempt == max_attempts:
                break
            retry_after = None
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except (TypeError, ValueError):
                    retry_after = None
            await asyncio.sleep(_backoff(attempt, retry_after))
            continue
        except anthropic.APIStatusError as e:
            last_error = {"type": type(e).__name__, "message": str(e),
                          "status_code": str(e.status_code), "retryable": str(e.status_code >= 500)}
            if e.status_code < 500 or attempt == max_attempts:
                break
            await asyncio.sleep(_backoff(attempt, None))
            continue

        latency_ms = int((time.perf_counter() - started) * 1000)
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = response.usage
        return SutResult(
            ok=True,
            # A refusal or an empty completion is recorded as "no reply" so the
            # checks come back no_evidence instead of failing on an empty string.
            text=text if text.strip() else None,
            stop_reason=response.stop_reason,
            truncated=response.stop_reason == "max_tokens",
            usage={
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            },
            request_id=response._request_id,
            latency_ms=latency_ms,
            attempts=attempt,
            model=response.model,
        )

    return SutResult(ok=False, attempts=max_attempts, model=scenario.model, error=last_error)


async def preflight(client: anthropic.AsyncAnthropic, scenario: Scenario) -> None:
    """Cheapest possible proof that the key and model are usable, before 24 units."""
    try:
        await client.messages.create(
            model=scenario.model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
            **({"thinking": {"type": scenario.thinking}} if scenario.thinking == "disabled" else {}),
        )
    except FATAL as e:
        raise FatalRunError(f"preflight failed - {type(e).__name__}: {e}") from e
