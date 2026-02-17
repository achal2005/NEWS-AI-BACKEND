import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.api.news import refresh_news_from_api
from app.db import SessionLocal

async def refresh():
    db = SessionLocal()
    try:
        print("Refreshing NewsAPI (RSS Disabled)...")
        # Refresh default categories
        categories = ["technology", "science", "business", "health", "sports", "entertainment"]
        count = await refresh_news_from_api(categories=categories, db=db)
        print(f"Fetched {count} articles from NewsAPI.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(refresh())
