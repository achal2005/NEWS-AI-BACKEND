# API module
from app.api.auth import router as auth_router
from app.api.news import router as news_router
from app.api.user import router as user_router
from app.api.gamification import router as gamification_router

__all__ = ["auth_router", "news_router", "user_router", "gamification_router"]
