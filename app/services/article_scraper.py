"""
Utility to scrape full article content from source URLs.
NewsAPI free tier truncates content to ~200 chars.
This fetches the actual page and extracts the article body.
"""
import httpx
import logging
import re
from bs4 import BeautifulSoup
from typing import Optional

logger = logging.getLogger(__name__)

# Tags that typically contain article body text
ARTICLE_TAGS = ["article", "main", "[role='main']"]
PARAGRAPH_MIN_LENGTH = 40  # Ignore very short paragraphs (nav items, etc.)


async def scrape_article_content(url: Optional[str], fallback_content: str = "") -> str:
    """
    Fetch full article text from a URL.
    Falls back to `fallback_content` if scraping fails.
    
    Returns the longer of: scraped text vs fallback_content.
    """
    if not url:
        return fallback_content

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove scripts, styles, nav, footer, aside, header
        for tag in soup(["script", "style", "nav", "footer", "aside",
                         "header", "form", "iframe", "noscript"]):
            tag.decompose()

        # Strategy 1: Find <article> or <main> tag
        article_text = ""
        for selector in ARTICLE_TAGS:
            container = soup.select_one(selector)
            if container:
                paragraphs = container.find_all("p")
                article_text = "\n\n".join(
                    p.get_text(strip=True)
                    for p in paragraphs
                    if len(p.get_text(strip=True)) >= PARAGRAPH_MIN_LENGTH
                )
                if len(article_text) > 200:
                    break

        # Strategy 2: Fallback to all <p> tags on the page
        if len(article_text) < 200:
            all_paragraphs = soup.find_all("p")
            article_text = "\n\n".join(
                p.get_text(strip=True)
                for p in all_paragraphs
                if len(p.get_text(strip=True)) >= PARAGRAPH_MIN_LENGTH
            )

        # Clean up whitespace
        article_text = re.sub(r'\n{3,}', '\n\n', article_text).strip()

        # Only use scraped version if it's meaningfully longer
        if len(article_text) > len(fallback_content) * 1.5:
            logger.info(
                f"Scraped {len(article_text)} chars from {url} "
                f"(vs {len(fallback_content)} chars from DB)"
            )
            return article_text[:10000]  # Cap at 10K chars for Gemini
        else:
            return fallback_content

    except Exception as e:
        logger.warning(f"Failed to scrape {url}: {e}")
        return fallback_content
