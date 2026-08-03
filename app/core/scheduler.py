import logging
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_news_refresh():
    """Background task to refresh news every 6 hours.

    Creates a fresh DB session, runs the refresh, and ensures
    the session is always closed + rolled back on error.
    """
    logger.info("Starting scheduled news refresh...")

    # Import here to avoid circular imports at module load time
    from app.db.session import SessionLocal
    from app.api.news import refresh_news_from_api

    # Create session synchronously (it's cheap and thread-safe)
    db = SessionLocal()
    try:
        categories = ["technology", "science", "business", "health", "sports", "entertainment", "general"]
        count = await refresh_news_from_api(categories, db)
        db.expire_all()  # Free ORM identity map to reduce memory
        logger.info(f"Scheduled refresh complete. Fetched {count} new articles.")
    except Exception as e:
        logger.error(f"Scheduled refresh failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


async def reconcile_missing_summaries():
    """R12: Find articles without any summaries and queue them for AI processing.
    
    This handles cases where Kafka was down during ingestion (fire-and-forget)
    and ensures all articles eventually get summarized.
    """
    logger.info("Starting summary reconciliation...")

    from app.db.session import SessionLocal
    from app.db.models import Article, ArticleSummary
    from app.services.gemini import gemini_service, GeminiQuotaError, GeminiServiceError, GeminiParseError
    from sqlalchemy import func

    db = SessionLocal()
    try:
        # Find articles that have no summaries at all (limit to recent 50 to avoid overload)
        subq = db.query(ArticleSummary.article_id).distinct().subquery()
        orphaned = (
            db.query(Article)
            .outerjoin(subq, Article.id == subq.c.article_id)
            .filter(subq.c.article_id == None)
            .order_by(Article.ingested_at.desc())
            .limit(10)  # Reduced from 20 to limit peak memory during Gemini calls
            .all()
        )

        if not orphaned:
            logger.info("Reconciliation: all articles have summaries.")
            return

        logger.info(f"Reconciliation: found {len(orphaned)} articles without summaries.")

        generated = 0
        for article in orphaned:
            try:
                summary_text = await gemini_service.generate_summary(
                    content=article.content, mode="pro"
                )
                new_summary = ArticleSummary(
                    article_id=article.id,
                    mode="deep",
                    depth_level=5,
                    summary=summary_text,
                    generated_at=datetime.now(timezone.utc),
                )
                db.add(new_summary)
                db.commit()
                generated += 1
            except (GeminiQuotaError, GeminiServiceError):
                logger.warning("Reconciliation: Gemini quota/error — stopping early.")
                break
            except Exception as e:
                logger.warning(f"Reconciliation: failed for article {article.id}: {e}")
                db.rollback()
                continue

        logger.info(f"Reconciliation complete: generated {generated} summaries.")
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


async def refresh_leaderboard_cache():
    """R15: Populate LeaderboardCache from live data every 15 minutes."""
    logger.info("Refreshing leaderboard cache...")

    from app.db.session import SessionLocal
    from app.db.models import User, PointsLedger, LeaderboardCache, QuizAttempt
    from app.core.time_utils import get_current_week_start
    from sqlalchemy import func

    db = SessionLocal()
    try:
        week_start = get_current_week_start()

        # Weekly points per user — single query instead of N+1
        weekly_data = (
            db.query(
                PointsLedger.user_id,
                func.sum(PointsLedger.points).label("weekly_points"),
                func.count(
                    func.nullif(PointsLedger.action_type != "read_article", True)
                ).label("articles_read"),
            )
            .filter(PointsLedger.earned_at >= week_start)
            .group_by(PointsLedger.user_id)
            .all()
        )

        # Pre-fetch reading times for all relevant users in ONE query
        user_ids = [row.user_id for row in weekly_data]
        user_reading_times = {}
        if user_ids:
            users = (
                db.query(User.id, User.total_reading_time_seconds)
                .filter(User.id.in_(user_ids))
                .all()
            )
            user_reading_times = {u.id: u.total_reading_time_seconds or 0 for u in users}

        # Clear old cache for this week
        db.query(LeaderboardCache).filter(
            LeaderboardCache.week_start == week_start.date()
        ).delete()

        # Rebuild
        entries = sorted(weekly_data, key=lambda r: r.weekly_points or 0, reverse=True)
        for rank, row in enumerate(entries, 1):
            cache_entry = LeaderboardCache(
                user_id=row.user_id,
                week_start=week_start.date(),
                weekly_points=row.weekly_points or 0,
                rank=rank,
                articles_read=row.articles_read or 0,
                reading_time_minutes=user_reading_times.get(row.user_id, 0) // 60,
            )
            db.add(cache_entry)

        db.commit()
        # Expire all objects in the session to free ORM identity map memory
        db.expire_all()
        logger.info(f"Leaderboard cache refreshed: {len(entries)} entries.")
    except Exception as e:
        logger.error(f"Leaderboard cache refresh failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def start_scheduler():
    """Start the background scheduler with all recurring jobs."""
    # Recurring: every 6 hours — news refresh
    scheduler.add_job(
        scheduled_news_refresh,
        IntervalTrigger(hours=6),
        id="news_refresh_6h",
        replace_existing=True,
    )
    # Startup: run once 60 seconds after boot
    scheduler.add_job(
        scheduled_news_refresh,
        DateTrigger(run_date=datetime.now() + timedelta(seconds=60)),
        id="news_refresh_startup",
        replace_existing=True,
    )

    # R12: Reconcile missing summaries every 2 hours.
    # Disabled by default: on the free Gemini tier this background pre-summarizing
    # burns the whole daily quota, so users hit "AI quota reached" on real requests.
    # Summaries are generated on demand (news.get_article_summary) instead.
    from app.core.config import get_settings
    presummarize = get_settings().presummarize_enabled
    if presummarize:
        scheduler.add_job(
            reconcile_missing_summaries,
            IntervalTrigger(hours=2),
            id="reconcile_summaries_2h",
            replace_existing=True,
        )

    # R15: Refresh leaderboard cache every 15 minutes
    scheduler.add_job(
        refresh_leaderboard_cache,
        IntervalTrigger(minutes=15),
        id="leaderboard_cache_15m",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Background scheduler started ("
        "News refresh every 6h + startup, "
        f"Summary reconciliation every 2h: {'ON' if presummarize else 'OFF (on-demand only)'}, "
        "Leaderboard cache every 15m)"
    )
