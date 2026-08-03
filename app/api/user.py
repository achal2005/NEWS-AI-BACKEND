from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db, User, TasteProfile
from app.core.security import get_current_user_id
from app.core.cache import article_list_cache
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
    
    # Merge depth_preference from User model into the response
    user = db.query(User).filter(User.id == user_id).first()
    response = TasteProfileResponse.model_validate(profile)
    if user and user.depth_preference is not None:
        response.depth_preference = user.depth_preference
    
    return response


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
    
    # Track whether the feed-affecting fields changed so we can invalidate cache
    categories_changed = (
        profile_data.preferred_categories is not None
        and profile_data.preferred_categories != profile.preferred_categories
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

    # Update the user model for fields that live on User, not TasteProfile
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        if profile_data.display_name is not None:
            user.display_name = profile_data.display_name.strip()
        if profile_data.depth_preference is not None:
            user.depth_preference = profile_data.depth_preference

    db.commit()
    db.refresh(profile)

    # Preferences drive the personalized feed, which is cached per-user for 5 min.
    # Invalidate this user's cached pages so a category change is reflected at once.
    if categories_changed:
        article_list_cache.invalidate(f"articles:{user_id}:")
    
    # Merge depth_preference from User model into the response
    response = TasteProfileResponse.model_validate(profile)
    if user and user.depth_preference is not None:
        response.depth_preference = user.depth_preference
    
    return response
