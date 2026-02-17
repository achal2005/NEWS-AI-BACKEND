import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.api.news import refresh_news_from_api

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_news_refresh():
    """Background task to refresh news daily."""
    logger.info("⏳ Starting scheduled daily news refresh...")
    db: Session = SessionLocal()
    try:
        # fetch from all main categories
        categories = ["technology", "science", "business", "health", "sports", "entertainment", "general"]
        count = await refresh_news_from_api(categories, db)
        logger.info(f"✅ Scheduled refresh complete. Fetched {count} new articles.")
    except Exception as e:
        logger.error(f"❌ Scheduled refresh failed: {e}")
    finally:
        db.close()

def start_scheduler():
    """Start the background scheduler."""
    # Run every day at midnight (UTC)
    # or whenever the user prefers. Let's do 00:00 UTC.
    scheduler.add_job(
        scheduled_news_refresh,
        CronTrigger(hour=0, minute=0),
        id="daily_news_refresh",
        replace_existing=True
    )
    
    # Also add a job to run on startup/restart (optional, maybe run once after 1 min uptime)
    # scheduler.add_job(scheduled_news_refresh, 'date', run_date=datetime.now() + timedelta(minutes=1))

    scheduler.start()
    logger.info("🕒 Background scheduler started (Daily refresh at 00:00 UTC)")
