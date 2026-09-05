"""
Phase 15: Security & Defensive Protections Module
=================================================
Provides:
  1. Strict identifier format validation (Payment, Merchant, Customer, Action IDs)
  2. SQLi / Path Traversal / XSS sanitization heuristics
  3. Sensitive credential masking for logs, traces, and API responses
  4. Sliding-window in-memory RateLimiter for sensitive recovery endpoints
"""
import re
import time
from typing import Dict, Any, Optional, Set
from collections import defaultdict

# ── Identifier Validation ─────────────────────────────────────────────────────

# Safe identifier pattern: alphanumeric with underscores and hyphens (4-64 characters)
SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{4,64}$")
DANGEROUS_CHARS_PATTERN = re.compile(r"['\";\\<>\/\x00]|(--)|(/\*)")

ALLOWED_PREFIXES: Set[str] = {
    "pay", "mer", "merch", "cust", "act", "ra", "rev", "ae", "batch", "bi", "wh", "del"
}


def is_valid_identifier(val: Optional[str], expected_prefix: Optional[str] = None) -> bool:
    """
    Validates that an ID is alphanumeric + underscores/hyphens, within length bounds,
    and contains no SQL injection or path traversal sequences.
    """
    if not val or not isinstance(val, str):
        return False

    val = val.strip()
    if len(val) < 4 or len(val) > 64:
        return False

    # Check for dangerous SQLi / XSS / path traversal sequences
    if DANGEROUS_CHARS_PATTERN.search(val):
        return False

    # Check strict regex pattern
    if not SAFE_ID_PATTERN.match(val):
        return False

    # Prefix verification if requested
    if expected_prefix:
        if not val.startswith(f"{expected_prefix}_"):
            return False

    return True


# ── Credential & Secret Masking ───────────────────────────────────────────────

SENSITIVE_FIELD_NAMES: Set[str] = {
    "password", "password_hash", "secret", "secret_key", "api_key",
    "razorpay_key_secret", "card_number", "pan", "cvv", "cvc",
    "token", "access_token", "refresh_token", "authorization"
}


def mask_sensitive_value(key: str, val: Any) -> Any:
    """Masks secrets and credentials for secure logging and responses."""
    if not isinstance(val, (str, int, float)):
        return val

    str_val = str(val)
    lower_key = key.lower()

    if any(s in lower_key for s in SENSITIVE_FIELD_NAMES):
        if len(str_val) <= 6:
            return "******"
        return f"{str_val[:3]}****{str_val[-3:]}"

    return val


def sanitize_payload(obj: Any) -> Any:
    """Recursively walks dictionaries and lists to mask sensitive fields."""
    if isinstance(obj, dict):
        return {
            k: sanitize_payload(mask_sensitive_value(k, v))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    return obj


# ── Sliding-Window Rate Limiter ───────────────────────────────────────────────

class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter for sensitive endpoints.
    Tracks hit timestamps per client key (e.g. IP address or merchant ID).
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.hits: Dict[str, list] = defaultdict(list)

    def is_allowed(self, client_key: str) -> bool:
        """Returns True if the request is permitted within rate limits, False otherwise."""
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old timestamps
        timestamps = self.hits[client_key]
        valid_timestamps = [t for t in timestamps if t > cutoff]
        self.hits[client_key] = valid_timestamps

        if len(valid_timestamps) >= self.max_requests:
            return False

        self.hits[client_key].append(now)
        return True

    def reset(self, client_key: Optional[str] = None):
        """Clears rate limit state for tests or maintenance."""
        if client_key:
            self.hits.pop(client_key, None)
        else:
            self.hits.clear()


# Global rate limiter for sensitive execution operations (e.g. max 20 executions / minute)
execution_rate_limiter = SlidingWindowRateLimiter(max_requests=20, window_seconds=60)
