"""
API key authentication and subscription tier enforcement.
Supports: free, pro, premium tiers.
OFF by default (MONETIZATION_ENABLED=false). Flip to true when ready to charge.
"""

import hashlib
import json
import os
import time
import secrets
import logging
from typing import Optional, Dict
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

KEYS_FILE = os.path.join(os.path.dirname(__file__), "..", "signal_data", "api_keys.json")

RATE_LIMITS = {
    "free": {"requests_per_minute": 10, "requests_per_day": 100},
    "pro": {"requests_per_minute": 60, "requests_per_day": 5000},
    "premium": {"requests_per_minute": 120, "requests_per_day": 20000},
    "admin": {"requests_per_minute": 999, "requests_per_day": 999999},
}

_rate_tracker: Dict[str, list] = {}


class AuthMiddleware(BaseHTTPMiddleware):
    PUBLIC_PATHS = ["/", "/health", "/api/status", "/docs", "/openapi.json"]
    FREE_PATHS = ["/api/scan"]
    PRO_PATHS = ["/api/analyze/", "/api/signals/recent", "/ws"]
    PREMIUM_PATHS = ["/api/options/"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public — no auth
        if path in self.PUBLIC_PATHS or path.startswith("/static") or path.startswith("/dashboard"):
            return await call_next(request)

        # Monetization off → allow everything
        if not os.getenv("MONETIZATION_ENABLED", "false").lower() == "true":
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required.")

        key_data = validate_api_key(api_key)
        if not key_data:
            raise HTTPException(status_code=403, detail="Invalid or expired API key.")

        tier = key_data.get("tier", "free")

        if any(path.startswith(p) for p in self.PREMIUM_PATHS) and tier not in ("premium", "admin"):
            raise HTTPException(status_code=403, detail="Premium subscription required for options recommendations.")
        if any(path.startswith(p) for p in self.PRO_PATHS) and tier not in ("pro", "premium", "admin"):
            raise HTTPException(status_code=403, detail="Pro subscription required.")

        if not check_rate_limit(api_key, tier):
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")

        request.state.user = key_data
        request.state.tier = tier
        return await call_next(request)


def validate_api_key(api_key: str) -> Optional[Dict]:
    try:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if not os.path.exists(KEYS_FILE):
            return None
        with open(KEYS_FILE, "r") as f:
            keys = json.load(f)
        key_data = keys.get(key_hash)
        if key_data and key_data.get("active", False):
            return key_data
        return None
    except Exception as e:
        logger.error(f"Error validating API key: {e}")
        return None


def check_rate_limit(api_key: str, tier: str) -> bool:
    now = time.time()
    limits = RATE_LIMITS.get(tier, RATE_LIMITS["free"])
    if api_key not in _rate_tracker:
        _rate_tracker[api_key] = []
    _rate_tracker[api_key] = [t for t in _rate_tracker[api_key] if now - t < 60]
    if len(_rate_tracker[api_key]) >= limits["requests_per_minute"]:
        return False
    _rate_tracker[api_key].append(now)
    return True


def create_api_key(email: str, tier: str = "free") -> str:
    api_key = f"ofr_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    keys = {}
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "r") as f:
            keys = json.load(f)

    keys[key_hash] = {
        "tier": tier,
        "email": email,
        "created": time.time(),
        "active": True,
    }

    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)

    logger.info(f"Created {tier} API key for {email}")
    return api_key


def activate_subscription(email: str, tier: str) -> Optional[str]:
    """Called by Stripe webhook when payment succeeds. Upgrades user tier."""
    try:
        if not os.path.exists(KEYS_FILE):
            # New user — create key
            return create_api_key(email, tier)

        with open(KEYS_FILE, "r") as f:
            keys = json.load(f)

        # Find existing key by email and upgrade
        for key_hash, data in keys.items():
            if data.get("email") == email:
                data["tier"] = tier
                data["upgraded_at"] = time.time()
                with open(KEYS_FILE, "w") as f:
                    json.dump(keys, f, indent=2)
                logger.info(f"Upgraded {email} to {tier}")
                return None  # Existing key upgraded, no new key needed

        # Email not found — create new key
        return create_api_key(email, tier)

    except Exception as e:
        logger.error(f"Error activating subscription for {email}: {e}")
        return None
