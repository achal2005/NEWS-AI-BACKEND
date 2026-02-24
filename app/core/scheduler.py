import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.api.news import refresh_news_from_api

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_news_refresh():
    """Background task to refresh news every 6 hours."""
    logger.info("Starting scheduled news refresh...")
    db: Session = SessionLocal()
    try:
        categories = ["technology", "science", "business", "health", "sports", "entertainment", "general"]
        count = await refresh_news_from_api(categories, db)
        logger.info(f"Scheduled refresh complete. Fetched {count} new articles.")
    except Exception as e:
        logger.error(f"Scheduled refresh failed: {e}")
    finally:
        db.close()

def start_scheduler():
    """Start the background scheduler — refreshes news every 6 hours + once at startup."""
    # Recurring: every 6 hours
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
    scheduler.start()
    logger.info("Background scheduler started (News refresh every 6 hours + startup)")
