"""
Authentication endpoints and shared dependencies — Phase 6.

Endpoints:
  POST /api/auth/token     — OAuth2 password flow; returns JWT
  POST /api/auth/register  — create a user (first user → admin; rest → require admin token)
  GET  /api/auth/me        — return current user's username and role

Shared dependency:
  require_admin(token)     — used by all write-route imports to enforce admin-only access

Decision A: first registered user auto-becomes admin; subsequent require an admin token.
Decision B: JWT_SECRET_KEY from env; loud warning + dev fallback if absent.
Decision C: only write operations require authentication; all GET endpoints remain public.

Note on Swagger /docs:
  The OAuth2PasswordBearer scheme declared here enables the
  "Authorize" button in FastAPI's Swagger UI at /docs.
  Users can log in with username+password and Swagger will
  automatically include the Bearer token in subsequent requests.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app import crud, schemas
from app.models.models import User
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Declared here; imported by main.py to pass to FastAPI() so Swagger picks it up.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Return the current user if a valid token is provided, or None.
    Does NOT raise on missing/invalid token — that is the caller's job.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if not username:
            return None
    except Exception:
        return None
    return crud.get_user_by_username(db, username)


def require_admin(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    FastAPI dependency that enforces admin-only access.

    Decision C: only write routes use this. All GET endpoints remain public.

    Raises 401 if no token, 403 if valid token but role != 'admin'.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Obtain a token from POST /api/auth/token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        role: str = payload.get("role", "viewer")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin access required. Your role is '{role}'.",
        )
    # Return the user object so route handlers can log who performed the action
    user = crud.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token references a user that no longer exists.",
        )
    return user


# ---------------------------------------------------------------------------
# POST /api/auth/token
# ---------------------------------------------------------------------------

@router.post("/token", response_model=schemas.Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    OAuth2 password flow. Returns a JWT access token on success.

    Compatible with FastAPI's built-in Swagger UI "Authorize" button:
    enter username + password in /docs, click Authorize, and all
    subsequent Swagger requests will carry the Bearer token.
    """
    user = crud.get_user_by_username(db, form.username)
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(username=user.username, role=user.role)
    return schemas.Token(access_token=token)


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------

@router.post("/register", response_model=schemas.UserRead, status_code=201)
def register(
    payload: schemas.UserCreate,
    current_user=Depends(_get_current_user_optional),
    db: Session = Depends(get_db),
):
    user_count = crud.count_users(db)
    is_bootstrap = (user_count == 0)
    if not payload.username or not payload.username.strip():
        raise HTTPException(status_code=400, detail="Username cannot be empty.")
    if len(payload.username) > 128:
        raise HTTPException(status_code=400, detail="Username must be 128 characters or fewer.")
    if crud.get_user_by_username(db, payload.username.strip()):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' is already taken.")
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not payload.email or not payload.email.strip():
        raise HTTPException(status_code=400, detail="Email is required.")
    if "@" not in payload.email or "." not in payload.email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if db.query(User).filter(User.email == payload.email.strip()).first():
        raise HTTPException(status_code=409, detail=f"Email '{payload.email}' is already registered.")
    role = "admin" if is_bootstrap else "viewer"
    hashed = hash_password(payload.password)
    return crud.create_user(db, payload.username.strip(), hashed, role, email=payload.email.strip())
# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=schemas.UserRead)
def get_me(
    current_user=Depends(_get_current_user_optional),
):
    """
    Return the currently authenticated user's profile.

    Returns 401 if no valid token is provided.
    This is the only GET endpoint that requires authentication,
    because it returns personal account information.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
