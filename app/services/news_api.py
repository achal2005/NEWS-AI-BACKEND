import httpx
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import asyncio
from urllib.parse import urlparse

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Domains known to block scraping or require subscriptions
PAYWALL_DOMAINS = {
    "ft.com", "bloomberg.com", "wsj.com", "nytimes.com", 
    "washingtonpost.com", "thetimes.co.uk", "economist.com",
    "businessinsider.com", "barrons.com", "reuters.com"
}

# Keywords that heavily imply the scraped text is just a paywall prompt
PAYWALL_KEYWORDS = [
    "subscribe now", "complete digital access", "unlock this article",
    "subscribe to read", "for unlimited access", "already a subscriber",
    "start your free trial", "to continue reading", "subscription required"
]


class NewsAPIService:
    """Service for fetching news from NewsAPI.org."""
    
    def __init__(self):
        self.api_key = settings.news_api_key
        self.base_url = settings.news_api_base_url
        self._last_fetch: Optional[datetime] = None
        self._cache: List[Dict] = []
        self._cache_duration = timedelta(minutes=30)
    
    async def fetch_top_headlines(
        self,
        category: Optional[str] = None,
        country: str = "us",
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch top headlines from NewsAPI.
        
        Args:
            category: News category (business, technology, science, health, sports, entertainment)
            country: ISO country code
            page_size: Number of articles to fetch (max 100)
            
        Returns:
            List of article dictionaries
        """
        if not self.api_key:
            logger.warning("NEWS_API_KEY not configured, returning empty list")
            print("WARNING: NEWS_API_KEY is missing. Articles will not be fetched.")
            return []
        
        params = {
            "apiKey": self.api_key,
            "country": country,
            "pageSize": min(page_size, 100),
        }
        
        if category:
            params["category"] = category.lower()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/top-headlines",
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"NewsAPI error: {response.text}")
                    return []
                
                data = response.json()
                articles = data.get("articles", [])
                
                # Transform to our format — process in batches of 5 to limit
                # peak memory from concurrent HTTP scraping + BeautifulSoup parsing
                eligible = [a for a in articles if a.get("content") or a.get("description")]
                result: List[Dict[str, Any]] = []
                BATCH_SIZE = 5
                for i in range(0, len(eligible), BATCH_SIZE):
                    batch = eligible[i:i + BATCH_SIZE]
                    batch_results = await asyncio.gather(
                        *(self._transform_article(a) for a in batch)
                    )
                    result.extend(batch_results)
                return result
                
        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return []
    
    async def search_news(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for news articles.
        
        Args:
            query: Search query
            from_date: Start date for search
            to_date: End date for search
            page_size: Number of results
            
        Returns:
            List of matching articles
        """
        if not self.api_key:
            return []
        
        params = {
            "apiKey": self.api_key,
            "q": query,
            "pageSize": min(page_size, 100),
            "sortBy": "publishedAt",
            "language": "en",
        }
        
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/everything",
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"NewsAPI search error: {response.text}")
                    return []
                
                data = response.json()
                articles = data.get("articles", [])
                
                # Batch scraping to limit peak memory
                eligible = [a for a in articles if a.get("content") or a.get("description")]
                result: List[Dict[str, Any]] = []
                BATCH_SIZE = 5
                for i in range(0, len(eligible), BATCH_SIZE):
                    batch = eligible[i:i + BATCH_SIZE]
                    batch_results = await asyncio.gather(
                        *(self._transform_article(a) for a in batch)
                    )
                    result.extend(batch_results)
                return result
                
        except Exception as e:
            logger.error(f"Error searching news: {e}")
            return []
    
    async def fetch_by_categories(
        self,
        categories: List[str],
        articles_per_category: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch articles from multiple categories.
        
        Args:
            categories: List of category names
            articles_per_category: How many articles per category
            
        Returns:
            Combined list of articles from all categories
        """
        all_articles = []
        
        for category in categories:
            articles = await self.fetch_top_headlines(
                category=category,
                page_size=articles_per_category
            )
            all_articles.extend(articles)
        
        return all_articles
    
    async def _scrape_full_article(self, url: str) -> Optional[str]:
        """Attempt to download and extract the text from the source URL."""
        # 1. Check Domain Blacklist
        try:
            domain = urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            
            # Use partial matching for subdomains
            if any(pd in domain for pd in PAYWALL_DOMAINS):
                logger.info(f"Skipping scrape for known paywalled domain: {domain}")
                return None
        except Exception:
            pass

        # 2. Scrape
        try:
            async with httpx.AsyncClient(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}, timeout=10.0) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Remove unwanted elements like scripts, styles, forms, and nav
                    for element in soup(["script", "style", "nav", "header", "footer", "form", "aside", "iframe", "noscript"]):
                        element.extract()
                    
                    # Try to find a main article body container
                    article_body = soup.find('article') or soup.find('main') or soup.body
                    
                    if article_body:
                        # Extract non-empty paragraphs
                        paragraphs = article_body.find_all(['p', 'h2', 'h3'])
                        text_chunks = [p.get_text(separator=' ', strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                        full_text = "\n\n".join(text_chunks)
                        
                        # 3. Check for Paywall Keywords in the scraped text
                        lower_text = full_text.lower()
                        if any(kw in lower_text for kw in PAYWALL_KEYWORDS):
                            logger.info(f"Detected paywall text in scraped content for: {url}")
                            return None
                            
                        if len(full_text) > 500:
                            return full_text
        except Exception as e:
            logger.warning(f"Failed to scrape article {url}: {e}")
            return None
            
    async def _transform_article(self, article: Dict) -> Dict[str, Any]:
        """Transform NewsAPI article to our format and fetch full content."""
        source_name = article.get("source", {}).get("name", "Unknown")
        source_url = article.get("url", "")
        
        # Determine category based on content or source
        description = article.get("description") or ""
        raw_content = article.get("content") or ""
        
        # Fallback content if scraping fails
        raw_fallback = f"{description}\n\n{raw_content}".strip()
        
        # Clean up any HTML tags that NewsAPI might have leaked in the fallback content
        try:
            actual_content = BeautifulSoup(raw_fallback, "html.parser").get_text(separator=' ', strip=True)
        except Exception:
            actual_content = raw_fallback
        
        # Scrape full text if URL exists
        if source_url:
            scraped_text = await self._scrape_full_article(source_url)
            if scraped_text:
                actual_content = scraped_text
                
        category = self._infer_category(actual_content, source_name)
        
        return {
            "title": article.get("title", "Untitled"),
            "content": actual_content,
            "description": description,
            "source_url": source_url,
            "source_name": source_name,
            "image_url": article.get("urlToImage"),
            "published_at": article.get("publishedAt"),
            "author": article.get("author"),
            "category": category,
        }
    
    def _infer_category(self, content: str, source: str) -> str:
        """
        Infer article category using weighted keyword scoring.

        Each category has keywords with weights. The article is scored against
        ALL categories simultaneously and the highest-scoring category wins.
        This prevents over-classification into Technology simply because a
        generic word like "app" or "google" appears in the text.
        """
        text = f"{content} {source}".lower()

        # (keyword, weight)  —  higher weight = stronger category signal
        CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
            "Technology": [
                ("artificial intelligence", 3), ("machine learning", 3),
                ("software engineer", 3), ("open source", 3),
                ("semiconductor", 3), ("cybersecurity", 3), ("blockchain", 3),
                ("programming", 2), ("algorithm", 2), ("startup", 2),
                ("silicon valley", 2), ("data center", 2), ("cloud computing", 2),
                ("quantum computing", 3), ("robotics", 2), ("5g", 2),
                ("coding", 2), ("tech industry", 3), ("saas", 2),
                ("smartphone", 1), ("laptop", 1), ("gadget", 1),
                ("software", 1), ("hardware", 1), ("processor", 2),
                ("gpu", 2), ("api", 2), ("developer", 1),
            ],
            "Science": [
                ("scientific study", 3), ("peer-reviewed", 3), ("research team", 3),
                ("clinical trial", 3), ("laboratory", 2), ("experiment", 2),
                ("nasa", 3), ("space station", 3), ("telescope", 2),
                ("physics", 2), ("chemistry", 2), ("biology", 2),
                ("genome", 3), ("fossil", 2), ("astronomy", 3),
                ("discovery", 1), ("species", 2), ("evolution", 2),
                ("climate change", 2), ("carbon emissions", 2), ("ecosystem", 2),
                ("researcher", 1), ("scientist", 2), ("university study", 2),
            ],
            "Business": [
                ("earnings report", 3), ("quarterly revenue", 3), ("ipo", 3),
                ("merger", 3), ("acquisition", 2), ("ceo", 1),
                ("profit margin", 3), ("market cap", 3), ("shareholder", 2),
                ("venture capital", 3), ("private equity", 3), ("valuation", 2),
                ("supply chain", 2), ("manufacturing", 1), ("retail sales", 2),
                ("e-commerce", 2), ("corporate", 1), ("industry", 1),
                ("revenue", 1), ("profit", 1), ("startup funding", 3),
                ("bankruptcy", 2), ("layoff", 2), ("restructuring", 2),
            ],
            "Finance": [
                ("stock market", 3), ("wall street", 3), ("federal reserve", 3),
                ("interest rate", 3), ("inflation", 2), ("bond market", 3),
                ("treasury", 2), ("forex", 3), ("cryptocurrency", 3),
                ("bitcoin", 3), ("ethereum", 3), ("s&p 500", 3),
                ("dow jones", 3), ("nasdaq", 3), ("hedge fund", 3),
                ("banking", 2), ("central bank", 3), ("monetary policy", 3),
                ("recession", 2), ("gdp", 2), ("economic growth", 2),
                ("investment", 1), ("portfolio", 2), ("dividend", 2),
            ],
            "Politics": [
                ("president", 2), ("congress", 3), ("senate", 3),
                ("white house", 3), ("legislation", 3), ("bipartisan", 3),
                ("democrat", 3), ("republican", 3), ("election", 3),
                ("vote", 1), ("policy", 1), ("supreme court", 3),
                ("governor", 2), ("political party", 3), ("campaign", 2),
                ("immigration", 2), ("executive order", 3), ("impeach", 3),
                ("geopolitical", 2), ("diplomat", 2), ("sanction", 2),
                ("tariff", 2), ("regulation", 1), ("government", 1),
            ],
            "World": [
                ("united nations", 3), ("nato", 3), ("eu ", 2),
                ("european union", 3), ("middle east", 2), ("asia pacific", 2),
                ("international", 1), ("foreign minister", 3), ("embassy", 2),
                ("refugee", 2), ("humanitarian", 2), ("war ", 2),
                ("ceasefire", 3), ("peacekeeping", 3), ("military", 1),
                ("conflict", 1), ("global", 1), ("treaty", 2),
            ],
            "Health": [
                ("medical breakthrough", 3), ("clinical trial", 3), ("fda", 3),
                ("patient", 1), ("hospital", 1), ("surgeon", 2),
                ("cancer", 2), ("disease", 2), ("pandemic", 3),
                ("vaccine", 3), ("mental health", 2), ("diagnosis", 2),
                ("pharmaceutical", 3), ("drug approval", 3), ("therapy", 1),
                ("healthcare", 2), ("public health", 3), ("epidemic", 3),
                ("nutrition", 1), ("wellness", 1), ("medical", 1),
            ],
            "Sports": [
                ("championship", 3), ("tournament", 3), ("playoffs", 3),
                ("nba", 3), ("nfl", 3), ("mlb", 3), ("fifa", 3),
                ("premier league", 3), ("super bowl", 3), ("world cup", 3),
                ("athlete", 2), ("coach", 1), ("quarterback", 3),
                ("goal scorer", 3), ("transfer window", 3), ("draft pick", 3),
                ("sports", 2), ("stadium", 2), ("referee", 2),
                ("baseball", 2), ("basketball", 2), ("football", 1),
                ("soccer", 2), ("tennis", 2), ("olympics", 3),
            ],
            "Entertainment": [
                ("box office", 3), ("oscar", 3), ("grammy", 3), ("emmy", 3),
                ("blockbuster", 3), ("streaming", 1), ("netflix", 2),
                ("movie premiere", 3), ("tv show", 2), ("album release", 3),
                ("concert tour", 3), ("celebrity", 2), ("red carpet", 3),
                ("hollywood", 2), ("music video", 2), ("reality tv", 3),
                ("film", 1), ("movie", 1), ("actor", 2), ("actress", 2),
                ("director", 1), ("soundtrack", 2), ("broadway", 3),
            ],
            "Lifestyle": [
                ("travel destination", 3), ("recipe", 2), ("fashion week", 3),
                ("home decor", 3), ("personal finance", 2), ("self-care", 2),
                ("parenting", 2), ("relationship", 1), ("fitness", 2),
                ("diet", 1), ("vacation", 2), ("restaurant review", 3),
                ("real estate", 2), ("home buying", 3), ("mortgage", 2),
                ("retirement", 2), ("work-life balance", 3), ("lifestyle", 2),
            ],
        }

        scores: dict[str, float] = {cat: 0.0 for cat in CATEGORY_KEYWORDS}

        for category, keywords in CATEGORY_KEYWORDS.items():
            for keyword, weight in keywords:
                if keyword in text:
                    scores[category] += weight

        best_category = max(scores, key=lambda c: scores[c])

        # Only return the best if it has a meaningful score, otherwise "General"
        if scores[best_category] >= 2:
            return best_category
        return "General"


# Singleton instance
news_api_service = NewsAPIService()
