from datetime import timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db import get_db, User, TasteProfile
from app.core.security import create_access_token, get_current_user_id
from app.core.config import get_settings
from app.services import google_oauth_service
from app.schemas import UserResponse, Token

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
async def get_google_auth_url():
    """
    Get Google OAuth authorization URL.
    
    Returns URL to redirect user to Google login.
    """
    auth_url = google_oauth_service.get_authorization_url()
    return {"auth_url": auth_url}


@router.post("/google/callback", response_model=Token)
async def google_callback(
    request: GoogleAuthRequest,
    db: Session = Depends(get_db)
):
    """
    Handle Google OAuth callback.
    
    Exchanges authorization code for user info and creates/returns JWT.
    """
    try:
        # Authenticate with Google
        google_user = await google_oauth_service.authenticate(request.code)
        
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
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "profile_complete": user.profile_complete,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google authentication failed: {str(e)}"
        )


@router.post("/complete-profile", response_model=UserResponse)
async def complete_profile(
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
    if profile_data.age and profile_data.age < 13:
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
        taste_profile = TasteProfile(
            user_id=user.id,
            preferred_categories=profile_data.preferred_categories,
            summary_mode=summary_mode,
            reading_level=5 if not profile_data.age else min(10, max(1, profile_data.age // 10 + 1)),
            topic_weights={}
        )
        db.add(taste_profile)
    else:
        taste_profile.preferred_categories = profile_data.preferred_categories
        taste_profile.summary_mode = summary_mode
        if profile_data.age:
            taste_profile.reading_level = min(10, max(1, profile_data.age // 10 + 1))
    
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
    Logout user (client should clear token).
    
    For server-side session invalidation, implement token blacklist.
    """
    return {"message": "Logged out successfully"}
