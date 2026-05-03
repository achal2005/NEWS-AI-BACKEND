from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.config import get_settings

settings = get_settings()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token authentication (Bearer header — used by Swagger UI)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


def _extract_token(request: Request, bearer_token: Optional[str] = None) -> Optional[str]:
    """
    FIX 3: Extract token from HttpOnly cookie first, then fall back to Bearer header.
    This keeps Swagger /docs working while the frontend uses cookies exclusively.
    """
    # 1. Try HttpOnly cookie (primary — set by backend on login)
    cookie_token = request.cookies.get("auth_token")
    if cookie_token:
        return cookie_token

    # 2. Fall back to Bearer header (for Swagger UI / external API consumers)
    if bearer_token:
        return bearer_token

    return None


async def get_current_user_id(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
) -> str:
    """
    Extract user ID from JWT token.
    FIX 3: Reads from HttpOnly cookie first, then Bearer header.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = _extract_token(request, bearer_token)
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    return user_id


async def get_optional_user_id(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[str]:
    """
    Extract user ID from JWT token, or return None if not authenticated.
    FIX 3: Reads from HttpOnly cookie first, then Bearer header.
    """
    token = _extract_token(request, bearer_token)
    if not token:
        return None
    
    payload = decode_access_token(token)
    if payload is None:
        return None
    
    return payload.get("sub")
