from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime

from app.db import get_db, Article, ArticleSummary, ArticleJargon, TasteProfile
from app.core.security import get_current_user_id, get_optional_user_id
from app.schemas import (
    ArticleCreate, ArticleResponse, ArticleListResponse,
    ArticleSummaryResponse
)
from app.services import gemini_service, news_api_service

router = APIRouter(prefix="/api/news", tags=["News"])


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of articles.
    
    If user is authenticated, filters by their preferred categories.
    Fetches live news if database is empty.
    """
    query = db.query(Article)
    
    # Get user's preferred categories if authenticated
    preferred_categories = []
    if user_id:
        taste_profile = db.query(TasteProfile).filter(
            TasteProfile.user_id == user_id
        ).first()
        if taste_profile and taste_profile.preferred_categories:
            preferred_categories = taste_profile.preferred_categories
    
    # Filter by specific category if provided
    if category:
        query = query.filter(Article.category == category)
    elif preferred_categories and not category:
        # Filter by user's preferred categories
        query = query.filter(Article.category.in_(preferred_categories))
    
    total = query.count()
    
    # If no articles in database, try to fetch from NewsAPI
    if total == 0:
        await refresh_news_from_api(
            categories=preferred_categories or ["technology", "science", "business"],
            db=db
        )
        total = query.count()
    
    articles = query.order_by(Article.ingested_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()
    
    return ArticleListResponse(
        items=articles,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/refresh")
async def refresh_articles(
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    db: Session = Depends(get_db)
):
    """
    Manually refresh articles from NewsAPI.
    
    Categories: technology, science, business, health, sports, entertainment
    """
    category_list = categories.split(",") if categories else ["technology", "science", "business"]
    count = await refresh_news_from_api(categories=category_list, db=db)
    return {"message": f"Fetched {count} new articles", "categories": category_list}


async def refresh_news_from_api(categories: List[str], db: Session) -> int:
    """Fetch news from NewsAPI and store in database."""
    articles_fetched = 0
    
    for category in categories:
        news_items = await news_api_service.fetch_top_headlines(
            category=category,
            page_size=20
        )
        
        for item in news_items:
            # Check if article already exists (by source URL)
            existing = db.query(Article).filter(
                Article.source_url == item.get("source_url")
            ).first()
            
            if not existing and item.get("content"):
                article = Article(
                    title=item.get("title", "Untitled"),
                    content=item.get("content", ""),
                    source_url=item.get("source_url", ""),
                    category=item.get("category", category.capitalize()),
                    published_at=datetime.fromisoformat(
                        item.get("published_at", "").replace("Z", "+00:00")
                    ) if item.get("published_at") else datetime.utcnow(),
                )
                db.add(article)
                articles_fetched += 1
    
    db.commit()
    return articles_fetched


@router.get("/categories")
async def get_available_categories():
    """Get list of available news categories."""
    return {
        "categories": [
            {"id": "technology", "name": "Technology", "icon": "💻"},
            {"id": "science", "name": "Science", "icon": "🔬"},
            {"id": "business", "name": "Business", "icon": "💼"},
            {"id": "health", "name": "Health", "icon": "🏥"},
            {"id": "sports", "name": "Sports", "icon": "⚽"},
            {"id": "entertainment", "name": "Entertainment", "icon": "🎬"},
            {"id": "general", "name": "General", "icon": "📰"},
        ]
    }


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a single article by ID."""
    article = db.query(Article).filter(Article.id == article_id).first()
    
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found"
        )
    
    return article


@router.get("/{article_id}/summary", response_model=ArticleSummaryResponse)
async def get_article_summary(
    article_id: UUID,
    mode: str = Query("pro", pattern="^(kid|pro)$"),
    db: Session = Depends(get_db)
):
    """Get or generate article summary."""
    article = db.query(Article).filter(Article.id == article_id).first()
    
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found"
        )
    
    # Check for cached summary
    existing_summary = db.query(ArticleSummary).filter(
        ArticleSummary.article_id == article_id,
        ArticleSummary.mode == mode
    ).first()
    
    if existing_summary:
        return existing_summary
    
    # Generate new summary
    summary_text = await gemini_service.generate_summary(article.content, mode)
    
    # Cache the summary
    new_summary = ArticleSummary(
        article_id=article_id,
        mode=mode,
        summary=summary_text
    )
    db.add(new_summary)
    db.commit()
    db.refresh(new_summary)
    
    return new_summary


@router.post("", response_model=ArticleResponse, status_code=status.HTTP_201_CREATED)
async def create_article(
    article_data: ArticleCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create a new article (admin only)."""
    article = Article(
        title=article_data.title,
        content=article_data.content,
        source_url=article_data.source_url,
        category=article_data.category,
        published_at=article_data.published_at
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    
    # Extract jargon asynchronously
    try:
        jargon_items = await gemini_service.extract_jargon(article.content)
        for item in jargon_items:
            jargon = ArticleJargon(
                article_id=article.id,
                term=item.get("term", ""),
                definition=item.get("definition", ""),
                difficulty=item.get("difficulty", "intermediate")
            )
            db.add(jargon)
        db.commit()
    except Exception:
        pass  # Don't fail if AI extraction fails
    
    db.refresh(article)
    return article
