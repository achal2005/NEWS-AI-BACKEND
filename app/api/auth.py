import os
from datetime import timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db import get_db, User, TasteProfile
from app.core.security import create_access_token, get_current_user_id
from app.core.config import get_settings
from app.services import google_oauth_service
from app.schemas import UserResponse, Token
from app.core.limiter import limiter

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class GoogleAuthRequest(BaseModel):
    """Request body for Google OAuth callback."""
    code: str


class CompleteProfileRequest(BaseModel):
    """Request to complete user profile after OAuth."""
    display_name: str = Field(..., min_length=2, max_length=50)
    age: Optional[int] = Field(None, ge=5, le=120)
    preferred_categories: List[str] = Field(default_factory=list)
    summary_mode: Optional[str] = Field(default="pro", pattern="^(kid|pro)$")


class AuthUrlResponse(BaseModel):
    """Response containing OAuth URL."""
    auth_url: str


# ============ Google OAuth Endpoints ============

@router.get("/google", response_model=AuthUrlResponse)
@limiter.limit("10/minute")
async def get_google_auth_url(request: Request):
    """
    Get Google OAuth authorization URL.
    
    Returns URL to redirect user to Google login.
    """
    auth_url = google_oauth_service.get_authorization_url()
    if not auth_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Login is not configured (missing GOOGLE_CLIENT_ID)"
        )
    return {"auth_url": auth_url}


@router.post("/google/callback")
@limiter.limit("5/minute")
async def google_callback(
    request: Request,
    auth_request: GoogleAuthRequest,
    db: Session = Depends(get_db)
):
    """
    Handle Google OAuth callback.
    
    Exchanges authorization code for user info and creates/returns JWT.
    FIX 3: Sets a single HttpOnly cookie named `auth_token`.
    """
    try:
        # Authenticate with Google
        google_user = await google_oauth_service.authenticate(auth_request.code)
        
        # Check if user exists
        user = db.query(User).filter(User.email == google_user.email).first()
        
        if not user:
            # Create new user from Google account
            user = User(
                email=google_user.email,
                display_name=google_user.name,
                google_id=google_user.id,
                avatar_url=google_user.picture,
                password_hash="",  # No password for OAuth users
                profile_complete=False,  # Needs to complete profile
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Update Google info if needed
            if not user.google_id:
                user.google_id = google_user.id
            if google_user.picture and not user.avatar_url:
                user.avatar_url = google_user.picture
            db.commit()
        
        # Create access token
        access_token = create_access_token(data={"sub": str(user.id)})
        
        # FIX 3+R1: HttpOnly cookie is the SOLE auth transport.
        # JWT is NOT returned in JSON body to prevent XSS token theft.
        response = JSONResponse(content={
            "profile_complete": user.profile_complete,
        })
        # Cross-origin (Vercel frontend ↔ Render backend) requires
        # SameSite=none + Secure=true. Lax only works same-origin.
        response.set_cookie(
            key="auth_token",
            value=access_token,
            httponly=True,
            secure=True,                # Always true (SameSite=none requires it)
            samesite="none",            # Required for cross-origin cookies
            max_age=86400,
            path="/",
        )
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google authentication failed: {str(e)}"
        )


@router.post("/complete-profile", response_model=UserResponse)
@limiter.limit("5/minute")
async def complete_profile(
    request: Request,
    profile_data: CompleteProfileRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Complete user profile after OAuth registration.
    
    Collects:
    - Display name
    - Age (for Kid/Pro mode)
    - Preferred news categories
    - Summary mode preference
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Determine summary mode based on age
    summary_mode = profile_data.summary_mode or "pro"
    if profile_data.age is not None and profile_data.age < 13:
        summary_mode = "kid"  # Auto-set kid mode for young users
    
    # Update user profile
    user.display_name = profile_data.display_name
    user.age = profile_data.age
    user.profile_complete = True
    
    # Create or update taste profile
    taste_profile = db.query(TasteProfile).filter(
        TasteProfile.user_id == user.id
    ).first()
    
    if not taste_profile:
        # Calculate reading level safely
        reading_level = 5
        if profile_data.age is not None:
            reading_level = min(10, max(1, profile_data.age // 10 + 1))
        
        taste_profile = TasteProfile(
            user_id=user.id,
            preferred_categories=profile_data.preferred_categories,
            summary_mode=summary_mode,
            reading_level=reading_level,
            topic_weights={}
        )
        db.add(taste_profile)
    else:
        taste_profile.preferred_categories = profile_data.preferred_categories
        taste_profile.summary_mode = summary_mode
        if profile_data.age is not None:
            age_value: int = profile_data.age
            taste_profile.reading_level = min(10, max(1, int(age_value) // 10 + 1))
    
    db.commit()
    db.refresh(user)
    
    return user


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get current authenticated user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.post("/logout")
async def logout():
    """
    Logout user.
    
    FIX 3: Clears the single HttpOnly auth cookie.
    """
    response = JSONResponse(content={"message": "Logged out successfully"})
    # Must match the same domain/path/samesite/secure attributes used in set_cookie
    response.delete_cookie(
        key="auth_token",
        path="/",
        samesite="none",
        secure=True,
    )
    return response


@router.get("/dev-login")
@limiter.limit("5/hour")
async def dev_login(request: Request, db: Session = Depends(get_db)):
    """
    Mock login for testing — only available when:
    1. debug=True
    2. ENVIRONMENT=development
    3. DEV_LOGIN_ENABLED=true (explicit opt-in, R9)
    """
    is_development = os.environ.get("ENVIRONMENT", "development").lower() == "development"
    dev_login_enabled = os.environ.get("DEV_LOGIN_ENABLED", "false").lower() == "true"
    if not settings.debug or not is_development or not dev_login_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    user = db.query(User).first()
    if not user:
        user = User(
            email="test@example.com",
            display_name="Dev User",
            profile_complete=True,
            age=25
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        taste = TasteProfile(
            user_id=user.id,
            preferred_categories=["Technology"],
            summary_mode="pro",
            reading_level=5,
            topic_weights={}
        )
        db.add(taste)
        db.commit()

    token = create_access_token(data={"sub": str(user.id)})

    # R1: Dev login also only sets HttpOnly cookie — no JWT in JSON body
    response = JSONResponse(content={"profile_complete": True})
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=False,  # Dev mode — localhost is HTTP
        samesite="lax",  # Same-origin OK for localhost
        max_age=86400,
        path="/",
    )
    return response
