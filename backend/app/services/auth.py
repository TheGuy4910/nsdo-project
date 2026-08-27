"""
Authentication service for NSDO — Phase 6.

Pure functions only: password hashing and JWT creation/verification.
No FastAPI, no SQLAlchemy, no database dependency. Fully testable
without infrastructure, matching the pattern of analytics.py and
seed_runtime.py.

Decision B: JWT_SECRET_KEY comes from the environment. If absent,
a development fallback is used with a loud WARNING at startup.
The fallback is intentionally weak and labelled; it must never be
used in production.

Packages required (already in requirements.txt):
  passlib[bcrypt]==1.7.4
  python-jose[cryptography]==3.3.0

These are not importable in the sandbox (PyPI blocked). Tests that
need them use the same try/except ImportError guard as TestSeedRuntime.
"""

from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("nsdo.auth")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEV_FALLBACK_SECRET = "INSECURE-DEV-ONLY-DO-NOT-USE-IN-PRODUCTION"
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours — reasonable for a working session

def get_secret_key() -> str:
    """
    Return the JWT secret key from the environment.

    If JWT_SECRET_KEY is not set, returns a clearly-labelled development
    fallback and emits a WARNING. The app continues — it does not refuse
    to start — so the sandbox and local-without-Docker path work.
    """
    key = os.environ.get("JWT_SECRET_KEY", "")
    if not key:
        logger.warning(
            "JWT_SECRET_KEY environment variable is not set. "
            "Using an insecure development fallback. "
            "THIS MUST NEVER BE USED IN PRODUCTION."
        )
        return _DEV_FALLBACK_SECRET
    return key


# ---------------------------------------------------------------------------
# Password hashing  (passlib/bcrypt)
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """
    Hash a plaintext password using bcrypt via passlib.

    Returns a bcrypt hash string suitable for storage in `users.password_hash`.
    """
    from passlib.context import CryptContext
    _ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return _ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a stored bcrypt hash.

    Returns True if the password matches, False otherwise.
    Never raises on a bad password — always returns False.
    """
    from passlib.context import CryptContext
    _ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    try:
        return _ctx.verify(plain, hashed)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT tokens  (python-jose)
# ---------------------------------------------------------------------------

def create_access_token(
    username: str,
    role: str,
    expires_minutes: int = _ACCESS_TOKEN_EXPIRE_MINUTES,
    secret_key: Optional[str] = None,
) -> str:
    """
    Create a signed JWT access token.

    Claims:
      sub   — username
      role  — 'admin' | 'viewer'
      exp   — expiry timestamp (UTC)

    secret_key: if None, get_secret_key() is called. Pass explicitly in tests.
    """
    from jose import jwt
    key = secret_key if secret_key is not None else get_secret_key()
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  username,
        "role": role,
        "exp":  now + timedelta(minutes=expires_minutes),
        "iat":  now,
    }
    return jwt.encode(payload, key, algorithm=_ALGORITHM)


def decode_access_token(
    token: str,
    secret_key: Optional[str] = None,
) -> dict:
    """
    Decode and verify a JWT access token.

    Returns the full payload dict on success.
    Raises jose.JWTError (subclasses: ExpiredSignatureError, JWTClaimsError)
    on any validation failure.

    The caller is responsible for catching JWTError and converting to
    an appropriate HTTP 401 response.
    """
    from jose import jwt
    key = secret_key if secret_key is not None else get_secret_key()
    return jwt.decode(token, key, algorithms=[_ALGORITHM])


def extract_username(token: str, secret_key: Optional[str] = None) -> Optional[str]:
    """
    Decode a token and return the subject (username), or None on failure.

    Convenience wrapper for use in FastAPI dependencies where a missing or
    invalid token should produce a 401, not an unhandled exception.
    """
    try:
        payload = decode_access_token(token, secret_key)
        return payload.get("sub")
    except Exception:
        return None


def extract_role(token: str, secret_key: Optional[str] = None) -> Optional[str]:
    """
    Decode a token and return the role, or None on failure.
    """
    try:
        payload = decode_access_token(token, secret_key)
        return payload.get("role")
    except Exception:
        return None
