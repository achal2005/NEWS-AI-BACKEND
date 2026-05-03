"""
Utility to scrape full article content from source URLs.
NewsAPI free tier truncates content to ~200 chars.
This fetches the actual page and extracts the article body.

FIX 2: Added SSRF protection — rejects private/loopback IPs, validates DNS,
       enforces 512KB response limit and 10s timeout.
"""
import httpx
import logging
import re
import socket
import ipaddress
from bs4 import BeautifulSoup
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Tags that typically contain article body text
ARTICLE_TAGS = ["article", "main", "[role='main']"]
PARAGRAPH_MIN_LENGTH = 40  # Ignore very short paragraphs (nav items, etc.)
MAX_RESPONSE_BYTES = 512 * 1024  # 512KB response size limit
REQUEST_TIMEOUT = 10.0  # seconds


# ── SSRF Protection ─────────────────────────────────────────────────
def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, or link-local."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        return True  # If we can't parse it, reject it


def is_safe_url(url: str) -> bool:
    """
    Validate that a URL is safe to fetch (not targeting internal resources).

    Rejects:
    - Non-http/https schemes
    - Hostnames resolving to private/loopback/link-local IPs
    - Known dangerous hostnames (localhost, metadata endpoints)

    Returns True if the URL is safe to fetch.
    """
    try:
        parsed = urlparse(url)

        # 1. Scheme check
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"SSRF blocked: non-http(s) scheme '{parsed.scheme}' in {url}")
            return False

        hostname = parsed.hostname
        if not hostname:
            logger.warning(f"SSRF blocked: no hostname in {url}")
            return False

        # 2. Hostname blocklist
        blocked_hostnames = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        if hostname.lower() in blocked_hostnames:
            logger.warning(f"SSRF blocked: blocked hostname '{hostname}'")
            return False

        # 3. DNS resolution check — resolve hostname and validate all IPs
        try:
            addrinfos = socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            logger.warning(f"SSRF blocked: DNS resolution failed for '{hostname}'")
            return False

        for family, _type, _proto, _canonname, sockaddr in addrinfos:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                logger.warning(
                    f"SSRF blocked: '{hostname}' resolved to private IP {ip_str}"
                )
                return False

        return True

    except Exception as e:
        logger.warning(f"SSRF check failed for '{url}': {e}")
        return False


async def scrape_article_content(url: Optional[str], fallback_content: str = "") -> str:
    """
    Fetch full article text from a URL.
    Falls back to `fallback_content` if scraping fails.
    
    Returns the longer of: scraped text vs fallback_content.
    """
    if not url:
        return fallback_content

    # FIX 2: SSRF protection — validate URL before fetching
    if not is_safe_url(url):
        logger.warning(f"Scrape blocked by SSRF filter: {url}")
        return fallback_content

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        ) as client:
            # Stream response to enforce size limit
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Check Content-Length header first
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    logger.warning(f"Response too large ({content_length} bytes) from {url}")
                    return fallback_content

                # Read with size limit
                chunks = []
                total_size = 0
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    total_size += len(chunk)
                    if total_size > MAX_RESPONSE_BYTES:
                        logger.warning(f"Response exceeded {MAX_RESPONSE_BYTES} bytes from {url}")
                        return fallback_content
                    chunks.append(chunk)

                html_content = b"".join(chunks).decode("utf-8", errors="replace")

        soup = BeautifulSoup(html_content, "html.parser")

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
