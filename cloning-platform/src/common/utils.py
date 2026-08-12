"""
utils.py — Retry decorator, name sanitizer, ARN builder, and helpers.
"""
from __future__ import annotations

import functools
import re
import time
from typing import Any, Callable, TypeVar

from .exceptions import RetryExhaustedError
from .logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Retry Decorator
# ---------------------------------------------------------------------------

def retry(
    max_attempts: int = 3,
    delay_seconds: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Exponential-backoff retry decorator.

    Args:
        max_attempts: Total number of attempts (including first try).
        delay_seconds: Initial delay between retries in seconds.
        backoff: Multiplier applied to delay after each failure.
        exceptions: Exception types that trigger a retry.

    Returns:
        Decorated function with retry logic.

    Raises:
        RetryExhaustedError: When all attempts are exhausted.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = delay_seconds
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        "Retry %d/%d for %s: %s — retrying in %.1fs",
                        attempt, max_attempts, func.__name__, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= backoff
            raise RetryExhaustedError(
                f"All {max_attempts} attempts exhausted for {func.__name__}: {last_exc}"
            ) from last_exc
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# Name Sanitizer
# ---------------------------------------------------------------------------

def sanitize_name(raw: str, max_length: int = 40) -> str:
    """
    Convert any string to a valid AWS resource name.

    Rules:
        - Lowercase
        - Only letters, numbers, hyphens
        - No leading/trailing hyphens
        - Maximum max_length characters

    Args:
        raw: The raw input string.
        max_length: Maximum output length.

    Returns:
        Sanitized name safe for use in AWS resource names.
    """
    name = raw.lower()
    name = re.sub(r"[^a-z0-9]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:max_length]


# ---------------------------------------------------------------------------
# ARN Builder
# ---------------------------------------------------------------------------

def build_lambda_arn(region: str, account_id: str, function_name: str) -> str:
    """Build a Lambda function ARN from components."""
    return f"arn:aws:lambda:{region}:{account_id}:function:{function_name}"


def build_role_arn(account_id: str, role_name: str) -> str:
    """Build an IAM role ARN from components."""
    return f"arn:aws:iam::{account_id}:role/{role_name}"


def build_api_url(api_id: str, region: str, stage: str) -> str:
    """Build an API Gateway REST endpoint URL."""
    return f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"


def build_apigw_source_arn(region: str, account_id: str, api_id: str) -> str:
    """Build the source ARN for API Gateway Lambda permission."""
    return f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/*"


# ---------------------------------------------------------------------------
# Environment Variable Merger
# ---------------------------------------------------------------------------

def merge_env_vars(
    base_vars: dict[str, str],
    overrides: dict[str, str],
) -> dict[str, str]:
    """
    Merge base Lambda environment variables with new environment-specific overrides.

    Args:
        base_vars: Existing environment variables from source Lambda.
        overrides: New key-value pairs to inject (will overwrite base_vars keys).

    Returns:
        Merged dict safe for use as Lambda environment variables.
    """
    merged = {k: str(v) for k, v in base_vars.items()}
    merged.update({k: str(v) for k, v in overrides.items()})
    return merged
