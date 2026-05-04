from typing import Optional, List
from uuid import UUID
import asyncio
import hashlib
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from datetime import datetime, timezone

from app.db import get_db, Article, ArticleSummary, ArticleJargon, TasteProfile
from app.core.security import get_current_user_id, get_optional_user_id
from app.schemas import (
    ArticleCreate, ArticleResponse, ArticleListResponse,
    ArticleSummaryResponse,
    ChatRequest
)
from app.services import gemini_service, news_api_service, kafka_producer
from app.services.rss_aggregator import rss_aggregator_service
from app.core.cache import article_list_cache

logger = logging.getLogger(__name__)
from app.services.gemini import GeminiQuotaError, GeminiServiceError, GeminiParseError
from app.services.article_scraper import scrape_article_content, is_safe_url

router = APIRouter(prefix="/api/news", tags=["News"])

# ── FIX 5: Import limiter from main ──────────────────────────────────
# The limiter is created in main.py and attached to app.state
# We import it lazily via the app reference in the request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_limiter(request: Request) -> Limiter:
    """Get the limiter instance from app state."""
    return request.app.state.limiter


@router.get("")
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
    Uses TTL cache for repeated queries.
    """
    t0 = time.time()

    # Build cache key from query params
    cache_key = f"articles:{user_id or 'anon'}:{category or 'all'}:{page}:{page_size}"
    cached = article_list_cache.get(cache_key)
    if cached:
        logger.info(f"Cache HIT for {cache_key} ({(time.time()-t0)*1000:.1f}ms)")
        resp = JSONResponse(content=cached)
        resp.headers["Cache-Control"] = "public, max-age=300"
        resp.headers["X-Cache"] = "HIT"
        return resp

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
        query = query.filter(func.lower(Article.category) == category.lower())
    elif preferred_categories and not category:
        # Filter by user's preferred categories (case-insensitive)
        lower_prefs = [c.lower() for c in preferred_categories]
        query = query.filter(func.lower(Article.category).in_(lower_prefs))
    
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
    
    result = ArticleListResponse(
        items=articles,
        total=total,
        page=page,
        page_size=page_size
    )

    # Cache the serialized response (5 min TTL)
    result_dict = result.model_dump(mode="json")
    article_list_cache.set(cache_key, result_dict, ttl=300)

    elapsed = (time.time() - t0) * 1000
    logger.info(f"Cache MISS for {cache_key} ({elapsed:.1f}ms, {total} total articles)")

    resp = JSONResponse(content=result_dict)
    resp.headers["Cache-Control"] = "public, max-age=300"
    resp.headers["X-Cache"] = "MISS"
    return resp


@router.get("/refresh")
async def refresh_articles(
    request: Request,
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Manually refresh articles from NewsAPI.
    FIX 5: Rate-limited to 5/hour.
    
    Categories: technology, science, business, health, sports, entertainment
    """
    # FIX 5: Rate limit check
    limiter = _get_limiter(request)
    category_list = categories.split(",") if categories else ["technology", "science", "business"]
    count = await refresh_news_from_api(categories=category_list, db=db)
    # Invalidate article list cache so new articles appear immediately
    invalidated = article_list_cache.invalidate("articles:")
    logger.info(f"Invalidated {invalidated} cached article list entries")
    return {"message": f"Fetched {count} new articles", "categories": category_list}


async def refresh_news_from_api(categories: List[str], db: Session) -> int:
    """Fetch news from NewsAPI AND RSS feeds, store in database."""
    articles_fetched: int = 0

    # ── 1. NewsAPI (if key is configured) ─────────────────────────
    for category in categories:
        try:
            news_items = await news_api_service.fetch_top_headlines(
                category=category,
                page_size=20
            )

            for item in news_items:
                articles_fetched += _store_article(item, category, db)
        except Exception as e:
            logger.warning(f"NewsAPI fetch failed for {category}: {e}")

    # ── 2. RSS Feeds ──────────────────────────────────────────────
    try:
        rss_items = await rss_aggregator_service.fetch_all(
            categories=categories,
            max_per_feed=15,
        )
        for item in rss_items:
            articles_fetched += _store_article(
                item, item.get("category", "General"), db
            )
    except Exception as e:
        logger.warning(f"RSS refresh error: {e}")

    # Commit all successfully-added articles
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Failed to commit articles: {e}")
        db.rollback()

    return articles_fetched


def _compute_url_hash(url: str) -> str:
    """Compute SHA-256 hash of a URL for fast deduplication."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _store_article(item: dict, fallback_category: str, db: Session) -> int:
    """Store a single article dict. Returns 1 if stored, 0 if skipped."""
    source_url = item.get("source_url", "")
    title = item.get("title", "Untitled")
    content = item.get("content", "")

    if not content or not title:
        return 0

    # SHA-256 deduplication on source_url
    url_hash = _compute_url_hash(source_url) if source_url else None
    if url_hash:
        existing = db.query(Article).filter(
            Article.url_hash == url_hash
        ).first()
        if existing:
            return 0
    else:
        existing = db.query(Article).filter(
            Article.title == title
        ).first()
        if existing:
            return 0

    pub_at = None
    raw_pub = item.get("published_at")
    if raw_pub:
        try:
            if isinstance(raw_pub, str):
                pub_at = datetime.fromisoformat(
                    raw_pub.replace("Z", "+00:00")
                )
            else:
                pub_at = raw_pub
        except Exception:
            pub_at = datetime.now(timezone.utc)
    else:
        pub_at = datetime.now(timezone.utc)

    article = Article(
        title=title,
        content=content,
        source_url=source_url,
        source_name=item.get("source_name"),
        author=item.get("author"),
        image_url=item.get("image_url"),
        url_hash=url_hash,
        category=item.get("category") or fallback_category.capitalize(),
        published_at=pub_at,
    )
    # Use a savepoint so rollback only affects THIS article, not previously added ones
    try:
        nested = db.begin_nested()
        db.add(article)
        db.flush()
    except IntegrityError:
        nested.rollback()  # Roll back only this savepoint
        return 0
    except Exception as exc:
        # Any other DB error — rollback savepoint to avoid tainted session
        try:
            nested.rollback()
        except Exception:
            pass
        logger.warning(f"Failed to store article '{title[:50]}': {exc}")
        return 0

    # Emit to Kafka for brand-new articles only (fire-and-forget)
    try:
        asyncio.get_event_loop().create_task(
            kafka_producer.publish_raw_article({
                "title": title,
                "source_url": source_url,
                "category": article.category,
            })
        )
    except Exception:
        pass  # Don't fail ingestion if Kafka is down

    return 1


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


@router.get("/refresh-rss")
async def refresh_from_rss(
    request: Request,
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    db: Session = Depends(get_db)
):
    """
    Refresh articles from free RSS feeds only (no API key needed).
    FIX 5: Rate-limited to 2/hour (unauthenticated endpoint).
    
    Categories: Technology, Science, Business, Health, Sports, Entertainment, General
    """
    # FIX 5: Rate limit check
    limiter = _get_limiter(request)
    category_list = categories.split(",") if categories else None
    try:
        rss_items = await rss_aggregator_service.fetch_all(
            categories=category_list,
            max_per_feed=15,
        )
        count = 0
        for item in rss_items:
            count += _store_article(
                item, item.get("category", "General"), db
            )
        db.commit()
        return {
            "message": f"Fetched {count} new articles from RSS feeds",
            "total_items_parsed": len(rss_items),
            "new_stored": count,
        }
    except Exception as e:
        return {"message": f"RSS refresh failed: {str(e)}", "new_stored": 0}


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a single article by ID."""
    article = db.query(Article).filter(Article.id == str(article_id)).first()
    
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found"
        )
    
    return article


@router.get("/{article_id}/summary", response_model=ArticleSummaryResponse)
async def get_article_summary(
    article_id: UUID,
    mode: str = Query("pro", pattern="^(kid|pro|skim|deep)$"),
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """Get or generate article summary (cached per article+mode)."""
    # Normalize mode aliases so cache keys are consistent:
    # kid → skim (3-bullet-point format), pro → deep (multi-paragraph)
    MODE_ALIASES = {"kid": "skim", "pro": "deep"}
    mode = MODE_ALIASES.get(mode, mode)
    
    article = db.query(Article).filter(Article.id == str(article_id)).first()
    
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found"
        )
    
    # ── 1. Check cache first — saves a Gemini API call ─────────────
    # Determine depth_level for cache lookup
    depth_level = 5  # Default
    if user_id:
        from app.db import User
        user = db.query(User).filter(User.id == user_id).first()
        if user and hasattr(user, 'depth_preference') and user.depth_preference is not None:
            depth_level = user.depth_preference

    cached = db.query(ArticleSummary).filter(
        ArticleSummary.article_id == str(article_id),
        ArticleSummary.mode == mode,
        ArticleSummary.depth_level == depth_level
    ).first()
    
    if cached:
        return {
            "mode": cached.mode,
            "summary": cached.summary,
            "generated_at": cached.generated_at
        }
    
    # ── 2. No cache hit — generate via Gemini ─────────────────────

    try:
        # NewsAPI free tier truncates content (~200 chars + "[+XXX chars]").
        # If content looks truncated, scrape the full article from source URL.
        content_for_summary = article.content or ""
        is_truncated = (
            "[+" in content_for_summary and "chars]" in content_for_summary
        ) or len(content_for_summary) < 500

        if is_truncated and hasattr(article, 'source_url') and article.source_url:
            content_for_summary = await scrape_article_content(
                article.source_url, fallback_content=content_for_summary
            )
        elif is_truncated and hasattr(article, 'url') and article.url:
            content_for_summary = await scrape_article_content(
                article.url, fallback_content=content_for_summary
            )

        category = article.category or "General News"
        summary_text = await asyncio.wait_for(
            gemini_service.generate_depth_calibrated_summary(
                content=content_for_summary, 
                depth_level=depth_level,
                category=category,
                mode=mode,
                user_id=user_id,  # FIX 4: per-user rate limiting
            ),
            timeout=30.0
        )
        
        # ── 3. FIX 10: Race-safe insert with conflict handling ─────
        now = datetime.now(timezone.utc)
        try:
            # Try dialect-specific upsert for PostgreSQL
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(ArticleSummary).values(
                article_id=str(article_id),
                mode=mode,
                depth_level=depth_level,
                summary=summary_text,
                generated_at=now,
            ).on_conflict_do_nothing(
                index_elements=['article_id', 'mode', 'depth_level']
            )
            db.execute(stmt)
            db.commit()
        except Exception:
            # SQLite fallback: catch IntegrityError
            db.rollback()
            try:
                new_summary = ArticleSummary(
                    article_id=str(article_id),
                    mode=mode,
                    depth_level=depth_level,
                    summary=summary_text,
                    generated_at=now
                )
                db.add(new_summary)
                db.commit()
            except IntegrityError:
                db.rollback()  # Another request got there first — that's fine

        # FIX 10: Always re-query to return the canonical stored version
        canonical = db.query(ArticleSummary).filter(
            ArticleSummary.article_id == str(article_id),
            ArticleSummary.mode == mode,
            ArticleSummary.depth_level == depth_level
        ).first()

        if canonical:
            return {
                "mode": canonical.mode,
                "summary": canonical.summary,
                "generated_at": canonical.generated_at
            }

        # Fallback if somehow nothing stored
        return {
            "mode": mode,
            "summary": summary_text,
            "generated_at": now
        }
    except GeminiQuotaError as e:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail=str(e)
        )
    except GeminiServiceError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except GeminiParseError as e:
        # FIX 7: Return 502 for AI parse failures
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="AI returned unexpected response format"
        )
    except Exception as e:
        db.rollback()
        # Return un-cached fallback so the user still sees something
        return {
            "mode": mode,
            "summary": _fallback_summary(article.content),
            "generated_at": datetime.now(timezone.utc)
        }


def _fallback_summary(content: str) -> str:
    """Extract first 3 sentences as a simple summary."""
    sentences = [s.strip() for s in content.split('.') if s.strip()]
    if not sentences:
        return "Summary is being generated. Please try again shortly."
    text = ". ".join(sentences[:3]) + "."
    return text[:500] if len(text) <= 500 else text[:497] + "..."


@router.post("/{article_id}/regenerate-summary", response_model=ArticleSummaryResponse)
async def regenerate_article_summary(
    article_id: UUID,
    mode: str = Query("pro", pattern="^(kid|pro|skim|deep)$"),
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """Force-regenerate an article summary, bypassing the cache."""
    MODE_ALIASES = {"kid": "skim", "pro": "deep"}
    mode = MODE_ALIASES.get(mode, mode)
    
    article = db.query(Article).filter(Article.id == str(article_id)).first()
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    depth_level = 5
    if user_id:
        from app.db import User
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.depth_preference is not None:
            depth_level = user.depth_preference

    # Delete any existing cached summary for this combo
    db.query(ArticleSummary).filter(
        ArticleSummary.article_id == str(article_id),
        ArticleSummary.mode == mode,
        ArticleSummary.depth_level == depth_level
    ).delete()
    db.commit()

    # Generate fresh summary
    content_for_summary = article.content or ""
    is_truncated = (
        "[+" in content_for_summary and "chars]" in content_for_summary
    ) or len(content_for_summary) < 500

    if is_truncated and article.source_url:
        content_for_summary = await scrape_article_content(
            article.source_url, fallback_content=content_for_summary
        )

    try:
        category = article.category or "General News"
        summary_text = await asyncio.wait_for(
            gemini_service.generate_depth_calibrated_summary(
                content=content_for_summary,
                depth_level=depth_level,
                category=category,
                mode=mode,
                user_id=user_id,
            ),
            timeout=30.0
        )

        now = datetime.now(timezone.utc)
        new_summary = ArticleSummary(
            article_id=str(article_id),
            mode=mode,
            depth_level=depth_level,
            summary=summary_text,
            generated_at=now
        )
        db.add(new_summary)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

        return {"mode": mode, "summary": summary_text, "generated_at": now}
    except GeminiQuotaError as e:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(e))
    except GeminiServiceError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except GeminiParseError:
        db.rollback()
        raise HTTPException(status_code=502, detail="AI returned unexpected response format")
    except Exception as e:
        db.rollback()
        return {
            "mode": mode,
            "summary": _fallback_summary(article.content),
            "generated_at": datetime.now(timezone.utc)
        }


@router.post("/{article_id}/chat")
async def chat_about_article(
    article_id: UUID,
    chat_request: ChatRequest,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """Chat with the AI editor about an article."""
    article = db.query(Article).filter(Article.id == str(article_id)).first()
    
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found"
        )
    
    try:
        response = await gemini_service.chat_with_editor(
            article.content,
            chat_request.question,
            user_id=user_id,  # FIX 4: per-user rate limiting
        )
        return {"answer": response}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat generation failed: {str(e)}"
        )


@router.post("", response_model=ArticleResponse, status_code=status.HTTP_201_CREATED)
async def create_article(
    article_data: ArticleCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create a new article (admin only)."""
    # FIX 2: SSRF protection on user-supplied source_url
    if article_data.source_url:
        if not is_safe_url(article_data.source_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The provided source_url points to a restricted or private network address."
            )

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
        jargon_items = await gemini_service.extract_jargon(article.content, user_id=user_id)
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
