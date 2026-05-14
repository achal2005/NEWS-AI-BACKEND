"""
RSS Feed Aggregator Service — unlimited free news from major outlets.

No API key required. Parses RSS/Atom feeds from Reuters, BBC, NPR,
The Guardian, Al Jazeera, TechCrunch, Wired, Ars Technica, and more.

FIX 9: Improved per-feed failure handling with detailed logging.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from email.utils import parsedate_to_datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)


# ── RSS Feed Directory ──────────────────────────────────────────────────
# Each entry: (feed_url, default_category)
RSS_FEEDS: List[tuple[str, str]] = [
    # ─── General / World ───
    ("https://feeds.bbci.co.uk/news/rss.xml", "General"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "General"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "General"),
    ("https://feeds.npr.org/1001/rss.xml", "General"),
    ("https://feeds.reuters.com/reuters/topNews", "General"),
    ("https://www.theguardian.com/world/rss", "General"),
    ("http://rss.cnn.com/rss/edition.rss", "General"),
    ("https://abcnews.go.com/abcnews/topstories", "General"),

    # ─── Technology ───
    ("https://feeds.feedburner.com/TechCrunch/", "Technology"),
    ("https://www.wired.com/feed/rss", "Technology"),
    ("https://feeds.arstechnica.com/arstechnica/index", "Technology"),
    ("https://www.theverge.com/rss/index.xml", "Technology"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "Technology"),
    ("https://www.zdnet.com/news/rss.xml", "Technology"),
    ("https://www.cnet.com/rss/news/", "Technology"),

    # ─── Science ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "Science"),
    ("https://www.newscientist.com/section/news/feed/", "Science"),
    ("https://www.theguardian.com/science/rss", "Science"),
    ("https://www.sciencedaily.com/rss/all.xml", "Science"),
    ("https://phys.org/rss-feed/", "Science"),

    # ─── Business ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "Business"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "Business"),
    ("https://www.theguardian.com/business/rss", "Business"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "Business"),
    ("https://feeds.reuters.com/reuters/businessNews", "Business"),
    ("https://fortune.com/feed/", "Business"),

    # ─── Health ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "Health"),
    ("https://feeds.bbci.co.uk/news/health/rss.xml", "Health"),
    ("https://www.theguardian.com/lifeandstyle/health-and-wellbeing/rss", "Health"),
    ("https://www.webmd.com/xml/rss/rss.xml", "Health"),
    ("https://feeds.npr.org/103537970/rss.xml", "Health"),
    ("https://www.statnews.com/feed/", "Health"),

    # ─── Sports ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml", "Sports"),
    ("https://feeds.bbci.co.uk/sport/rss.xml", "Sports"),
    ("https://www.espn.com/espn/rss/news", "Sports"),
    ("https://www.theguardian.com/sport/rss", "Sports"),
    ("https://feeds.reuters.com/reuters/sportsNews", "Sports"),
    ("https://www.cbssports.com/rss/headlines/", "Sports"),

    # ─── Entertainment ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml", "Entertainment"),
    ("https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", "Entertainment"),
    ("https://www.theguardian.com/culture/rss", "Entertainment"),
    ("https://ew.com/feed/", "Entertainment"),
    ("https://deadline.com/feed/", "Entertainment"),

    # ─── Politics ───
    ("https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "Politics"),
    ("https://feeds.bbci.co.uk/news/politics/rss.xml", "Politics"),
    ("https://www.politico.com/rss/politicopicks.xml", "Politics"),
    ("https://www.theguardian.com/politics/rss", "Politics"),
]


class RSSAggregatorService:
    """Fetches and normalises articles from many RSS feeds."""

    def __init__(self, feeds: Optional[List[tuple[str, str]]] = None):
        self.feeds = feeds or RSS_FEEDS

    # ── public API ──────────────────────────────────────────────────────

    async def fetch_all(
        self,
        categories: Optional[List[str]] = None,
        max_per_feed: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        Fetch articles from every feed (optionally filtered by category).

        FIX 9: Handles per-feed failures gracefully and logs a summary.
        Returns a list of article dicts in the same shape as NewsAPIService.
        """
        selected_feeds = self.feeds
        if categories:
            cats_lower = {c.lower() for c in categories}
            selected_feeds = [
                (url, cat) for url, cat in self.feeds
                if cat.lower() in cats_lower
            ]

        semaphore = asyncio.Semaphore(5)  # Reduced from 10 to limit peak memory on Render free tier

        async def sem_fetch(url, default_cat, max_items):
            async with semaphore:
                return await self._fetch_feed(url, default_cat, max_items)

        tasks = [
            sem_fetch(url, default_cat, max_per_feed)
            for url, default_cat in selected_feeds
        ]
        # FIX 9: return_exceptions=True (already was, but now we handle them)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: List[Dict[str, Any]] = []
        success_count = 0
        fail_count = 0
        total_feeds = len(selected_feeds)

        for i, r in enumerate(results):
            feed_url = selected_feeds[i][0] if i < len(selected_feeds) else "unknown"
            if isinstance(r, Exception):
                # FIX 9: Log warning with feed URL and exception, skip this feed
                fail_count += 1
                logger.warning(
                    f"RSS feed failed: {feed_url} — {type(r).__name__}: {r}"
                )
            elif isinstance(r, list):
                success_count += 1
                articles.extend(r)
            else:
                fail_count += 1
                logger.warning(f"RSS feed returned unexpected result type from {feed_url}: {type(r)}")

        # FIX 9: Summary log
        logger.info(
            f"RSS fetch complete: {success_count}/{total_feeds} feeds, "
            f"{len(articles)} articles"
        )

        return articles

    async def fetch_by_category(
        self, category: str, max_articles: int = 30
    ) -> List[Dict[str, Any]]:
        """Convenience: fetch a single category."""
        return await self.fetch_all(
            categories=[category], max_per_feed=max_articles
        )

    # ── internals ───────────────────────────────────────────────────────

    async def _fetch_feed(
        self, url: str, default_category: str, max_items: int
    ) -> List[Dict[str, Any]]:
        """Download and parse a single feed."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0
            ) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "NewsAggregator/1.0 (educational project)"
                })

                if resp.status_code != 200:
                    logger.warning(f"Feed {url} returned {resp.status_code}")
                    return []

                # FIX 7: Offload synchronous feedparser to thread pool
                loop = asyncio.get_running_loop()
                raw_text = resp.text
                feed = await loop.run_in_executor(None, feedparser.parse, raw_text)
                del raw_text  # Free the raw HTTP response text immediately
                
                items: List[Dict[str, Any]] = []

                for entry in feed.entries[:max_items]:
                    article = self._transform_entry(entry, default_category, url)
                    if article and article.get("title") and article.get("content"):
                        items.append(article)

                del feed  # Free feedparser DOM tree to reduce peak memory
                logger.info(f"Fetched {len(items)} articles from {url}")
                return items

        except Exception as exc:
            logger.warning(f"Error fetching feed {url}: {exc}")
            return []

    @staticmethod
    def _transform_entry(
        entry: Any, default_category: str, feed_url: str
    ) -> Dict[str, Any]:
        """Normalise a feedparser entry into our article dict format."""

        title = entry.get("title", "").strip()
        if not title:
            return {}

        # Content: prefer full content, fall back to summary/description
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        if not content:
            content = entry.get("summary", "") or entry.get("description", "")

        # Strip very short content (likely just a teaser link)
        if len(content) < 20:
            return {}

        # Published date
        published_at = None
        for date_field in ("published_parsed", "updated_parsed"):
            parsed = entry.get(date_field)
            if parsed:
                try:
                    published_at = datetime(
                        parsed[0], parsed[1], parsed[2],
                        parsed[3], parsed[4], parsed[5]
                    ).isoformat()
                except Exception:
                    pass
                break

        if not published_at:
            raw = entry.get("published") or entry.get("updated")
            if raw:
                try:
                    published_at = parsedate_to_datetime(raw).isoformat()
                except Exception:
                    published_at = datetime.now(timezone.utc).isoformat()
            else:
                published_at = datetime.now(timezone.utc).isoformat()

        # Source
        link = entry.get("link", "")
        source_name = entry.get("source", {}).get("title", "")
        if not source_name:
            # Derive from URL
            try:
                from urllib.parse import urlparse
                source_name = urlparse(link or feed_url).netloc.replace("www.", "").split(".")[0].title()
            except Exception:
                source_name = "RSS"

        # Image
        image_url = None
        if hasattr(entry, "media_content") and entry.media_content:
            image_url = entry.media_content[0].get("url")
        elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image_url = entry.media_thumbnail[0].get("url")
        # Check enclosures
        if not image_url and hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image"):
                    image_url = enc.get("href") or enc.get("url")
                    break

        # Category — always use the default (feed-level) category so articles
        # map cleanly to the 8 UI categories. RSS tags are too unpredictable
        # (e.g. "Gear", "Virtual Currency", "Volcanoes").
        category = default_category

        return {
            "title": title,
            "content": content,
            "description": content[:300] if content else "",
            "source_url": link,
            "source_name": source_name,
            "image_url": image_url,
            "published_at": published_at,
            "author": entry.get("author"),
            "category": category,
        }


# Singleton
rss_aggregator_service = RSSAggregatorService()
