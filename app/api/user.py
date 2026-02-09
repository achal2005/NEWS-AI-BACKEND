from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db, User, TasteProfile
from app.core.security import get_current_user_id
from app.schemas import TasteProfileUpdate, TasteProfileResponse, UserResponse

router = APIRouter(prefix="/api/user", tags=["User"])


@router.get("/profile", response_model=TasteProfileResponse)
async def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get current user's taste profile."""
    profile = db.query(TasteProfile).filter(TasteProfile.user_id == user_id).first()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    
    return profile


@router.put("/profile", response_model=TasteProfileResponse)
async def update_profile(
    profile_data: TasteProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update current user's taste profile."""
    profile = db.query(TasteProfile).filter(TasteProfile.user_id == user_id).first()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    
    # Update only provided fields
    if profile_data.preferred_categories is not None:
        profile.preferred_categories = profile_data.preferred_categories
    if profile_data.summary_mode is not None:
        profile.summary_mode = profile_data.summary_mode
    if profile_data.reading_level is not None:
        profile.reading_level = profile_data.reading_level
    if profile_data.topic_weights is not None:
        profile.topic_weights = profile_data.topic_weights
    
    db.commit()
    db.refresh(profile)
    
    return profile
